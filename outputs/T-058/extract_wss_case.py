"""T-058 parameterized WSS extraction: wall_600.vtp -> distribution + force.

Mirrors outputs/T-054/extract_wss_b15.py exactly:
  |tau| = kinematic wallShearStress x rho=1.2 -> Pa
  force = sum(|tau| * dA) over wall faces (SI units from foamToVTK)

Known answers:
  b15 (T-054): force 1.506e-3 N, median 0.0682 Pa, max 3.292 Pa
  b01 (T-047): force 1.331e-3 N, median 0.0537 Pa, max 2.157 Pa

Usage: python extract_wss_case.py <case> [chain_root] [cut_convention]
Reads  <chain_root>/<case>/wall_600.vtp  (chain_root default C:/ts_work/t058_chain)
Writes <chain_root>/<case>/wss_t058_<case>.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import vtk

CASE = sys.argv[1] if len(sys.argv) > 1 else 'b15'
ROOT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('C:/ts_work/t058_chain')
CUT_CONVENTION = sys.argv[3] if len(sys.argv) > 3 else 'axial_perpendicular_to_scan_z'
RHO = 1.2
WALL_VTP = ROOT / CASE / 'wall_600.vtp'
OUT = WALL_VTP.parent / f'wss_t058_{CASE}.json'

KNOWN = {
    'b15': {'force_n': 1.506e-3, 'median_pa': 0.0682, 'max_pa': 3.292,
            'src': 'T-054 b15 oropharynx-extended'},
    'b01': {'force_n': 1.331e-3, 'median_pa': 0.0537, 'max_pa': 2.157,
            'src': 'T-047 b01 oropharynx-extended'},
}


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
        'task': f'T-058 {CASE} oropharynx-extended domain WSS (production chain)',
        'outlet_cut_convention': CUT_CONVENTION,
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
        'clinical_status': 'generalisation_test_only_no_human_review',
    }
    if CASE in KNOWN:
        k = KNOWN[CASE]
        out['reconciliation'] = {
            'reference': k['src'],
            'note': 'reference = AXIAL-cut baseline; with the anatomical oblique outlet '
                    'the outlet geometry changes -> differences EXPECTED, not a regression',
            'force_n': {'known': k['force_n'], 'now': force_n,
                        'rel_diff': (force_n - k['force_n']) / k['force_n']},
            'median_pa': {'known': k['median_pa'], 'now': float(np.median(mag)),
                          'rel_diff': (float(np.median(mag)) - k['median_pa']) / k['median_pa']},
            'max_pa': {'known': k['max_pa'], 'now': float(mag.max()),
                       'rel_diff': (float(mag.max()) - k['max_pa']) / k['max_pa']},
        }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"== {CASE} WSS ==")
    print(f"faces={n} wall_area={out['wall_area_mm2']:.1f} mm2")
    print(f"median={out['wss_median_pa']:.4f} Pa  mean={out['wss_mean_pa']:.4f}  "
          f"max={out['wss_max_pa']:.4f}  force={force_n:.4e} N")
    if 'reconciliation' in out:
        print('reconciliation:', json.dumps(out['reconciliation'], ensure_ascii=False))
    print('written:', OUT)


if __name__ == '__main__':
    main()
