"""Minimal bounded ROI expansion: the least padding that clears every clip guard.

Contrast with propose_surface_scope.propose_roi, which expands the ROI by the
whole negative-side connected component. That flood leaks across the cavity on
p0 (+71.7 mm on one axis) and then collides with an earlier cap. This module
instead searches the smallest isotropic padding that makes clip_and_cap succeed,
and reports the whole ladder so the cost of the bound is visible.

Scope only: padding is a selection limit, never an anatomical claim, and never
an approval. patient_solver_allowed stays False.
"""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
import vtk

from build_reviewed_surface_drafts import load_adopted, write_surface
from ct_case_pipeline import CaseManager, read_json, sha256, write_json
from medical_review import MedicalReviewStore
from partitioned_surface import clip_and_cap
from export_candidate_preview import triangle_arrays

OPENINGS = ('nostril_L', 'nostril_R', 'nasopharynx_outlet')
LADDER_MM = (0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


def pad_roi(plane, padding_mm):
    result = copy.deepcopy(plane)
    if padding_mm <= 0:
        return result
    low = np.asarray(plane['roi_lps_mm']['min'], dtype=float) - padding_mm
    high = np.asarray(plane['roi_lps_mm']['max'], dtype=float) + padding_mm
    result['roi_lps_mm'] = {'min': low.tolist(), 'max': high.tolist()}
    return result


def try_ladder(points, faces, planes, *, ladder=LADDER_MM):
    """Return (padding, result) for the smallest padding that survives all guards."""
    trace = []
    for padding in ladder:
        padded = {name: pad_roi(planes[name], padding) for name in OPENINGS}
        try:
            out = clip_and_cap(points, faces, padded)
        except ValueError as exc:
            trace.append({'padding_mm': padding, 'status': 'fail', 'reason': str(exc)})
            continue
        trace.append({'padding_mm': padding, 'status': 'pass'})
        return padding, out, trace
    return None, None, trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-drafts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case-root', type=Path, default=Path('C:/ts_work/project_cases'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
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
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(source))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            planes = config['planes_lps']
            padding, out, trace = try_ladder(points, faces, planes)
            report = {'case': case, 'schema': 'minimal_roi_expansion/v1',
                      'source_sha256': sha256(source),
                      'point_review_sha256': sha256(config_path),
                      'ladder_mm': list(LADDER_MM), 'ladder_trace': trace,
                      'baseline_planes_lps': planes,
                      'boundary_scope_review': 'pending',
                      'oral_exclusion_review': 'pending', 'sinus_policy_review': 'pending',
                      'final_geometry_review': 'pending', 'patient_solver_allowed': False}
            if out is None:
                report['technical_status'] = 'fail'
                report['reason'] = trace[-1]['reason']
            else:
                p, f, patches, qc = out
                report['technical_status'] = 'pass'
                report['minimal_padding_mm'] = padding
                report['expanded_planes_lps'] = {n: pad_roi(planes[n], padding) for n in OPENINGS}
                report['surface_qc'] = qc
                directory = args.output / case
                directory.mkdir(exist_ok=True)
                write_surface(directory / 'minimal_scope.vtp', p, f, patches)
                report['surface_sha256'] = sha256(directory / 'minimal_scope.vtp')
            write_json(directory / 'proposal.json', report) if out is not None else None
            write_json(args.output / f'{case}.json', report)
            summary.append(report)
            print(f"{case}: {report['technical_status']} pad={report.get('minimal_padding_mm')}", flush=True)
        write_json(args.output / 'summary.json', {'cases': summary, 'patient_cfd_results': 0})
    finally:
        manager.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()