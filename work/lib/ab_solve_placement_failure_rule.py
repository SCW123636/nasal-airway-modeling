"""Decisive experiment: does the solve_placement 'clip_failed' fix explain the
b02 outlet change 268.51 -> 177.44?

Timeline of the evidence:
  * b02 surface, masks and landmarks are all bit-for-bit reproducible (verified by
    rerun today: five mask shas identical, surface sha identical, landmarks sha
    identical).
  * baseline normal_run_allow.json (10-12) recorded the outlet cap as 268.51 with
    nostril_L/R 91.01/81.68 - and the nostrils are STILL 91.01/81.68 today.
  * hybrid3 records the same nostrils but outlet 177.44.
  * The only code changed between those two runs is solve_placement: the old code
    read a failed clip as `hi = mid` (push the window inwards), the new code reads
    it as "unknown, leave the bracket alone" (`continue`).

This script runs solve_placement twice on the identical inputs, once with each
failure rule, and reports the resulting outlet offset and cap area. If the old
rule reproduces 268.51 and the new rule reproduces 177.44, the fix - not the
seeding - is what moved the number.

Usage: python ab_solve_placement_failure_rule.py
"""
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_opening_pipeline as A
from auto_opening_placement import detect_onset, plane_basis
from export_candidate_preview import triangle_arrays

SURFACE = Path('C:/ts_work/batch27_surfaces/b02/source_surface.vtp')
PROPOSALS = Path('D:/项目/鼻腔建模/work/06_auto_landmarks')


def read_surface(path):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(path))
    r.Update()
    return triangle_arrays(r.GetOutput())


def load_planes(case):
    import json
    obj = json.loads((PROPOSALS / case / 'landmarks.json').read_text(encoding='utf-8'))
    out = {}
    for name in A.OPENINGS:
        lm = obj['landmarks'][name]
        out[name] = {'point_lps_mm': lm['point_lps_mm'], 'normal_lps': lm['normal_lps'],
                     'roi_lps_mm': lm['roi_lps_mm'], 'keep_positive': True}
    return out


def solve(points, faces, planes, norms, onsets, failure_rule):
    """Copy of solve_placement with a switchable failure rule.

    failure_rule='old' : a None clip is read as `hi = mid` (the pre-fix code)
    failure_rule='new' : a None clip is read as unknown; bracket untouched
    """
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


def main():
    points, faces = read_surface(SURFACE)
    planes = load_planes('b02')
    norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in A.OPENINGS}
    onsets = {}
    for name in A.OPENINGS:
        o = np.asarray(planes[name]['point_lps_mm'], float)
        onsets[name], _, _ = detect_onset(points, faces, o, norms[name])
    print('onsets:', {k: round(v, 3) for k, v in onsets.items()})

    for rule in ('old', 'new'):
        off = solve(points, faces, planes, norms, onsets, rule)
        placed = A.build_placed(planes, norms, onsets, off)
        areas, _ = A.clip_areas(points, faces, placed, 'roi')
        print(f'\nfailure_rule={rule}')
        print('  offsets:', {k: round(v, 3) for k, v in off.items()})
        print('  cap areas:', {k: (None if areas is None else round(areas[k], 2))
                               for k in A.OPENINGS} if areas else None)


if __name__ == '__main__':
    main()
