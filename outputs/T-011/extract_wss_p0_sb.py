"""T-011 A.4 (S-B) - WSS distribution + integrated wall-shear force on the p0
extended domain, SAME snappy mesh as A.1. Mirrors outputs/T-054/extract_wss_b15.py:
  patch wall type -> wallShearStress -> foamToVTK -> read wall.vtp cell data ->
  |tau| = kinematic * rho=1.2 -> force = sum(|tau| * dA) in N (SI from foamToVTK).

Needs VTK, which is only on the Windows python here, hence this file runs on
Windows against a copy of wall.vtp dropped at C:/ts_work/t011_p0/sb_out/.

Usage: python extract_wss_p0_sb.py
"""
import json
from pathlib import Path

import numpy as np
import vtk

RHO = 1.2
WALL_VTP = Path('C:/ts_work/t011_p0/sb_out/wall.vtp')
OUT = Path(__file__).resolve().parent / 'wss_t011_p0_sb.json'


def main():
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(WALL_VTP))
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
        'task': 'T-011 A.4 p0 extended-domain WSS, S-B (A.1 snappy mesh reused)',
        'source_vtp': str(WALL_VTP),
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
        'SA_anchor_A1_same_mesh': {'force_n': 1.008636e-3},
        'b15_extended_reference_T054': {'force_n': 1.506e-3},
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('faces', 'wall_area_mm2', 'wss_median_pa',
                                          'wss_mean_pa', 'wss_p90_pa', 'wss_max_pa',
                                          'wall_shear_force_n')}, indent=1))
    print('written:', OUT)


if __name__ == '__main__':
    main()
