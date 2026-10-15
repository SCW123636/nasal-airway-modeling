"""Independent raw-VTU and quality rejection audit; no field export or repair."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import os
import re
import urllib.request

os.environ['OMP_NUM_THREADS'] = os.environ['OPENBLAS_NUM_THREADS'] = os.environ['MKL_NUM_THREADS'] = '1'
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy
from audit_actual_candidate_fields import raw_internal

vtk.vtkMultiThreader.SetGlobalMaximumNumberOfThreads(1)
HERE = Path(__file__).resolve().parent
JOB = 's_aa79a63027b94bfb9a273898'
ROOT = Path('C:/ts_work/project_cases/simulation_jobs') / JOB
EVAL = ROOT / 'export' / JOB / 'evaluations/eval_001'


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))


def triangle_statistics(poly):
    p = vtk_to_numpy(poly.GetPoints().GetData()).astype(float)
    f = vtk_to_numpy(poly.GetPolys().GetConnectivityArray()).reshape(-1, 3)
    area2 = np.linalg.norm(np.cross(p[f[:,1]]-p[f[:,0]], p[f[:,2]]-p[f[:,0]]), axis=1)
    bad = np.flatnonzero(area2 <= 1e-20)
    return {'points': len(p), 'triangles': len(f), 'nonfinite_coordinates': int((~np.isfinite(p)).sum()), 'zero_area_triangles': int((area2 == 0).sum()), 'at_or_below_existing_1e_minus20_threshold': len(bad), 'minimum_double_area_m2': float(area2.min()), 'bad_examples': [{'triangle_index': int(i), 'point_ids': f[i].tolist(), 'xyz_m': p[f[i]].tolist(), 'double_area_m2': float(area2[i])} for i in bad[:6]]}


def main():
    identity = read(HERE / 'terminal-native-identity.json'); native = identity['actual_native']
    local = read(ROOT / 'job.json'); report = read(ROOT / 'export' / JOB / 'patient_engineering_report.json')
    evaluation = read(ROOT / 'export' / JOB / 'evaluations/evaluation_001.json')
    config = read(EVAL / 'config.json'); rho = config['physics']['rho_kg_m3']
    assert identity['native_export_all_equal'] and native['latest_field_time'] == '120'
    assert local['status'] == report['execution_status'] == evaluation['status'] == 'failed'
    assert report['scenario']['result']['status'] == 'quality_rejected_not_converged'
    assert evaluation['exit_code'] == 0 and native['End'] and not native['SIMPLE_convergence']
    assert not native['actual_signal_stack'] and native['startup_trap_banner_present']
    assert all(not evaluation['evaluation'][k] for k in ['converged', 'mesh_quality_passed', 'residuals_passed'])
    assert not (ROOT / 'viewer.json').exists() and not (ROOT / 'viewer_mesh.json').exists()
    assert local['result']['viewer_export_error'] == '抽取后存在退化三角面'
    sources = list((EVAL / 'VTK').rglob('internal.vtu')); assert len(sources) == 1
    source = sources[0]; reader = vtk.vtkXMLUnstructuredGridReader(); reader.SetFileName(str(source)); reader.Update(); grid = reader.GetOutput()
    assert grid.GetNumberOfCells() == 1161194 and grid.GetNumberOfPoints() == 229033
    raw_checks = {}
    for name,kind,dimensions in [('p','scalar',[0,2,-2,0,0,0,0]),('U','vector',[0,1,-1,0,0,0,0])]:
        expected = raw_internal(EVAL / ('120/' + name),kind,dimensions)
        array = grid.GetCellData().GetArray(name); assert array is not None
        actual = vtk_to_numpy(array).astype(float)
        assert len(expected) == len(actual) == grid.GetNumberOfCells()
        np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-6)
        pa = grid.GetPointData().GetArray(name); assert pa is not None
        assert np.isfinite(vtk_to_numpy(pa)).all()
        raw_checks[name] = {'raw_sha256':sha(EVAL / ('120/' + name)), 'native_export_equal':True, 'dimensions':dimensions, 'source_cell_count':len(expected), 'max_cell_abs_difference':float(np.max(np.abs(actual-expected))), 'cell_min':float(expected.min()), 'cell_max':float(expected.max()), 'point_array_finite':True, 'ascii_serialization_tolerance':'rtol=1e-5, atol=1e-6'}
    raw_text = (EVAL / 'constant/polyMesh/points').read_text(encoding='ascii')
    match = re.search(r'\n\s*(\d+)\s*\(',raw_text); assert match
    raw_points = np.fromstring(raw_text[match.end():].rsplit(')',1)[0].replace('(', ' ').replace(')', ' '), sep=' ').reshape(-1,3)
    assert len(raw_points) == int(match[1]) == grid.GetNumberOfPoints()
    points = vtk_to_numpy(grid.GetPoints().GetData()).astype(float)
    np.testing.assert_allclose(points,raw_points,rtol=1e-5,atol=1e-8)
    surface=vtk.vtkDataSetSurfaceFilter();surface.SetInputData(grid);surface.Update()
    triangle=vtk.vtkTriangleFilter();triangle.SetInputConnection(surface.GetOutputPort());triangle.PassVertsOff();triangle.PassLinesOff();triangle.Update()
    surface_stats=triangle_statistics(triangle.GetOutput())
    bounds=grid.GetBounds();center=[(bounds[2*a]+bounds[2*a+1])/2 for a in range(3)];cuts=[]
    for a,axis in enumerate('xyz'):
        plane=vtk.vtkPlane();plane.SetOrigin(*center);normal=[0,0,0];normal[a]=1;plane.SetNormal(*normal)
        cutter=vtk.vtkCutter();cutter.SetInputData(grid);cutter.SetCutFunction(plane);cutter.Update()
        triangles=vtk.vtkTriangleFilter();triangles.SetInputConnection(cutter.GetOutputPort());triangles.Update()
        cuts.append({'axis':axis,'position_lps_m':center[a],**triangle_statistics(triangles.GetOutput())})
    assert surface_stats['at_or_below_existing_1e_minus20_threshold'] + sum(c['at_or_below_existing_1e_minus20_threshold'] for c in cuts) > 0
    # Recompute the rejected point only from raw native patch monitor rows.
    signed={};pressures={}
    for name,rows in native['monitors'].items():
        assert len(rows)==120 and [r[0] for r in rows]==list(range(1,121))
        tag=Path(name).parts[1]
        if tag.startswith('flow_'):signed[tag[5:]]=rows[-1][1]
        elif tag.startswith('pressure_'):pressures[tag[9:]]=rows[-1][1]*rho
    assert signed==evaluation['diagnostics']['signed_phi_m3_s']
    total=-signed['nostril_L']-signed['nostril_R'];qout=signed['nasopharynx_outlet']
    result=report['scenario']['result'];assert result['q_total_m3_s']==total and result['q_out_m3_s']==qout
    np.testing.assert_allclose(result['mass_imbalance_frac'],abs(total-qout)/total,rtol=1e-12)
    np.testing.assert_allclose(result['left_fraction'],-signed['nostril_L']/total,rtol=1e-12)
    target=report['target_m3_s'];np.testing.assert_allclose(result['relative_flow_error'],abs(total-target)/target,rtol=1e-12)
    asset=next(a for a in local['artifacts'] if a['url'].endswith('-internal.vtu'))
    with urllib.request.urlopen('http://127.0.0.1:8769'+asset['url'],timeout=90) as response:
        h=hashlib.sha256()
        while block:=response.read(1024*1024):h.update(block)
    assert h.hexdigest()==sha(source)==native['files'][str(source.relative_to(EVAL)).replace('\\','/')]
    data={'schema':'t023_t029_raw_vtu_quality/v1','at':dt.datetime.now(dt.timezone.utc).isoformat(),'job_id':JOB,'case_id':local['case_id'],'field_time':'120','source_vtu_sha256':sha(source),'actual_served_vtu_sha256':h.hexdigest(),'native_export_served_equal':True,'raw_cell_field_checks':raw_checks,'coordinate_check':{'source_points':len(points),'LPS_axes_unchanged':True,'source_unit':'m','max_absolute_difference_m':float(np.max(np.abs(points-raw_points))),'ascii_serialization_tolerance':'rtol=1e-5, atol=1e-8'},'outer_surface':surface_stats,'three_readonly_raw_cut_statistics':cuts,'recomputed_rejected_point':{'signed_phi_m3_s':signed,'pressure_pa':pressures,'q_total_m3_s':total,'q_out_m3_s':qout,'left_fraction':-signed['nostril_L']/total,'target_m3_s':target,'relative_flow_error':abs(total-target)/target,'diagnostic_only':True},'strict_quality':{'actual_status':result['status'],'converged':False,'mesh_quality_passed':False,'residuals_passed':False,'not_feedback_accepted':True},'display':{'viewer_export_error':local['result']['viewer_export_error'],'viewer_files_absent':True,'formal_field_display_passed':False},'scope':'Read-only raw identity/coordinates/units/finite fields and actual rejection; cuts are diagnostic statistics, not exported or accepted display. No numerical/clinical approval.','script_sha256':sha(__file__)}
    with (HERE/'raw-vtu-and-quality-audit.json').open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'raw_identity_passed':True,'native_export_served_equal':True,'surface_degenerate_triangles':surface_stats['at_or_below_existing_1e_minus20_threshold'],'cuts':cuts,'strict_quality_status':result['status'],'formal_field_display_passed':False},ensure_ascii=False))


if __name__=='__main__':main()
