"""Is the cross-section total area even the right quantity to steer on?

Comparing the section total measured at the reviewed plane against the cap
area the production clip actually produces there:

  case  opening              section total   cap area   ratio
  p1    outlet                  704.1        172.40     0.24
  p2    outlet                  292.1        292.13     1.00
  p3    outlet                  391.4        248.17     0.63
  p3t1  outlet                  465.5        392.42     0.84
  p1    nostril_L/R          70.4/ 66.2   85.95/85.96  1.22

Two of those rows are impossible for a correct measurement: p2's ratio is
exactly 1.00 by coincidence, and for p1's nostrils the cap is LARGER than the
whole cross-section. A section that undercounts cannot steer placement.

So this script tests the alternative directly: steer on the cap area produced by
the production clip, which is the quantity that actually reaches CFD. The cap
area is monotone in the plane offset (measured: every opening's cap grows as the
plane moves inward), so a bisection on it is well posed.

Anatomical target bands, stated up front so they can be judged as priors rather
than as fitted numbers: adult nostril cross-section 50-100 mm2, nasopharyngeal
airway cross-section 150-400 mm2. The falsifiable claim is that all five
reviewed cases land inside those bands on their own geometry.
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
from partitioned_surface import clip_and_cap
from connectivity_opened_surface import flood_mask, OPENINGS
from auto_opening_placement import detect_onset, plane_basis, SRC, CASES

TARGET_MM2 = {'nostril_L': 80.0, 'nostril_R': 80.0, 'nasopharynx_outlet': 250.0}
SEARCH_LO, SEARCH_HI = -1.0, 14.0      # mm from the onset, monotonic window
BISECT_STEPS = 9                        # 15 mm / 2^9 ~= 0.03 mm


def move(spec, n, offset):
    o = np.asarray(spec['point_lps_mm'], float)
    roi = spec['roi_lps_mm']
    return {'normal_lps': spec['normal_lps'], 'keep_positive': spec['keep_positive'],
            'point_lps_mm': (o + offset * n).tolist(),
            'roi_lps_mm': {'min': (np.asarray(roi['min'], float) + offset * n).tolist(),
                           'max': (np.asarray(roi['max'], float) + offset * n).tolist()}}


def try_clip(points, faces, specs):
    """Return (cap_areas, error) without letting an exception escape."""
    try:
        sel = {k: flood_mask(points, faces, specs[k])[0] for k in OPENINGS}
        p, f, patches, _ = clip_and_cap(points, faces, specs, selectors=sel)
    except ValueError as exc:
        return None, str(exc)
    xyz = p[f]
    out = {}
    for name in OPENINGS:
        t = xyz[patches == name]
        if len(t):
            out[name] = float(np.linalg.norm(
                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5)
    return out, None


def place_one(points, faces, planes, norms, onsets, name, target):
    """Bisect this opening's offset so its cap reaches target, others held."""
    base = {k: move(planes[k], norms[k], onsets[k] + 0.5) for k in OPENINGS}
    areas, err = try_clip(points, faces, base)
    if areas is None or name not in areas:
        return None, None, err or f'{name} cap missing'
    if areas[name] >= target:
        return 0.5, areas[name], None          # already past target at onset+0.5
    lo, hi = 0.5, SEARCH_HI
    best, best_a = 0.5, areas[name]
    for _ in range(BISECT_STEPS):
        mid = 0.5 * (lo + hi)
        spec = dict(base)
        spec[name] = move(planes[name], norms[name], onsets[name] + mid)
        a, err = try_clip(points, faces, spec)
        if a is None or name not in a:
            hi = mid
            continue
        if a[name] >= target:
            hi = mid
            best, best_a = mid, a[name]
        else:
            lo = mid
    return best, best_a, None


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
            planes = {k: config['planes_lps'][k] for k in OPENINGS}
            norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
            onsets = {}
            for k in OPENINGS:
                o = np.asarray(planes[k]['point_lps_mm'], float)
                onsets[k], _, _ = detect_onset(points, faces, o, norms[k])
            for k in OPENINGS:
                off, area, err = place_one(points, faces, planes, norms, onsets,
                                           k, TARGET_MM2[k])
                rows.append({'case': case, 'opening': k,
                             'onset_mm': None if onsets[k] is None else round(onsets[k], 2),
                             'offset_from_onset_mm': None if off is None else round(off, 3),
                             'offset_from_reviewed_mm': None if off is None or onsets[k] is None
                             else round(onsets[k] + off, 2),
                             'target_mm2': TARGET_MM2[k],
                             'cap_area_mm2': None if area is None else round(area, 1),
                             'error': err})
                print(f"{case:6s} {k:18s} onset={onsets[k]} "
                      f"off={None if off is None else round(off, 2)} "
                      f"area={None if area is None else round(area, 1)} "
                      f"err={err or ''}", flush=True)
    finally:
        mgr.pool.shutdown(wait=True)

    devs = [r['offset_from_reviewed_mm'] for r in rows if r['offset_from_reviewed_mm'] is not None]
    got = [r for r in rows if r['cap_area_mm2'] is not None]
    summary = {
        'rows': len(rows), 'reached_target': len(got),
        'offset_from_reviewed': {'min': min(devs) if devs else None,
                                 'max': max(devs) if devs else None,
                                 'max_abs': max(abs(x) for x in devs) if devs else None},
        'cap_area_mm2': {k: sorted(r['cap_area_mm2'] for r in got if r['opening'] == k)
                         for k in TARGET_MM2},
        'errors': sorted({r['error'] for r in rows if r['error']}),
    }
    (out / 'cap_target_bisect.json').write_text(
        json.dumps({'schema': 'cap_target_bisect/v1', 'targets': TARGET_MM2,
                    'search_mm': [SEARCH_LO, SEARCH_HI], 'bisect_steps': BISECT_STEPS,
                    'summary': summary, 'rows': rows}, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()