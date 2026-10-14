"""Per-offset trace of the b02 outlet bisection: does every probe return None,
and does 'hybrid' differ from 'roi' AT THE FINAL POSITION?

b02's outlet cap moved 268.51 -> 177.44 between the roi baseline (normal_run_allow)
and the hybrid3 run, yet b02's report shows NO fallback fired and the offset stayed
at 0.5 mm. So the delta is NOT the fallback. This script replays the exact
placement and prints, for each probe offset, whether clip_areas returns an area -
in 'roi' mode and in 'hybrid' mode - to locate where the two diverge.

Usage: python probe_b02_outlet_bisect.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auto_opening_pipeline import (CAP_TARGET_MM2, OPENINGS, SEARCH_HI_MM,
                                   clip_areas, place)
from auto_opening_placement import detect_onset, plane_basis
from connectivity_opened_surface import flood_mask
from export_candidate_preview import triangle_arrays

SURFACE = Path('C:/ts_work/batch27_surfaces/b02/source_surface.vtp')
PROPOSALS = Path('D:/项目/鼻腔建模/work/06_auto_landmarks')
REPORT = Path('C:/ts_work/batch27_opening/b02.json')


def read_surface(path):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(path))
    r.Update()
    return triangle_arrays(r.GetOutput())


def load_planes(case):
    obj = json.loads((PROPOSALS / case / 'landmarks.json').read_text(encoding='utf-8'))
    out = {}
    for name in OPENINGS:
        lm = obj['landmarks'][name]
        out[name] = {
            'normal_lps': lm['normal_lps'],
            'keep_positive': lm.get('keep_positive', True),
            'point_lps_mm': lm['point_lps_mm'],
            'roi_lps_mm': lm['roi_lps_mm'],
        }
    return out


def main():
    case = 'b02'
    points, faces = read_surface(SURFACE)
    planes = load_planes(case)
    rep = json.loads(REPORT.read_text(encoding='utf-8'))
    print(f'{case}: {len(points)} pts, {len(faces)} faces')
    print('report seed_mode:', rep['seed_mode'],
          '| offset_from_onset:', rep['offset_from_onset_mm'],
          '| patch_areas:', rep['patch_areas_mm2'])
    print('report note[outlet]:', json.dumps(
        rep['selection_notes']['nasopharynx_outlet'], ensure_ascii=False))
    print('fallback fired?',
          rep['selection_notes']['nasopharynx_outlet'].get(
              'roi_seed_unavailable_fallback_to_rim_band', False))
    print()

    norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
    onsets = {}
    for name in OPENINGS:
        o = np.asarray(planes[name]['point_lps_mm'], float)
        onsets[name], _, _ = detect_onset(points, faces, o, norms[name])
    print('recomputed onsets:', {k: (None if v is None else round(v, 3))
                                 for k, v in onsets.items()})

    name = 'nasopharynx_outlet'
    cur = {k: place(planes[k], norms[k], onsets[k] + 0.5) for k in OPENINGS}
    print(f'\n--- probe offsets for {name} (probe size 0.5 mm) ---')
    print(f'{"offset":>8s} {"roi":>28s} {"hybrid":>28s}  same?')
    lo, hi = 0.5, SEARCH_HI_MM
    for i in range(10):
        mid = 0.5 * (lo + hi)
        probe = dict(cur)
        probe[name] = place(planes[name], norms[name], onsets[name] + mid)
        a_roi, e_roi = clip_areas(points, faces, probe, 'roi')
        a_hyb, e_hyb = clip_areas(points, faces, probe, 'hybrid')
        vr = a_roi.get(name) if a_roi else None
        vh = a_hyb.get(name) if a_hyb else None
        print(f'{mid:8.3f} {str(vr) if vr is not None else "None":>28s} '
              f'{str(vh) if vh is not None else "None":>28s}  '
              f'{"yes" if (vr is None) == (vh is None) and vr == vh else "NO <--"}')
        if a_hyb and vh is not None and vh >= CAP_TARGET_MM2[name]:
            hi = mid
        else:
            lo = mid

    print(f'\n--- final position (onset{onsets[name]:+.2f} + 0.5 = '
          f'{onsets[name] + 0.5:+.2f} mm) ---')
    final = {k: place(planes[k], norms[k], onsets[k] + 0.5) for k in OPENINGS}
    for mode in ('roi', 'hybrid'):
        a, e = clip_areas(points, faces, final, mode)
        note = ''
        try:
            sel = {k: flood_mask(points, faces, final[k], seed_mode=mode)[0]
                   for k in OPENINGS}
            _, n = flood_mask(points, faces, final[name], seed_mode=mode)
            note = json.dumps(n, ensure_ascii=False)
        except ValueError as exc:
            note = f'ValueError: {exc}'
        print(f'  {mode:6s} outlet area = '
              f'{a.get(name) if a else None}   note={note}')


if __name__ == '__main__':
    main()
