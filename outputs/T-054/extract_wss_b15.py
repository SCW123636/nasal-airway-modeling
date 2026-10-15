"""T-054 step 5b: WSS distribution + integrated wall-shear force for the b15
oropharynx-extended domain. Mirrors the T-042-verified chain exactly:
  patch wall type -> simpleFoam -postProcess -func wallShearStress -latestTime
  -> foamToVTK -> read wall.vtp cell data -> |tau| = kinematic * rho.
Force = sum(|tau| * dA) over wall faces (SI units from foamToVTK).
Reference (T-042 b15 short domain): force 1.102e-3 N, median 0.047, max 4.17 Pa.
"""
import json
from pathlib import Path

import numpy as np
import vtk

RHO = 1.2
WALL_VTP = Path('C:/ts_work/t054_b15_oroext/wall_600.vtp')
OUT = Path(__file__).resolve().parent / 'wss_t054_b15_oroext.json'


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
    mag = np.linalg.norm(tau, axis=1) * RHO  # Pa
    areas = np.zeros(n)
    for i in range(n):
        cell = poly.GetCell(i)
        pts = [np.array(poly.GetPoint(cell.GetPointId(k))) for k in range(3)]
        areas[i] = 0.5 * np.linalg.norm(np.cross(pts[1] - pts[0], pts[2] - pts[0]))
    force_n = float((mag * areas).sum())
    out = {
        'task': 'T-054 b15 oropharynx-extended domain WSS',
        'source_vtp': str(WALL_VTP),
        'faces': n,
        'wall_area_m2': float(areas.sum()),
        'wall_area_mm2': float(areas.sum() * 1e6),
        'units_note': 'foamToVTK exports SI: coords metres, areas m^2; '
                      '|tau| = kinematic x rho=1.2 -> Pa; force = sum(|tau|*dA) in N',
        'wss_median_pa': float(np.median(mag)),
        'wss_mean_pa': float(mag.mean()),
        'wss_p90_pa': float(np.percentile(mag, 90)),
        'wss_max_pa': float(mag.max()),
        'wall_shear_force_n': force_n,
        'b15_short_reference_T042': {
            'force_n': 0.0011019165435884187, 'median_pa': 0.047, 'max_pa': 4.17,
            'wall_area_mm2': 18023.934332},
        'b01_extended_reference_T047': {
            'force_n': 1.331e-3, 'median_pa': 0.0537, 'max_pa': 2.157},
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({k: out[k] for k in ('faces', 'wall_area_mm2', 'wss_median_pa',
                                          'wss_mean_pa', 'wss_max_pa',
                                          'wall_shear_force_n')}, indent=1))


if __name__ == '__main__':
    main()
