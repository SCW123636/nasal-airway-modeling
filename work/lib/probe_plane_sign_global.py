"""What is the plane's negative side, globally?

Measured: b15's outlet selection is a 1.25 mm shell against the plane, and the
whole surface has only 4500 of 86216 triangles on that side (5%). A plane that
bisected a lumen would put roughly half the surface there. So the sign is not
"downstream of a cross-section"; it must be something else, and everything about
the seeding behaviour depends on which.

Prints, per opening: the normal, the plane origin, the surface bounds, the signed
coordinate distribution over ALL vertices, and the geometry of the negative and
positive parts. Read-only.
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_candidate_preview import triangle_arrays
from connectivity_opened_surface import signed_of, OPENINGS, TOL

CASES = sys.argv[1:] or ['b15']
SURF = Path('C:/ts_work/batch27_surfaces')
LAND = Path('work/06_auto_landmarks')


def load(case):
    r = vtk.vtkXMLPolyDataReader()
    r.SetFileName(str(SURF / case / 'source_surface.vtp'))
    r.Update()
    points, faces = triangle_arrays(r.GetOutput())
    o = json.loads((LAND / case / 'landmarks.json').read_text(encoding='utf-8'))
    return points, faces, o


for case in CASES:
    print('=' * 78)
    points, faces, o = load(case)
    print(case, 'vertices', len(points), 'triangles', len(faces))
    print('  surface bounds  min', np.round(points.min(axis=0), 1),
          ' max', np.round(points.max(axis=0), 1))
    print('  surface centroid', np.round(points.mean(axis=0), 1))
    for n in OPENINGS:
        lm = o['landmarks'][n]
        spec = {'point_lps_mm': lm['point_lps_mm'], 'normal_lps': lm['normal_lps'],
                'roi_lps_mm': lm['roi_lps_mm'], 'keep_positive': True}
        nrm = np.asarray(spec['normal_lps'], float)
        nrm = nrm / np.linalg.norm(nrm)
        org = np.asarray(spec['point_lps_mm'], float)
        s = signed_of(points, spec)
        neg = s < 0
        print(f'  {n}')
        print(f'    normal {np.round(nrm, 3)}  origin {np.round(org, 2)}')
        print(f'    origin vs bounds: '
              f'{"INSIDE the surface box" if (org > points.min(axis=0)).all() and (org < points.max(axis=0)).all() else "outside the surface box"}')
        print(f'    signed: min {s.min():8.2f}  p1 {np.percentile(s,1):8.2f}  '
              f'med {np.median(s):8.2f}  p99 {np.percentile(s,99):8.2f}  max {s.max():8.2f} mm')
        print(f'    negative {int(neg.sum()):6d}  positive {int((~neg).sum()):6d}  '
              f'zero {int((s == 0).sum()):5d}')
        if neg.any():
            print(f'      negative bbox  {np.round(points[neg].min(axis=0),1)} .. '
                  f'{np.round(points[neg].max(axis=0),1)}')
            print(f'      negative centroid {np.round(points[neg].mean(axis=0),1)}')
        pos = ~neg
        if pos.any():
            print(f'      positive centroid {np.round(points[pos].mean(axis=0),1)}')
