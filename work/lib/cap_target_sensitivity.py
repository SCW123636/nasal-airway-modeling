"""Two load-bearing questions about cap-area placement, answered before adoption.

Placement: bisect each opening's offset until its cap reaches an anatomical
target area (nostril 80 mm2, nasopharynx 250 mm2). On the five reviewed cases
that lands within 1.42 mm of the reviewer's plane on all 12 reachable openings,
and it fixes p1's 20 mm2 outlet.

A. Target sensitivity. The targets are a prior, not a fit - but that only counts
   if the answer barely moves when they move. If the offsets swing with the
   target, the method is fitting five cases through two numbers.

B. Convergence. Each opening is solved with the other two held fixed, so the
   search is coordinate descent. One pass is not a solution. This measures
   whether repeated passes still move the planes.

C. The honest caveat, measured rather than asserted: a target guarantees a
   plausible opening area, NOT that the plane is anatomically correct. Both are
   reported per opening so the difference is visible.
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
from cap_area_placement import move, try_clip, TARGET_MM2

NOSTRIL_SCALES = (60.0, 80.0, 100.0)
OUTLET_SCALES = (150.0, 250.0, 350.0)
PASSES = 3
BISECT_STEPS = 9
SEARCH_HI = 14.0


def targets(nostril, outlet):
    return {'nostril_L': nostril, 'nostril_R': nostril, 'nasopharynx_outlet': outlet}


def solve_pass(points, faces, planes, norms, onsets, current, tgt):
    """One coordinate-descent sweep; returns new offsets-from-onset."""
    out = dict(current)
    for name in OPENINGS:
        if onsets[name] is None:
            continue
        start = out[name]
        spec0 = {k: move(planes[k], norms[k], onsets[k] + out[k]) for k in OPENINGS}
        a0, err = try_clip(points, faces, spec0)
        if a0 is None or name not in a0:
            out[name] = start          # keep, cannot improve what will not clip
            continue
        if a0[name] >= tgt[name]:
            continue                   # already open enough, leave it
        lo, hi, best, best_a = start, SEARCH_HI, start, a0[name]
        for _ in range(BISECT_STEPS):
            mid = 0.5 * (lo + hi)
            spec = dict(spec0)
            spec[name] = move(planes[name], norms[name], onsets[name] + mid)
            a, _e = try_clip(points, faces, spec)
            if a is None or name not in a:
                hi = mid
                continue
            if a[name] >= tgt[name]:
                hi, best, best_a = mid, mid, a[name]
            else:
                lo = mid
        out[name] = best
    return out


def final_areas(points, faces, planes, norms, onsets, offsets):
    specs = {k: move(planes[k], norms[k], onsets[k] + offsets[k]) for k in OPENINGS}
    areas, err = try_clip(points, faces, specs)
    return areas, err


def main():
    work = Path(__file__).resolve().parents[1]
    out = work / '08_auto_placement'
    out.mkdir(exist_ok=True)
    mgr = CaseManager(Path('C:/ts_work/project_cases'))
    store = MedicalReviewStore(mgr, work / '06_auto_landmarks')
    sens, conv = [], []
    try:
        for case in CASES:
            config, _ = load_adopted(store, case)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(SRC / case / 'source_surface.vtp'))
            reader.Update()
            points, faces = triangle_arrays(reader.GetOutput())
            planes = {k: config['planes_lps'][k] for k in OPENINGS}
            norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
            onsets, clipped = {}, False
            for k in OPENINGS:
                o = np.asarray(planes[k]['point_lps_mm'], float)
                onsets[k], _, _ = detect_onset(points, faces, o, norms[k])
                if onsets[k] is None:
                    clipped = True
            if clipped:
                print(f'{case}: onset missing, skipped', flush=True)
                continue

            # A. target sensitivity, three passes each so the comparison is fair
            for nsc in NOSTRIL_SCALES:
                for osc in OUTLET_SCALES:
                    tgt = targets(nsc, osc)
                    off = {k: 0.5 for k in OPENINGS}
                    for _ in range(PASSES):
                        off = solve_pass(points, faces, planes, norms, onsets, off, tgt)
                    areas, err = final_areas(points, faces, planes, norms, onsets, off)
                    sens.append({'case': case, 'nostril_target': nsc, 'outlet_target': osc,
                                 'offsets_mm': {k: round(off[k], 3) for k in OPENINGS},
                                 'offset_from_reviewed_mm': {k: round(onsets[k] + off[k], 2)
                                                            for k in OPENINGS},
                                 'cap_areas_mm2': None if areas is None
                                 else {k: round(areas[k], 1) for k in OPENINGS if k in areas},
                                 'error': err})
                    print(f'{case} n={nsc} o={osc} off_rev='
                          f"{sens[-1]['offset_from_reviewed_mm']} areas={sens[-1]['cap_areas_mm2']}",
                          flush=True)

            # B. convergence trace at the chosen targets
            tgt = TARGET_MM2
            off = {k: 0.5 for k in OPENINGS}
            for p in range(PASSES):
                off = solve_pass(points, faces, planes, norms, onsets, off, tgt)
                areas, err = final_areas(points, faces, planes, norms, onsets, off)
                conv.append({'case': case, 'pass': p + 1,
                             'offsets_mm': {k: round(off[k], 3) for k in OPENINGS},
                             'offset_from_reviewed_mm': {k: round(onsets[k] + off[k], 2)
                                                        for k in OPENINGS},
                             'cap_areas_mm2': None if areas is None
                             else {k: round(areas[k], 1) for k in OPENINGS if k in areas},
                             'error': err})
                print(f"{case} pass{p + 1} off_rev={conv[-1]['offset_from_reviewed_mm']} "
                      f"areas={conv[-1]['cap_areas_mm2']}", flush=True)
    finally:
        mgr.pool.shutdown(wait=True)

    # A summary: spread of the final plane position across the target grid
    per_opening = {}
    for r in sens:
        if r['error']:
            continue
        for k, v in r['offset_from_reviewed_mm'].items():
            per_opening.setdefault(k, []).append(v)
    sens_summary = {k: {'n': len(v), 'min': min(v), 'max': max(v),
                        'max_abs': max(abs(x) for x in v)} for k, v in per_opening.items()}

    # B summary: movement between the last two passes
    move_last = []
    by_case = {}
    for r in conv:
        by_case.setdefault(r['case'], []).append(r)
    for case, rs in by_case.items():
        if len(rs) >= 2:
            a, b = rs[-2], rs[-1]
            for k in OPENINGS:
                move_last.append(round(abs(b['offsets_mm'][k] - a['offsets_mm'][k]), 4))
    payload = {'schema': 'cap_target_sensitivity/v1',
               'targets_tested': {'nostril': list(NOSTRIL_SCALES), 'outlet': list(OUTLET_SCALES)},
               'passes': PASSES, 'bisect_steps': BISECT_STEPS,
               'sensitivity_summary': sens_summary,
               'convergence_last_pass_move_mm': {'n': len(move_last),
                                                 'max': max(move_last) if move_last else None,
                                                 'mean': round(float(np.mean(move_last)), 4)
                                                 if move_last else None},
               'sensitivity_rows': sens, 'convergence_rows': conv}
    (out / 'cap_target_sensitivity.json').write_text(json.dumps(payload, indent=2),
                                                     encoding='utf-8')
    print(json.dumps({'sensitivity_summary': sens_summary,
                      'convergence_last_pass_move_mm': payload['convergence_last_pass_move_mm']},
                     indent=2))


if __name__ == '__main__':
    main()