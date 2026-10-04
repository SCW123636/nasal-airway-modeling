"""Read completed non-patient circular-tube cases and measure axial pressure.

Cut actual exported fields, area-average each cut and fit the interior pressure
gradient. This supplies independent evidence for mesh/entrance hypotheses;
it never replaces the boundary pressure drop used for strict acceptance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

import extract_cfd_metrics as ecm


def section(grid, z_m, rho):
    plane = vtk.vtkPlane()
    plane.SetOrigin(0, 0, z_m)
    plane.SetNormal(0, 0, 1)
    cutter = vtk.vtkCutter()
    cutter.SetInputData(grid)
    cutter.SetCutFunction(plane)
    triangles = vtk.vtkTriangleFilter()
    triangles.SetInputConnection(cutter.GetOutputPort())
    triangles.Update()
    cut = triangles.GetOutput()
    if not cut.GetNumberOfCells():
        raise ValueError('Empty pressure section')
    p = cut.GetCellData().GetArray('p')
    u = cut.GetCellData().GetArray('U')
    if p is None or u is None:
        raise ValueError('Missing cut cell p/U')
    pressure = vtk_to_numpy(p).astype(float)
    velocity = vtk_to_numpy(u).astype(float)
    points = vtk_to_numpy(cut.GetPoints().GetData()).astype(float)
    cells = vtk_to_numpy(cut.GetPolys().GetConnectivityArray()).reshape(-1, 3)
    a, b, c = (points[cells[:, i]] for i in range(3))
    areas = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    area = float(areas.sum())
    if area <= 0 or not np.isfinite(pressure).all() or not np.isfinite(velocity).all():
        raise ValueError('Invalid pressure cut')
    return {'z_mm': z_m * 1000, 'area_mm2': area * 1e6,
            'pressure_pa': float(pressure @ areas / area) * rho,
            'axial_flow_m3_s': float(velocity[:, 2] @ areas),
            'peak_velocity_m_s': float(np.linalg.norm(velocity, axis=1).max())}


def inspect(case, diameter_mm=4., rho=1.2, mu=1.81e-5):
    case = Path(case)
    manifest = json.loads((case/'case_manifest.json').read_text(encoding='utf-8'))
    run = json.loads((case/'run_manifest.json').read_text(encoding='utf-8'))
    if run.get('execution_status') != 'completed':
        raise ValueError('Solver run has not completed')
    if manifest.get('surface', {}).get('source_file') != 'tube.stl':
        raise ValueError('This diagnostic requires the synthetic tube.stl case')
    pressure_text = (case/'0/p').read_text(encoding='ascii')
    if not re.search(r'dimensions\s*\[0\s+2\s+-2\s+0\s+0\s+0\s+0\]', pressure_text):
        raise ValueError('Pressure must have kinematic dimensions')
    z0, z1 = (manifest['bbox_mm'][key][2] for key in ('min', 'max'))
    flow = manifest['boundary']['total_flow_m3_s']
    length = z1-z0
    gradient = 128*mu*flow/(math.pi*(diameter_mm*1e-3)**4)  # Pa/m
    path = ecm.latest_vtk_dir(case)/'internal.vtu'
    reader = vtk.vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(path))
    reader.Update()
    grid = reader.GetOutput()
    sections = [section(grid, (z0+fraction*length)*1e-3, rho)
                for fraction in np.linspace(.1, .9, 9)]
    middle = sections[2:-2]
    x = np.array([s['z_mm']*1e-3 for s in middle])
    y = np.array([s['pressure_pa'] for s in middle])
    slope, intercept = np.polyfit(x, y, 1)
    fitted_gradient = -float(slope)
    profile = next((s.get('patches', {}).get('inlet') for s in run['steps']
                    if s.get('command') == ['internal:set_parabolic_inlet_profile']), None)
    return {'case': case.name, 'length_mm': length, 'diameter_mm': diameter_mm,
            'target_flow_m3_s': flow, 'analytic_pressure_gradient_pa_per_m': gradient,
            'interior_pressure_gradient_pa_per_m': fitted_gradient,
            'interior_gradient_rel_error': abs(fitted_gradient-gradient)/gradient,
            'fit_region_fraction': [.3, .7],
            'max_fit_residual_pa': float(np.max(np.abs(y-(slope*x+intercept)))),
            'profile_record': profile, 'stations': sections,
            'source_sha256': {str(p.relative_to(case)).replace('\\','/'): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (path, case/'case_manifest.json', case/'run_manifest.json', case/'0/p')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', nargs='+', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {'schema': 'tube_axial_pressure_diagnostic/v1',
              'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'method': 'Area-weighted cell fields on nine exact z cuts; least-squares fit on 30-70 percent of tube length.',
              'scope': 'Synthetic circular tubes only. Interior gradient is diagnostic; boundary delta_p remains the strict acceptance metric.',
              'cases': [inspect(case) for case in args.cases]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps([{'case': c['case'], 'length_mm': c['length_mm'],
                       'interior_gradient_rel_error': c['interior_gradient_rel_error']}
                      for c in report['cases']], indent=2))


if __name__ == '__main__':
    main()
