"""Map the ROI seeding mechanism's stable range as the plane is pushed.

b16/b21 pass with outlet onset -1.25 (plane pushed 0.75 mm), b15 fails at -1.75
(pushed 1.25 mm). That gap is too narrow to state a rule from, and the rule
matters: ONSET_BAND_MM is (-4, 1) but the mechanism looks like it survives about
1 mm. Either the band is far wider than the machinery, or the machinery is
fragile and the band is honest - the two readings have opposite consequences.

So sweep the plane offset directly, in units of the push away from the reviewed
position (d = 0 is the reviewed plane itself, negative pushes downstream), and
report for each opening:

  * ROI seed count (does the box still hold a negative-side vertex)
  * whether the full three-plane clip succeeds, and the cap areas

Read-only.
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
from connectivity_opened_surface import flood_mask, OPENINGS
from partitioned_surface import clip_and_cap

TARGETS = sys.argv[1:] or ['b15:nasopharynx_outlet', 'b18:nasopharynx_outlet',
                           'b16:nasopharynx_outlet', 'b05:nostril_L']
SURF = Path('C:/ts_work/batch27_surfaces')
LAND = Path('work/06_auto_landmarks')
PUSHES = [0.0, -0.25, -0.5, -0.75, -1.0, -1.25, -1.5, -2.0, -2.75, -3.5]


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


cache = {}
for target in TARGETS:
    case, opening = target.split(':')
    if case not in cache:
        cache[case] = load(case)
    points, faces, planes = cache[case]
    nrm = plane_basis(planes[opening]['normal_lps'])[0]
    o = np.asarray(planes[opening]['point_lps_mm'], float)
    onset, _, _ = detect_onset(points, faces, o, nrm)
    print('=' * 74)
    print(f'{case} {opening}   onset={onset:+.2f}  '
          f'(the pipeline starts at push {onset + 0.5:+.2f})')
    print(f'  {"push":>7s} {"roi seeds":>10s}   clip (three planes, roi seeding)')
    for d in PUSHES:
        placed = {k: place(planes[k], plane_basis(planes[k]['normal_lps'])[0],
                           d if k == opening else 0.0) for k in OPENINGS}
        try:
            _, note = flood_mask(points, faces, placed[opening], seed_mode='roi')
            ns = note['seed_vertices']
        except ValueError:
            ns = 0
        try:
            sels = {k: flood_mask(points, faces, placed[k], seed_mode='roi')[0]
                    for k in OPENINGS}
            p, f, patches, qc = clip_and_cap(points, faces, placed, selectors=sels)
            xyz = p[f]
            areas = {k: round(float(np.linalg.norm(
                np.cross(xyz[patches == k][:, 1] - xyz[patches == k][:, 0],
                         xyz[patches == k][:, 2] - xyz[patches == k][:, 0]),
                axis=1).sum() * .5), 1) for k in OPENINGS if (patches == k).any()}
            print(f'  {d:+7.2f} {ns:10d}   OK {areas}')
        except ValueError as exc:
            print(f'  {d:+7.2f} {ns:10d}   FAIL {exc}')
