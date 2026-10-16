# -*- coding: utf-8 -*-
"""T-011 A.2 - mesh-labeled patch areas from the foamToVTK boundary vtp files.
Same fan-triangulation as the WSS extractor (consistent with A.1's wall 19290.1).
  python patch_areas_vtp.py <out_dir> <out_json>
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import vtk

SRC = sys.argv[1]
OUT = Path(sys.argv[2])
PATCHES = ('nostril_L', 'nostril_R', 'oropharynx_truncation_outlet', 'wall')


def area_of(poly):
    n = poly.GetNumberOfCells()
    a = 0.0
    for i in range(n):
        cell = poly.GetCell(i)
        pts = [np.array(poly.GetPoint(cell.GetPointId(k))) for k in range(cell.GetNumberOfPoints())]
        for k in range(1, len(pts) - 1):
            a += 0.5 * float(np.linalg.norm(np.cross(pts[k] - pts[0], pts[k + 1] - pts[0])))
    return a * 1e6  # m^2 -> mm^2


def main():
    res = {}
    for name in PATCHES:
        p = os.path.join(SRC, name + '.vtp')
        r = vtk.vtkXMLPolyDataReader()
        r.SetFileName(p)
        r.Update()
        res[name] = round(area_of(r.GetOutput()), 4)
        print('%-30s %10.4f mm^2' % (name, res[name]))
    OUT.write_text(json.dumps(res, indent=2), encoding='utf-8')
    print('written:', OUT)


if __name__ == '__main__':
    main()
