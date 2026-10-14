"""Why is p1's outlet area 20 mm2 when the reviewer got 172 mm2?

p1 is the one case where onset+0.5 lands badly: the other three land in
364-442 mm2. The reason is visible in the definition - onset is the first
offset reaching AREA_ON=50 mm2, and for p1's outlet the nasopharynx opens
slowly, so +0.5 mm still sits in the tapered tip.

This script measures the candidates rather than guessing at a fix:

  per-opening threshold  the airway has two structurally different openings
      (nostrils ~57-118 mm2, nasopharyngeal outlet ~170-470 mm2); one shared
      50 mm2 threshold cannot serve both
  steepest expansion     the offset of maximum d(area)/d(offset), i.e. where the
      lumen stops being a tip and starts being a passage
  area quantile          the offset at which the section first reaches a fixed
      fraction of the section at the reviewed position

Reported per case and opening, and always against the reviewed plane, so any
candidate that merely happens to fit these five cases is visible as such.
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
from auto_opening_placement import CASES, detect_onset, AREA_ON, COARSE, D_START, D_END

FINE = 0.25
NOSTRIL_ON = 50.0
OUTLET_ON = 150.0
QUANTILE = 0.5


def area_at(points, faces, o, n, d):
    return float(sum(section_loops(points, faces, o + d * n, n)[0]))


def refine_threshold(points, faces, o, n, lo, hi, target):
    """Bisect to FINE on (area - target) crossing zero. `hi` must satisfy it.

    Written against the target explicitly on purpose: an earlier version
    compared `area >= 0`, which is true everywhere, and silently collapsed
    every candidate to the coarse lower bracket (-1.75 mm, area ~0).
    """
    while hi - lo > FINE:
        mid = 0.5 * (lo + hi)
        if area_at(points, faces, o, n, mid) >= target:
            hi = mid
        else:
            lo = mid
    return hi


def bisect_threshold(points, faces, o, n, area_on):
    prev = None
    for d in np.arange(D_START, D_END + 1e-9, COARSE):
        if area_at(points, faces, o, n, d) >= area_on:
            if prev is None:
                return float(d)
            return refine_threshold(points, faces, o, n, prev, d, area_on)
        prev = d
    return None


def bisect_quantile(points, faces, o, n, target):
    prev = None
    for d in np.arange(D_START, D_END + 1e-9, COARSE):
        if area_at(points, faces, o, n, d) >= target:
            if prev is None:
                return float(d)
            return refine_threshold(points, faces, o, n, prev, d, target)
        prev = d
    return None


def steepest(points, faces, o, n):
    ds = np.arange(-8.0, 30.0 + 1e-9, 0.5)
    a = np.array([area_at(points, faces, o, n, d) for d in ds])
    i = int(np.argmax(np.diff(a)))
    return float(ds[i]), float(np.diff(a)[i])


def main():
    work = Path(__file__).resolve().parents[1]
    out = work / '08_auto_placement'
    out.mkdir(exist_ok=True)
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    rows = []
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
                a_rev = area_at(points, faces, o, n, 0.0)
                thr = OUTLET_ON if name == 'nasopharynx_outlet' else NOSTRIL_ON
                cand = {
                    'case': case, 'opening': name,
                    'reviewed_area_mm2': round(a_rev, 1),
                    'onset_50': bisect_threshold(points, faces, o, n, AREA_ON),
                    'onset_per_opening': bisect_threshold(points, faces, o, n, thr),
                    'steepest_offset': steepest(points, faces, o, n)[0],
                    'steepest_slope': round(steepest(points, faces, o, n)[1], 1),
                    'quantile_50pct': bisect_quantile(points, faces, o, n,
                                                      QUANTILE * a_rev),
                }
                for k in ('onset_50', 'onset_per_opening', 'steepest_offset', 'quantile_50pct'):
                    v = cand[k]
                    cand[k + '_minus_reviewed'] = None if v is None else round(v, 2)
                    cand[k + '_area'] = None if v is None else round(
                        area_at(points, faces, o, n, v), 1)
                rows.append(cand)
                print(f"{case:6s} {name:18s} rev={a_rev:7.1f} "
                      f"on50={cand['onset_50_area']:8.1f}@{cand['onset_50_minus_reviewed']:+6.2f} "
                      f"perOp={cand['onset_per_opening_area']:8.1f}@{cand['onset_per_opening_minus_reviewed']:+6.2f} "
                      f"steep={cand['steepest_offset_area']:8.1f}@{cand['steepest_offset_minus_reviewed']:+6.2f} "
                      f"q50={cand['quantile_50pct_area']:8.1f}@{cand['quantile_50pct_minus_reviewed']:+6.2f}",
                      flush=True)
    finally:
        mgr.pool.shutdown(wait=True)

    def spread(key):
        v = [r[key + '_minus_reviewed'] for r in rows if r[key + '_minus_reviewed'] is not None]
        return {'n': len(v), 'min': min(v), 'max': max(v),
                'max_abs': max(abs(x) for x in v)}

    summary = {k: spread(k) for k in ('onset_50', 'onset_per_opening',
                                      'steepest_offset', 'quantile_50pct')}
    summary['reviewed_area_mm2'] = {
        'nostril': sorted(r['reviewed_area_mm2'] for r in rows if r['opening'] != 'nasopharynx_outlet'),
        'outlet': sorted(r['reviewed_area_mm2'] for r in rows if r['opening'] == 'nasopharynx_outlet')}
    (out / 'candidates.json').write_text(
        json.dumps({'schema': 'opening_placement_candidates/v1', 'summary': summary,
                    'nostril_on': NOSTRIL_ON, 'outlet_on': OUTLET_ON,
                    'quantile': QUANTILE, 'rows': rows}, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()