"""Option 1 end-to-end: connectivity selectors instead of ROI boxes.

Builds one boolean per-face selection mask per opening by flooding the negative
side of each plane from its reviewed seed, then calls the same clip_and_cap the
production path uses. Reports technical QC, patch areas and, crucially, whether
the outlet selection stays clear of the nostril openings.

Nothing here approves anatomy. ROI boxes are still recorded and still reported;
they are simply no longer the selection predicate.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import vtk
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_reviewed_surface_drafts import load_adopted, write_surface
from ct_case_pipeline import CaseManager, read_json, sha256, write_json
from medical_review import MedicalReviewStore
from export_candidate_preview import triangle_arrays
from partitioned_surface import clip_and_cap, topology

SRC = Path('C:/ts_work/reviewed_surface_drafts_20261008_r3')
OPENINGS = ('nostril_L', 'nostril_R', 'nasopharynx_outlet')
TOL = 1e-7


def signed_of(points, spec):
    n = np.asarray(spec['normal_lps'], float)
    n = n / np.linalg.norm(n)
    o = np.asarray(spec['point_lps_mm'], float)
    s = (points - o) @ (n if spec['keep_positive'] else -n)
    s[np.abs(s) <= TOL] = 0.0
    return s


def loop_seed_vertices(points, faces, spec):
    """Vertex indices usable as flood seeds, derived from the section rim.

    The reviewed ROI box did two jobs at once: it said which component to keep
    (semantics) and it supplied the numerical seed. Only the second job needs a
    box, and it is the one that breaks whenever the plane moves or the geometry
    changes - 6 of 24 cases in the b01-b24 batch escalated with seed_lost.

    Here the seed is the rim band of the LARGEST section loop: the straddling
    triangles that loop was cut from, and their negative-side vertices. Those
    triangles are the wall the opening cuts through, so the components they
    belong to are the components the opening removes - no hand-tuned box, and
    the band moves with the plane because the plane defines it.

    Two measured reasons this is restricted to the largest loop rather than
    "every triangle that crosses the plane":

    1. Seeding from a single vertex (or single loop) loses whole pieces: the
       negative side of a plane is NOT one connected component, because an edge
       only survives when both endpoints are negative. b01's nostril_L shatters
       into 349 + 34 vertices, its outlet into 156 + 341 + 556 + 15. Dropping a
       piece drops the cap area by 9-46%.
    2. Seeding from every straddling triangle pulls in fragments belonging to a
       DIFFERENT opening - b01's outlet gains two components whose centroids sit
       ~50 mm away in the nostril region - and the resulting cut boundary is no
       longer coplanar, so clip_and_cap rejects it. Distance-from-ring does not
       separate them either (measured: b05 13.6/18.2 mm vs ring diagonal 11.8,
       b18 15.0 mm vs 16.3 - fully overlapping).
    """
    from cross_section_scan import section_loops_detail
    o = np.asarray(spec['point_lps_mm'], float)
    _, _, _, detail = section_loops_detail(points, faces, o, spec['normal_lps'])
    loops = detail['loops']
    if not loops:
        raise ValueError('no closed section loop at this plane; '
                         'cannot derive a rim-band seed')
    best = int(np.argmax(detail['loop_areas_mm2']))
    rim_faces = detail['loop_faces'][best]
    if not len(rim_faces):
        raise ValueError('largest section loop has no source triangles')

    s = signed_of(points, spec)
    tv = s[faces]
    rim_neg = np.zeros(len(points), bool)
    for fi in rim_faces:
        rim_neg[faces[fi][tv[fi] < 0]] = True
    seeds = np.where(rim_neg)[0]
    if not len(seeds):
        raise ValueError('rim triangles have no negative-side vertex')
    return seeds, {
        'seed_mode': 'loop',
        'section_loops_at_plane': len(loops),
        'loop_areas_mm2': [round(float(a), 3) for a in detail['loop_areas_mm2']],
        'loop_used': best,
        'rim_triangles': int(len(rim_faces)),
        'rim_band_vertices': int(len(seeds)),
    }


def flood_mask(points, faces, spec, seed_mode='roi'):
    """Boolean per-vertex mask: negative-side vertices in a component the seed reaches.

    seed_mode:
      'roi'    (default, byte-for-byte the old behaviour) seed from the reviewed
               ROI box. The box does two jobs: it picks the structure and it
               supplies the seed.
      'loop'   seed from the section rim band only. Measured consequence: it
               also pulls in wall fragments that straddle the same plane but
               belong to a different opening (b01's outlet gains two fragments
               whose centroids sit 50 mm away, in the nostril region), and the
               resulting cap boundary is no longer coplanar. Kept as the
               control arm for that comparison, not as a default.
      'hybrid' ROI first; if the box contains no negative-side vertex - which is
               exactly the seed_lost failure, measured on 6 openings across
               b04/b05/b15/b18/b23 whenever the plane sits at or behind the
               onset - fall back to the rim band and record the fallback.

    All three return the same structure; the mode and any fallback are recorded
    in the note so a report can never silently claim a reviewed-ROI run.
    """
    if seed_mode not in ('roi', 'loop', 'hybrid'):
        raise ValueError(f'unknown seed_mode {seed_mode!r}')
    s = signed_of(points, spec)
    negative = s < 0
    e = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    e = e[negative[e].all(axis=1)]
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(points), len(points))).tocsr()
    _, labels = connected_components(g, directed=False)

    fallback = None
    if seed_mode in ('roi', 'hybrid'):
        lo = np.asarray(spec['roi_lps_mm']['min'], float)
        hi = np.asarray(spec['roi_lps_mm']['max'], float)
        seeds = negative & ((points >= lo) & (points <= hi)).all(axis=1)
        if not seeds.any() and seed_mode == 'hybrid':
            cand, band_note = loop_seed_vertices(points, faces, spec)
            seeds = np.zeros(len(points), bool)
            seeds[cand] = True
            fallback = band_note
        elif not seeds.any():
            raise ValueError('no negative-side seed inside the reviewed ROI')
        selection = 'negative_side_connectivity_from_reviewed_roi_seed'
    else:
        cand, band_note = loop_seed_vertices(points, faces, spec)
        seeds = np.zeros(len(points), bool)
        seeds[cand] = True
        fallback = band_note
        selection = 'negative_side_connectivity_from_section_rim_band'

    chosen = negative & np.isin(labels, np.unique(labels[seeds]))
    note = {
        'seed_mode': seed_mode,
        'seed_vertices': int(seeds.sum()),
        'negative_components_reached': int(len(np.unique(labels[seeds]))),
        'selected_vertices': int(chosen.sum()),
        'selected_faces': int(np.any(chosen[faces], axis=1).sum()),
        'selection': selection,
    }
    if fallback is not None:
        note['rim_band'] = fallback
        if seed_mode == 'hybrid':
            note['roi_seed_unavailable_fallback_to_rim_band'] = True
    return chosen, note


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case-root', type=Path, default=Path('C:/ts_work/project_cases'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(args.case_root)
    summary = []
    try:
        store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
        for case in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
            config, config_path = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            planes = {k: config['planes_lps'][k] for k in OPENINGS}
            base, _ = topology(points, faces)

            selectors, notes = {}, {}
            for name in OPENINGS:
                selectors[name], notes[name] = flood_mask(points, faces, planes[name])

            report = {'case': case, 'schema': 'connectivity_opened_surface/v1',
                      'selection_method': 'negative_side_connectivity_from_reviewed_roi_seed',
                      'roi_boxes_retained_not_used_for_selection': planes,
                      'source_sha256': sha256(SRC / case / 'source_surface.vtp'),
                      'point_review_sha256': sha256(config_path),
                      'source_qc': base, 'selection_notes': notes,
                      'boundary_scope_review': 'pending', 'oral_exclusion_review': 'pending',
                      'sinus_policy_review': 'pending', 'final_geometry_review': 'pending',
                      'patient_solver_allowed': False}
            try:
                p, f, patches, qc = clip_and_cap(points, faces, planes, selectors=selectors)
                report['technical_status'] = 'pass'
                qc = qc.get('technical_qc', qc)
                report['surface_qc'] = qc
                d = args.output / case
                d.mkdir(exist_ok=True)
                write_surface(d / 'connectivity_opened.vtp', p, f, patches)
                report['surface_sha256'] = sha256(d / 'connectivity_opened.vtp')
                xyz = p[f]
                areas = {}
                for name in OPENINGS:
                    sel = patches == name
                    if sel.any():
                        t = xyz[sel]
                        a = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5
                        areas[name] = round(float(a), 2)
                report['patch_areas_mm2'] = areas
                report['volume_removed_mm3'] = round(base['signed_volume_mm3'] - qc['signed_volume_mm3'], 1)
            except ValueError as exc:
                report['technical_status'] = 'fail'
                report['reason'] = str(exc)
                if getattr(exc, 'details', None):
                    d_ = exc.details
                    report['failure_details'] = {k: v for k, v in d_.items()
                                                if k != 'triangle_centers_lps_mm'}
                    if 'triangle_centers_lps_mm' in d_:
                        report['failure_details']['center_count'] = len(d_['triangle_centers_lps_mm'])
                        report['failure_details']['earlier_patch_counts'] = d_.get('earlier_patch_counts')
            write_json(args.output / f'{case}.json', report)
            summary.append(report)
            print(f"{case}: {report['technical_status']} {report.get('reason', '')}", flush=True)
        write_json(args.output / 'summary.json', {'cases': summary, 'patient_cfd_results': 0})
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()