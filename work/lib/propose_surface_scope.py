"""Explore component-bound ROI proposals while preserving reviewed points.

Only negative-side mesh connectivity sets the proposal extent. This is a
numerical scope proposal, never an anatomical classifier or boundary review.
"""
import argparse
import copy
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
import vtk

from build_reviewed_surface_drafts import candidate_inputs, load_adopted, write_surface
from ct_case_pipeline import CaseManager, read_json, sha256, write_json
from medical_review import MedicalReviewStore
from partitioned_surface import clip_and_cap
from export_candidate_preview import triangle_arrays


def propose_roi(points, faces, plane, *, padding_mm=.5):
    if not np.isfinite(padding_mm) or padding_mm <= 0:
        raise ValueError('Padding must be finite and positive')
    result = copy.deepcopy(plane)
    normal = np.asarray(plane['normal_lps'], dtype=float)
    origin = np.asarray(plane['point_lps_mm'], dtype=float)
    roi = plane['roi_lps_mm']
    low, high = np.asarray(roi['min'], dtype=float), np.asarray(roi['max'], dtype=float)
    if (any(v.shape != (3,) or not np.isfinite(v).all() for v in (normal, origin, low, high))
            or np.linalg.norm(normal) < 1e-12 or np.any(low >= high)
            or type(plane.get('keep_positive')) is not bool):
        raise ValueError('Invalid clipping plane or ROI')
    normal /= np.linalg.norm(normal)
    signed = (points - origin) @ normal
    if not plane['keep_positive']:
        signed = -signed
    negative = signed < -1e-7
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges = edges[negative[edges].all(axis=1)]
    graph = coo_matrix((np.ones(len(edges)), (edges[:, 0], edges[:, 1])),
                       shape=(len(points), len(points))).tocsr()
    _, labels = connected_components(graph, directed=False)
    seeds = negative & ((points >= roi['min']) & (points <= roi['max'])).all(axis=1)
    if not seeds.any():
        raise ValueError('No negative-side vertices inside original ROI')
    chosen = negative & np.isin(labels, np.unique(labels[seeds]))
    adjacent = np.any(chosen[faces], axis=1)
    extent = points[np.unique(faces[adjacent])]
    low = np.minimum(roi['min'], extent.min(axis=0) - padding_mm)
    high = np.maximum(roi['max'], extent.max(axis=0) + padding_mm)
    result['roi_lps_mm'] = {'min': low.tolist(), 'max': high.tolist()}
    result['point_localization_status'] = plane.get('status', 'unspecified')
    result['status'] = 'proposed_scope'
    return result, {'selected_negative_vertices': int(chosen.sum()),
                    'selected_negative_components': len(np.unique(labels[chosen])),
                    'roi_expansion_min_mm': (np.asarray(roi['min']) - low).tolist(),
                    'roi_expansion_max_mm': (high - np.asarray(roi['max'])).tolist(),
                    'point_unchanged': True, 'normal_unchanged': True,
                    'boundary_scope_review': 'pending', 'patient_solver_allowed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-drafts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case-root', type=Path, default=Path('C:/ts_work/project_cases'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    work = Path(__file__).resolve().parents[1]
    manager = CaseManager(args.case_root)
    summary = []
    try:
        store = MedicalReviewStore(manager, work / '06_auto_landmarks')
        for case in ('p0', 'p1', 'p2', 'p3', 'p3t1'):
            config, config_path = load_adopted(store, case)
            source = args.source_drafts / case / 'source_surface.vtp'
            previous = read_json(args.source_drafts / case / 'report.json')
            if sha256(source) != previous['artifacts']['source_surface.vtp']:
                raise ValueError('Source draft changed')
            if sha256(config_path) != previous['inputs']['point_review']:
                raise ValueError('Point review differs from source draft')
            inputs = candidate_inputs(case, work / '05_ts_seg', config, config_path)[3]
            if inputs != previous['inputs']:
                raise ValueError('Current candidate differs from source draft')
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(source))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            proposed, details = {}, {}
            for name in ('nostril_L', 'nostril_R', 'nasopharynx_outlet'):
                proposed[name], details[name] = propose_roi(points, faces, config['planes_lps'][name])
            directory = args.output / case
            directory.mkdir()
            report = {'case': case, 'schema': 'surface_scope_proposal/v1', 'controls': proposed,
                      'scope_changes': details, 'source_sha256': sha256(source),
                      'point_review_sha256': sha256(config_path), 'scope_review': 'pending',
                      'inputs': inputs,
                      'oral_exclusion_review': 'pending', 'sinus_policy_review': 'pending',
                      'final_geometry_review': 'pending', 'patient_solver_allowed': False}
            try:
                p, f, patches, qc = clip_and_cap(points, faces, proposed)
                write_surface(directory / 'scope_proposal.vtp', p, f, patches)
                report['technical_status'] = 'pass'
                report['surface_qc'] = qc
                report['surface_sha256'] = sha256(directory / 'scope_proposal.vtp')
            except ValueError as exc:
                report['technical_status'] = 'fail'
                report['reason'] = str(exc)
                if getattr(exc, 'details', None):
                    report['failure_details'] = exc.details
            if sha256(source) != previous['artifacts']['source_surface.vtp']:
                raise ValueError('Source changed during proposal')
            load_adopted(store, case)
            if inputs != candidate_inputs(case, work / '05_ts_seg', config, config_path)[3]:
                raise ValueError('Candidate changed during proposal')
            write_json(directory / 'proposal.json', report)
            summary.append(report)
            print(case + ': ' + report['technical_status'] + ' ' + report.get('reason', ''), flush=True)
        write_json(args.output / 'summary.json', {'cases': summary, 'patient_cfd_results': 0})
    finally:
        manager.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()
