"""Option 1 feasibility probe: select openings by negative-side connectivity.

The box ROI fails because it is a rectangular proxy for "which wall is the
opening". This probe replaces it with the thing the box was trying to
approximate: flood the negative side from the reviewed seed and keep only the
components the seed actually reaches.

What it measures, per case and opening:
  n_components      how many separate negative-side components exist at all
  reached           components the seed flood reaches
  selected_frac     fraction of the whole surface in the selected set
  removed_volume    signed volume lost, and whether it stays monotone
  touches_nostril   whether any nostril cap region ends up inside the deleted
                    set -- the real failure mode, since the outlet plane sits
                    ABOVE the nostril planes in all five cases

Feasibility only: nothing here is an approval or an anatomical claim.
"""
import sys
from pathlib import Path

import numpy as np
import vtk
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_reviewed_surface_drafts import load_adopted
from ct_case_pipeline import CaseManager
from medical_review import MedicalReviewStore
from export_candidate_preview import triangle_arrays
from partitioned_surface import topology

SRC = Path('C:/ts_work/reviewed_surface_drafts_20261008_r3')
TOL = 1e-7


def signed_distance(points, spec):
    n = np.asarray(spec['normal_lps'], float)
    n = n / np.linalg.norm(n)
    o = np.asarray(spec['point_lps_mm'], float)
    s = (points - o) @ (n if spec['keep_positive'] else -n)
    s[np.abs(s) <= TOL] = 0.0
    return s


def components(points, faces, negative):
    """Connected components of the negative side, edges restricted to it."""
    e = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    e = e[negative[e].all(axis=1)]
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(len(points), len(points))).tocsr()
    n_comp, labels = connected_components(g, directed=False)
    return n_comp, labels


def probe(points, faces, planes, name):
    spec = planes[name]
    roi = spec['roi_lps_mm']
    lo, hi = np.asarray(roi['min'], float), np.asarray(roi['max'], float)
    s = signed_distance(points, spec)
    negative = s < 0
    n_comp, labels = components(points, faces, negative)

    seeds = negative & ((points >= lo) & (points <= hi)).all(axis=1)
    if not seeds.any():
        return {'opening': name, 'status': 'no_seed'}
    reach = np.unique(labels[seeds])
    chosen = negative & np.isin(labels, reach)

    sel_faces = np.any(chosen[faces], axis=1)
    frac = float(sel_faces.mean())
    kept = ~sel_faces
    qc_kept, _ = topology(points, faces[kept])

    # does the deleted set reach the nostril cap regions?
    reach_nostril = {}
    for other in ('nostril_L', 'nostril_R'):
        if other == name:
            continue
        o_spec = planes[other]
        o_lo, o_hi = np.asarray(o_spec['roi_lps_mm']['min'], float), np.asarray(o_spec['roi_lps_mm']['max'], float)
        in_other = ((points >= o_lo) & (points <= o_hi)).all(axis=1)
        both = chosen & in_other
        other_neg = signed_distance(points, o_spec) < 0
        reach_nostril[other] = {
            'chosen_in_other_roi': int(both.sum()),
            'of_which_other_negative': int((both & other_neg).sum()),
        }

    # how much does the negative wall reach past the ROI box on each axis?
    neg_pts = points[negative]
    beyond = {
        'below_min_mm': np.round(np.maximum(lo - neg_pts.min(axis=0), 0), 1).tolist(),
        'above_max_mm': np.round(np.maximum(neg_pts.max(axis=0) - hi, 0), 1).tolist(),
    }
    return {'opening': name, 'status': 'ok',
            'n_components_total': int(n_comp),
            'components_reached': int(len(reach)),
            'seed_vertices': int(seeds.sum()),
            'selected_vertex_frac': round(float(chosen.sum() / negative.sum()), 3),
            'selected_face_frac': round(frac, 4),
            'kept_signed_volume_mm3': round(qc_kept['signed_volume_mm3'], 1),
            'negative_extent_beyond_roi': beyond,
            'nostril_overlap': reach_nostril}


def main():
    work = Path(__file__).resolve().parents[1]
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    try:
        for case in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            planes = {k: config['planes_lps'][k] for k in ('nostril_L', 'nostril_R', 'nasopharynx_outlet')}
            qc, _ = topology(points, faces)
            print('=' * 20, case, 'tris', len(faces), 'vol_mm3', round(qc['signed_volume_mm3'], 1))
            for name in ('nostril_L', 'nostril_R', 'nasopharynx_outlet'):
                r = probe(points, faces, planes, name)
                if r['status'] != 'ok':
                    print('  ', name, r)
                    continue
                print(f"   {name}: neg_components={r['n_components_total']} reached={r['components_reached']} "
                      f"seedV={r['seed_vertices']} selVfrac={r['selected_vertex_frac']} "
                      f"selF={r['selected_face_frac']} keptVol={r['kept_signed_volume_mm3']}")
                print('      neg wall beyond roi: below', r['negative_extent_beyond_roi']['below_min_mm'],
                      'above', r['negative_extent_beyond_roi']['above_max_mm'])
                for k, v in r['nostril_overlap'].items():
                    flag = '  <-- COLLISION' if v['of_which_other_negative'] else ''
                    print(f"      vs {k}: inROI={v['chosen_in_other_roi']} alsoNegative={v['of_which_other_negative']}{flag}")
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()