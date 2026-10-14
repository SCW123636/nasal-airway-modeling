"""Automatic opening-plane placement from the airway-lumen onset.

Criterion under test: sweep the plane inward along its own normal and take the
first offset at which the airway lumen cross-section appears. Earlier criteria
were measured and rejected - components_reached points the wrong way, and
filtering the section by the connectivity mask breaks the contour.

Grounded in two measured facts, not assumptions:
- marching cubes puts no vertex on an arbitrary plane (zero within 1e-3 mm)
  while 241-865 triangles straddle it, so the section is built from
  edge/plane intersections;
- those intersections are per-triangle duplicates, so they must be welded
  before any contour can close.

Sweep direction is +normal, into the airway: the retained side is s>0, so
moving the plane inward is what makes lumen area appear. The reference is the
five hand-reviewed positions; the detector is only trustworthy if it lands on
them without being fitted to them.
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_reviewed_surface_drafts import load_adopted
from ct_case_pipeline import CaseManager
from medical_review import MedicalReviewStore
from export_candidate_preview import triangle_arrays
from cross_section_scan import section_loops, plane_basis, SRC, OPENINGS

CASES = ('p0', 'p1', 'p2', 'p3', 'p3t1')
COARSE = 2.0          # mm, coarse sweep step
FINE = 0.25           # mm, bisection tolerance
D_START = -30.0       # mm, guaranteed outside the lumen
D_END = 30.0
AREA_ON = 50.0        # mm2, onset threshold; see separability report


def total_area(points, faces, o, n):
    areas, _, diag = section_loops(points, faces, o, n)
    return float(sum(areas)), len(areas), diag


def scan(points, faces, o, n):
    return {d: total_area(points, faces, o + d * n, n) for d in
            np.arange(D_START, D_END + 1e-9, COARSE)}


def detect_onset(points, faces, o, n, area_on=AREA_ON):
    """First offset where lumen area reaches area_on, refined to FINE."""
    curve = scan(points, faces, o, n)
    prev_d = None
    for d in sorted(curve):
        a = curve[d][0]
        if a >= area_on:
            if prev_d is None:
                return float(d), curve, d
            lo, hi = prev_d, d
            while hi - lo > FINE:
                mid = 0.5 * (lo + hi)
                am = total_area(points, faces, o + mid * n, n)[0]
                if am >= area_on:
                    hi = mid
                else:
                    lo = mid
            return float(hi), curve, d
        prev_d = d
    return None, curve, None


def main():
    work = Path(__file__).resolve().parents[1]
    out = work / '08_auto_placement'
    out.mkdir(exist_ok=True)
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    report = {'schema': 'auto_opening_placement/v1', 'criterion': 'airway_lumen_onset',
              'area_on_mm2': AREA_ON, 'coarse_mm': COARSE, 'fine_mm': FINE,
              'sweep_range_mm': [D_START, D_END], 'rows': []}
    try:
        for case in CASES:
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            for name in OPENINGS:
                spec = config['planes_lps'][name]
                n, _, _ = plane_basis(spec['normal_lps'])
                o = np.asarray(spec['point_lps_mm'], float)
                onset, curve, coarse_hit = detect_onset(points, faces, o, n)
                a0, loops0, _ = total_area(points, faces, o, n)
                row = {'case': case, 'opening': name,
                       'reviewed_offset_mm': 0.0, 'reviewed_area_mm2': round(a0, 1),
                       'reviewed_loops': loops0,
                       'onset_offset_mm': None if onset is None else round(onset, 2),
                       'reviewed_minus_onset_mm': None if onset is None else round(-onset, 2),
                       'coarse_curve': {str(d): round(curve[d][0], 1) for d in sorted(curve)}}
                report['rows'].append(row)
                print(f"{case:6s} {name:18s} onset={row['onset_offset_mm']} "
                      f"reviewed- onset={row['reviewed_minus_onset_mm']} "
                      f"area@0={a0:.1f}", flush=True)
        d = np.array([r['reviewed_minus_onset_mm'] for r in report['rows']
                      if r['reviewed_minus_onset_mm'] is not None])
        report['summary'] = {
            'rows': len(report['rows']), 'onset_found': int(len(d)),
            'reviewed_minus_onset': {'min': float(d.min()) if len(d) else None,
                                     'max': float(d.max()) if len(d) else None,
                                     'mean': round(float(d.mean()), 2) if len(d) else None},
        }
        (out / 'onset_scan.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report['summary'], indent=2))
    finally:
        mgr.pool.shutdown(wait=True)


if __name__ == '__main__':
    main()