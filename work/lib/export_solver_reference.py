"""Export a real OpenFOAM reference field to the local viewer; no patient data."""
import hashlib
import json
from pathlib import Path
import re

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from cfd_contract import pressure_to_pa, validate_result

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'work'/'07_cfd_pipeline'


def main():
    run=BASE/'solver_reference'/'results'/'poiseuille_v1912_verified'
    manifest=json.loads((run/'run_manifest.json').read_text(encoding='utf-8'))
    validation=json.loads((run/'validation.json').read_text(encoding='utf-8'))
    if manifest.get('patient_data') is not False or validation.get('reference_pass') is not True:
        raise ValueError('Require a successfully validated non-patient reference run')
    recorded=next(c for c in manifest['cases'] if c['level']=='fine')
    metrics=next(c for c in validation['cases'] if c['level']=='fine')
    if any(c['exit_code']!=0 for c in recorded['commands']):
        raise ValueError('Reference solver command failed')
    sources=list((run/'fine'/'VTK').glob('*/internal.vtu'))
    if len(sources)!=1:raise ValueError('Expected one exported final fine-grid field')
    source=sources[0]
    pressure_files=[p for p in (run/'fine').glob('*/p') if p.parent.name.replace('.','',1).isdigit()]
    pressure_file=max(pressure_files,key=lambda p:float(p.parent.name))
    header=pressure_file.read_text(encoding='ascii',errors='replace')
    if not re.search(r'dimensions\s*\[\s*0\s+2\s+-2\s+0\s+0\s+0\s+0\s*\]',header):
        raise ValueError('OpenFOAM pressure dimensions are not the expected kinematic pressure')
    reader=vtk.vtkXMLUnstructuredGridReader();reader.SetFileName(str(source));reader.Update()
    data=reader.GetOutput()
    if data.GetNumberOfCells()!=recorded['cells']:raise ValueError('Cell count differs from run record')
    plane=vtk.vtkPlane();plane.SetOrigin(0,0,manifest['parameters']['empty_width_W_m']/2);plane.SetNormal(0,0,1)
    cutter=vtk.vtkCutter();cutter.SetInputData(data);cutter.SetCutFunction(plane);cutter.Update()
    triangle=vtk.vtkTriangleFilter();triangle.SetInputConnection(cutter.GetOutputPort());triangle.Update()
    poly=triangle.GetOutput()
    points=vtk_to_numpy(poly.GetPoints().GetData()).astype(float)
    cells=poly.GetPolys()
    if np.any(np.diff(vtk_to_numpy(cells.GetOffsetsArray()))!=3):raise ValueError('Reference cut must be triangular')
    faces=vtk_to_numpy(cells.GetConnectivityArray()).reshape(-1,3)
    vectors=vtk_to_numpy(poly.GetPointData().GetArray('U')).astype(float)
    pressure=vtk_to_numpy(poly.GetPointData().GetArray('p')).astype(float)
    params=manifest['parameters'];rho=params['rho_kg_m3']
    pressure_pa=pressure_to_pa(pressure,'m2/s2',rho)
    # Cyclic axis permutation is a rigid rotation for readable long-axis display.
    shown_points=points[:,[1,2,0]]*1000
    shown_vectors=vectors[:,[1,2,0]]
    result={'schema':'nasal_cfd_result/v1','type':'cfd_result',
        'geometry':{'kind':'idealized','case_id':None}, 'clinical_validation':'not_validated',
        'numerical_validation':'passed_engineering_screen',
        'physics':{'turbulence_model':'laminar','rho_kg_m3':rho,'mu_Pa_s':params['mu_Pa_s']},
        'provenance':{'method':'cfd_solver','solver_name':'simpleFoam',
            'solver_version':manifest['package_version'],'run_id':'poiseuille_v1912_verified/fine',
            'run_log':str(run/'fine'/'log.simpleFoam'),'config_id':'plane_poiseuille_v1912_reference',
            'source_vtu':str(source),'source_vtu_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'pressure_dimensions_file':str(pressure_file),
            'display_mapping':'Shown xyz = solver yzx, rigid axis permutation; positions m to mm; no geometric stretching',
            'sampling':'Middle empty-direction plane cut through exported point-interpolated fields'},
        'diagnostics':{'mass_imbalance_fraction':metrics['mass_imbalance_fraction_at_stored_precision'],
            'monitor_relative_change':metrics['pressure_relative_range_last20_iterations'],
            'residual_max':max(r['initial'] for r in metrics['last_residuals'].values()),
            'precision_note':'Zero imbalance/stability may mean below recorded precision, not exact arithmetic'},
        'parameters':params,'reference_comparison':metrics,
        'fields':{'velocity':{'unit':'m/s','association':'point','values':shown_vectors.tolist()},
            'pressure':{'unit':'Pa','association':'point','values':pressure_pa,'quantity':'static','reference':'gauge',
                'source_unit':'m2/s2','source_field':'p','rho_kg_m3':rho,'conversion':'p_Pa = rho_kg_m3 * p_kinematic'},
            'turbulence_intensity':None},'turbulence_intensity_status':'not_applicable'}
    check=validate_result(result)
    if not check['valid']:raise ValueError(check['errors'])
    obj={'schema':'candidate_surface_preview/v1','case':None,'status':'numerical_reference',
         'coordinate_system':'synthetic_Cartesian','unit':'mm','display_geometry_only':True,'cfd_ready':False,
         'geometry':{'vertices':shown_points.ravel().tolist(),'indices':faces.ravel().tolist()},
         'result':result,'qc':{'result_contract':check,'reference_validation':validation['grid_checks']}}
    out=BASE/'reference'/'channel_numerical';out.mkdir(parents=True,exist_ok=True)
    for name,value in [('viewer_mesh.json',obj),('result.json',result)]:
        (out/name).write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
    print(json.dumps({'points':len(points),'triangles':len(faces),'result_valid':check['valid'],
                      'patient_data':False,'output':str(out)},ensure_ascii=False))


if __name__=='__main__':main()
