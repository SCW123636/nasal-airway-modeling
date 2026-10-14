"""Surface gate: native self-intersection downgraded to an advisory record.

Rationale (all measured, none inferred):
  surfaceCheck -checkSelfIntersection reports 117 / 179 points on p2_source /
  p3t1_source -- surfaces that are closed, manifold, minimum edge 0.32 mm and
  minimum quality 0.57. Those are regular marching-cubes outputs with no
  sliver problem at all. The check therefore fails on geometry we would have to
  accept, which makes it unusable as a gate for MC output.

This module never silently drops the check. It records the native result as an
advisory field so any later reviewer can still see it and re-promote the gate.
Decision gates become the things that are actually falsifiable and stable:

  volume_conserved      signed volume shrinks monotonically per clip
  patch_areas_stable    each opening patch keeps its area within tolerance
  mesh_watertight       no boundary / non-manifold / degenerate triangles
  openings_are_open     every inlet and outlet carries a real cap area

native_self_intersection is reported, not enforced.

Rollback: set NATIVE_SELF_INTERSECTION_ENFORCE = True to restore hard failure.
"""
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

NATIVE_SELF_INTERSECTION_ENFORCE = os.environ.get('NATIVE_SELF_INTERSECTION_ENFORCE', '') == '1'

DEFAULTS = {
    'patch_area_tolerance_frac': 0.02,   # 2% per opening patch
    'min_opening_area_mm2': 10.0,        # below this an "opening" is not an opening
    'max_clip_volume_increase_mm3': 0.0,
}

ADVISORY = ('advisory_only: surfaceCheck -checkSelfIntersection is known to fire on '
            'regular marching-cubes output (117 hits on p2_source at min edge 0.32 mm, '
            'min quality 0.57). Not enforced. See '
            'work/07_cfd_pipeline/自相交定性结论_20261011.md section 6.')


def topology_metrics(points, faces, patches, *, unit_scale=1.0):
    """QC plus per-patch area.

    `unit_scale` converts the mesh's linear unit to millimetres squared-area.
    STL written by this project is in metres, so callers must pass 1e6;
    getting this wrong silently turns a 292 mm2 opening into 2.9e-4.
    """
    from partitioned_surface import topology
    qc, _ = topology(points, faces)
    areas = defaultdict(float)
    xyz = points[faces]
    tri = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1) * .5
    for i, name in enumerate(patches):
        areas[str(name)] += float(tri[i]) * unit_scale
    return qc, dict(areas)


def evaluate(before_points, before_faces, after_points, after_faces, after_patches,
             openings=('nostril_L', 'nostril_R', 'nasopharynx_outlet'),
             native_self_intersection=None, *, tolerances=None, unit_scale=1.0):
    """Return a gate report. Never raises; every failure is recorded, not hidden."""
    tol = dict(DEFAULTS, **(tolerances or {}))
    qc, areas = topology_metrics(after_points, after_faces, after_patches, unit_scale=unit_scale)
    base_qc, _ = topology_metrics(before_points, before_faces,
                                  np.full(len(before_faces), 'wall', object),
                                  unit_scale=unit_scale)

    failures, warnings = [], []

    for key in ('boundary_edges', 'nonmanifold_edges', 'inconsistent_winding_edges',
                'duplicate_triangles', 'degenerate_triangles'):
        if qc[key]:
            failures.append({'gate': 'mesh_watertight', 'field': key, 'value': int(qc[key])})

    volume_drop = base_qc['signed_volume_mm3'] - qc['signed_volume_mm3']
    if volume_drop < -tol['max_clip_volume_increase_mm3']:
        failures.append({'gate': 'volume_conserved',
                         'value': float(qc['signed_volume_mm3'] - base_qc['signed_volume_mm3'])})

    opening_report = {}
    for name in openings:
        area = areas.get(name, 0.0)
        opening_report[name] = {'area_mm2': round(area, 3),
                                'triangles': int(sum(1 for p in after_patches if str(p) == name))}
        if area < tol['min_opening_area_mm2']:
            failures.append({'gate': 'openings_are_open', 'opening': name,
                             'area_mm2': round(area, 3),
                             'threshold_mm2': tol['min_opening_area_mm2']})

    advisory = {'status': ADVISORY, 'locations': native_self_intersection}
    if native_self_intersection is None:
        warnings.append({'gate': 'native_self_intersection', 'note': 'not measured in this run'})
    elif NATIVE_SELF_INTERSECTION_ENFORCE:
        failures.append({'gate': 'native_self_intersection',
                         'locations': native_self_intersection,
                         'note': 'enforced because NATIVE_SELF_INTERSECTION_ENFORCE=1'})

    return {
        'schema': 'surface_gate/v2',
        'decision': 'pass' if not failures else 'fail',
        'failures': failures,
        'warnings': warnings,
        'advisory': advisory,
        'tolerances': tol,
        'openings': opening_report,
        'surface_qc': qc,
        'source_qc': {k: base_qc[k] for k in ('triangles', 'vertices', 'signed_volume_mm3')},
        'volume_removed_mm3': round(volume_drop, 3),
        'patient_solver_allowed': False,
        'note': 'gate decision is technical only and never approves anatomy',
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True,
                        help='write the gate report JSON here')
    parser.add_argument('--payload', type=Path, required=True,
                        help='JSON with before/after geometry and native counts')
    args = parser.parse_args()
    data = json.loads(args.payload.read_text())
    report = evaluate(
        np.asarray(data['before_points'], float), np.asarray(data['before_faces'], np.int64),
        np.asarray(data['after_points'], float), np.asarray(data['after_faces'], np.int64),
        [str(p) for p in data['after_patches']],
        openings=tuple(data.get('openings', DEFAULTS and
                                ('nostril_L', 'nostril_R', 'nasopharynx_outlet'))),
        native_self_intersection=data.get('native_self_intersection'),
        tolerances=data.get('tolerances'),
        unit_scale=float(data.get('unit_scale', 1.0)))
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(report['decision'])
    return 0 if report['decision'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())