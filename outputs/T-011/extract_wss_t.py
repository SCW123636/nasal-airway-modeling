# -*- coding: utf-8 -*-
"""T-011 A.2 - parameterized WSS extraction for a threshold-axis solve.
Same definitions as extract_wss_p0_snappy.py (A.1); argv-driven (runs on Windows
python, which is where VTK lives):
  python extract_wss_t.py <wall_vtp> <out_json> <label>
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

RHO = 1.2
WALL_VTP = sys.argv[1]
OUT = Path(sys.argv[2])
LABEL = sys.argv[3]


def main():
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(WALL_VTP)
    reader.Update()
    poly = reader.GetOutput()
    wss = poly.GetCellData().GetArray('wallShearStress')
    if wss is None:
        raise SystemExit('wallShearStress array missing (patch type not wall?)')
    n = poly.GetNumberOfCells()
    if n == 0:
        raise SystemExit('empty wall patch')
    tau = np.array([wss.GetTuple(i) for i in range(n)], dtype=float)
    mag = np.linalg.norm(tau, axis=1) * RHO
    areas = np.zeros(n)
    for i in range(n):
        cell = poly.GetCell(i)
        pts = [np.array(poly.GetPoint(cell.GetPointId(k))) for k in range(cell.GetNumberOfPoints())]
        a = 0.0
        for k in range(1, len(pts) - 1):
            a += 0.5 * float(np.linalg.norm(np.cross(pts[k] - pts[0], pts[k + 1] - pts[0])))
        areas[i] = a

    out = {
        'task': 'T-011 A.2 threshold-axis WSS %s' % LABEL,
        'source_vtp': WALL_VTP,
        'faces': int(n),
        'wall_area_m2': float(areas.sum()),
        'wall_area_mm2': float(areas.sum() * 1e6),
        'units_note': 'foamToVTK exports SI: coords m, areas m^2; |tau| = kinematic x '
                      'rho=1.2 -> Pa; force = sum(|tau|*dA) in N',
        'wss_median_pa': float(np.median(mag)),
        'wss_mean_pa': float(mag.mean()),
        'wss_p90_pa': float(np.percentile(mag, 90)),
        'wss_max_pa': float(mag.max()),
        'wall_shear_force_n': float((mag * areas).sum()),
        'A1_anchor_t300_same_route': {'force_n': 1.008636e-3},
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('faces', 'wall_area_mm2', 'wss_median_pa',
                                          'wss_mean_pa', 'wss_p90_pa', 'wss_max_pa',
                                          'wall_shear_force_n')}, indent=1))
    print('written:', OUT)


if __name__ == '__main__':
    main()
