"""Measure what the negative side of an opening plane actually is.

The anchored-seed probe showed the reviewed-plane selection can evaporate when
the plane moves 1.25 mm: b15's outlet anchor keeps 1 of 2324 vertices at
onset+0.5, b18 keeps 0 of 1304, while b05's outlet keeps 554 of 1227. Either the
anchors differ in kind, or the plane's sign convention does something other than
what "cut a lumen in half" suggests.

So measure, per case and opening:

  * how many vertices the plane puts on its negative side, globally
  * the ROI box's own extent along the plane normal, and how much negative-side
    geometry sits inside it
  * the signed coordinate spread of the selection (is it a shell against the
    plane, or a bulk region?)
  * the same after moving the plane to onset+0.5, so the evaporation is visible

Everything is geometric; no threshold is applied and nothing is written.
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_candidate_preview import triangle_arrays
from auto_opening_placement import detect_onset, plane_basis
from auto_opening_pipeline import place
from connectivity_opened_surface import signed_of, flood_mask, OPENINGS

CASES = sys.argv[1:] or ['b15', 'b18', 'b05', 'b02']
SURF = Path('C:/ts_work/batch27_surfaces')
LAND = Path('work/06_auto_landmarks')


def load(case):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(SURF / case / 'source_surface.vtp'))
    r.Update()
    points, faces = triangle_arrays(r.GetOutput())
    o = json.loads((LAND / case / 'landmarks.json').read_text(encoding='utf-8'))
    planes = {n: {'point_lps_mm': o['landmarks'][n]['point_lps_mm'],
                  'normal_lps': o['landmarks'][n]['normal_lps'],
                  'roi_lps_mm': o['landmarks'][n]['roi_lps_mm'],
                  'keep_positive': True} for n in OPENINGS}
    return points, faces, planes


def stats(v):
    if not len(v):
        return 'empty'
    return (f'n={len(v):6d} min={v.min():8.2f} p10={np.percentile(v, 10):7.2f} '
            f'med={np.median(v):7.2f} p90={np.percentile(v, 90):7.2f} max={v.max():8.2f} mm')


for case in CASES:
    print('=' * 78)
    print(case)
    points, faces, planes = load(case)
    norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
    onsets = {}
    for n in OPENINGS:
        o = np.asarray(planes[n]['point_lps_mm'], float)
        onsets[n], _, _ = detect_onset(points, faces, o, norms[n])
    print('  onsets:', {k: (None if v is None else round(v, 2)) for k, v in onsets.items()})

    for n in OPENINGS:
        spec = planes[n]
        s = signed_of(points, spec)
        neg = s < 0
        lo = np.asarray(spec['roi_lps_mm']['min'], float)
        hi = np.asarray(spec['roi_lps_mm']['max'], float)
        inbox = ((points >= lo) & (points <= hi)).all(axis=1)
        print(f'  {n}')
        print(f'    reviewed plane: negative vertices {int(neg.sum()):6d} of {len(points)}'
              f'   inside ROI {int((neg & inbox).sum()):6d}')
        print(f'      s of ROI&negative : {stats(s[neg & inbox])}')
        try:
            m, _ = flood_mask(points, faces, spec, seed_mode='roi')
            print(f'      selection (roi)   : {int(m.sum()):6d} verts, s = {stats(s[m])}')
        except ValueError as exc:
            print(f'      selection (roi)   : refused ({exc})')
        if onsets[n] is None:
            continue
        placed = place(spec, norms[n], onsets[n] + 0.5)
        sp = signed_of(points, placed)
        negp = sp < 0
        print(f'    placed(+onset+0.5): negative vertices {int(negp.sum()):6d}'
              f'   ROI extent along normal = {float(hi @ norms[n] - lo @ norms[n]):.2f} mm')
        print(f'      s_placed of ROI&negative : {stats(sp[negp & inbox])}')
        try:
            mp, notep = flood_mask(points, faces, placed, seed_mode='roi')
            print(f'      selection (roi)   : {int(mp.sum()):6d} verts')
        except ValueError as exc:
            print(f'      selection (roi)   : refused ({exc})')
