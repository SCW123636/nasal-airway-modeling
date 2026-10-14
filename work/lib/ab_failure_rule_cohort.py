"""Run both failure rules over the 6 problem cases and the 18 passing ones.

Purpose: decide how to fix solve_placement. The old rule (`hi = mid` on a failed
clip) reproduces the baseline exactly, and the new rule (`continue`) breaks it.
Neither is obviously right, so measure both on the cases that matter:

  * the 18 that the baseline passes - the fix must not move them
  * b05 / b15 / b18 - pure seed_lost, the ones hybrid is meant to rescue
  * b04 / b23 - anchor failures, must stay escalated
  * b20 - no point at all

Usage: python ab_failure_rule_cohort.py [case ...]
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_opening_pipeline as A
from auto_opening_placement import detect_onset, plane_basis
from export_candidate_preview import triangle_arrays

SURFACES = Path('C:/ts_work/batch27_surfaces')
PROPOSALS = Path('D:/项目/鼻腔建模/work/06_auto_landmarks')
BASELINE = Path('D:/项目/鼻腔建模/work/10_nasalseg_intake/normal_run_allow.json')


def read_surface(case):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(SURFACES / case / 'source_surface.vtp'))
    r.Update()
    return triangle_arrays(r.GetOutput())


def load_planes(case, allow_needs_review=True):
    obj = json.loads((PROPOSALS / case / 'landmarks.json').read_text(encoding='utf-8'))
    out = {}
    for name in A.OPENINGS:
        lm = obj['landmarks'][name]
        st = lm.get('status')
        if st == 'needs_review' and not allow_needs_review:
            return None
        if st not in ('proposed', 'needs_review') or not lm.get('normal_lps'):
            return None
        out[name] = {'point_lps_mm': lm['point_lps_mm'], 'normal_lps': lm['normal_lps'],
                     'roi_lps_mm': lm['roi_lps_mm'], 'keep_positive': True}
    return out


def solve(points, faces, planes, norms, onsets, failure_rule, seed_mode='roi'):
    probe_mode = 'roi'
    offsets = {k: A.SEED_OFFSET_MM for k in A.OPENINGS}
    for _ in range(A.PASSES):
        moved = False
        for name in A.OPENINGS:
            if onsets[name] is None:
                continue
            current = A.build_placed(planes, norms, onsets, offsets)
            areas, _ = A.clip_areas(points, faces, current, probe_mode)
            if areas is None or name not in areas:
                continue
            if areas[name] >= A.CAP_TARGET_MM2[name]:
                continue
            lo, hi = offsets[name], A.SEARCH_HI_MM
            for _ in range(A.BISECT_STEPS):
                mid = 0.5 * (lo + hi)
                probe = dict(current)
                probe[name] = A.place(planes[name], norms[name], onsets[name] + mid)
                a, _ = A.clip_areas(points, faces, probe, probe_mode)
                if a is None or name not in a:
                    if failure_rule == 'old':
                        hi = mid
                        offsets[name] = mid
                        moved = True
                    continue
                if a[name] >= A.CAP_TARGET_MM2[name]:
                    hi = mid
                    offsets[name] = mid
                    moved = True
                else:
                    lo = mid
        if not moved:
            break
    return offsets


def final_areas(points, faces, planes, norms, onsets, offsets, seed_mode='roi'):
    placed = A.build_placed(planes, norms, onsets, offsets)
    areas, err = A.clip_areas(points, faces, placed, seed_mode)
    if areas is None:
        return None, err
    return areas, None


def main():
    cases = sys.argv[1:] or [f'b{i:02d}' for i in range(1, 25)]
    base = json.loads(BASELINE.read_text(encoding='utf-8'))
    base = base['rows'] if isinstance(base, dict) and 'rows' in base else base
    print(f'{"case":5s} {"baseline":>10s} {"rule":6s} {"outlet":>10s} {"nostril_L":>10s} '
          f'{"nostril_R":>10s}  note')
    for case in cases:
        planes = load_planes(case)
        if planes is None:
            print(f'{case:5s} {"no_planes":>10s}')
            continue
        try:
            points, faces = read_surface(case)
        except Exception as exc:
            print(f'{case:5s} surface error: {exc}')
            continue
        norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in A.OPENINGS}
        onsets = {}
        for name in A.OPENINGS:
            o = np.asarray(planes[name]['point_lps_mm'], float)
            onsets[name], _, _ = detect_onset(points, faces, o, norms[name])
        bareas = base.get(case, {}).get('N6', {}).get('areas_mm2')
        bstate = base.get(case, {}).get('final')
        for rule in ('old', 'new'):
            off = solve(points, faces, planes, norms, onsets, rule)
            areas, err = final_areas(points, faces, planes, norms, onsets, off)
            if areas is None:
                print(f'{case:5s} {str(bstate):>10s} {rule:6s}  clip_failed: {err}')
                continue
            got = {k: round(areas[k], 2) for k in A.OPENINGS}
            match = ''
            if bareas:
                match = 'MATCH' if all(abs(got[k] - bareas[k]) < 0.01 for k in A.OPENINGS) else 'differs'
            print(f'{case:5s} {str(bstate):>10s} {rule:6s} {got["nasopharynx_outlet"]:>10.2f} '
                  f'{got["nostril_L"]:>10.2f} {got["nostril_R"]:>10.2f}  {match}')


if __name__ == '__main__':
    main()
