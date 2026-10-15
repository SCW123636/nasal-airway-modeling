"""Replay the failed job's native VTU into isolated local diagnostic output.

The original A report/error/assets are read-only. This does not complete,
reopen, or publish A and does not run meshing or a solver.
"""
import hashlib,json,shutil,sys
from pathlib import Path
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'work/lib'))
from patient_cfd_viewer import export_patient_trial_viewer,_grid
JOB=Path('C:/ts_work/project_cases/simulation_jobs/s_aa79a63027b94bfb9a273898')
source=next((JOB/'export').rglob('internal.vtu'));job=json.loads((JOB/'job.json').read_text(encoding='utf-8'))
report_path=JOB/'export'/job['id']/'patient_engineering_report.json'
report=json.loads(report_path.read_text(encoding='utf-8'))
base=source.parents[2];field_time='120'
inputs=[JOB/'job.json',report_path,source,base/'config.json',base/field_time/'p',base/field_time/'U']
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
before={str(path):sha(path) for path in inputs}
replay=OUT/'replay'
if replay.exists():raise RuntimeError('Replay evidence exists; do not overwrite')
for original in inputs[2:]:
    target=replay/original.relative_to(JOB);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
data={'id':job['id'],'case_id':job['case_id'],'action':'run_patient_engineering','artifacts':[],'asset_paths':{}}
def asset(name,path,label):
    data['asset_paths'][name]=Path(path).resolve().relative_to(replay.resolve()).as_posix()
    data['artifacts'].append({'name':name,'label':label,'url':'/simulation-assets/'+job['id']+'/'+name})
view=export_patient_trial_viewer(replay,report,asset,data)
mesh=json.loads((replay/'viewer_mesh.json').read_text(encoding='utf-8'))
grid,_=_grid(source)
# Independent sampler: direct vtkProbeFilter queries at the exported slice
# coordinates. No conversion from the display's sampled values is used.
differences=[];rho=mesh['result']['physics']['rho_kg_m3']
for item in mesh['interior_slices']:
    points=np.array(item['geometry']['vertices']).reshape(-1,3)/1000
    probe_points=vtk.vtkPoints();probe_points.SetDataTypeToDouble()
    for point in points:probe_points.InsertNextPoint(*point)
    query=vtk.vtkPolyData();query.SetPoints(probe_points)
    probe=vtk.vtkProbeFilter();probe.SetInputData(query);probe.SetSourceData(grid);probe.Update()
    sampled=probe.GetOutput().GetPointData();valid=vtk_to_numpy(sampled.GetArray('vtkValidPointMask')).astype(bool)
    u=vtk_to_numpy(sampled.GetArray('U'));p=vtk_to_numpy(sampled.GetArray('p'))*rho
    actual_u=np.array(item['fields']['velocity']['values']);actual_p=np.array(item['fields']['pressure']['values'])
    # Float32 source fields retain their original storage accuracy; querying
    # shared boundaries can select an adjacent cell, so record actual errors.
    differences.append({'axis':item['id'],'points':len(points),'triangles':len(item['geometry']['indices'])//3,
        'valid_probe_points':int(valid.sum()),'max_abs_U_diff_m_s':float(np.max(np.abs(u[valid]-actual_u[valid]))),
        'max_abs_p_diff_Pa':float(np.max(np.abs(p[valid]-actual_p[valid]))),
        'source_vtu_sha256':item['source_vtu_sha256']})
after={str(path):sha(path) for path in inputs}
assert before==after,'Original A inputs changed'
assert job['result']['viewer_export_error']=='抽取后存在退化三角面'
assert mesh['result']['numerical_validation']=='failed'
evidence={'scope':'read_only_native_A_failed_field_replay_not_republished_A_not_valid_flow',
    'source_before':before,'source_after':after,'source_unchanged':before==after,
    'original_A_status':job['status'],'original_A_viewer_export_error':job['result']['viewer_export_error'],
    'replay_export':view,'probe_comparison':differences,
    'replay_manifest_sha256':sha(replay/'viewer.json'),'replay_mesh_sha256':sha(replay/'viewer_mesh.json'),
    'exporter_sha256':sha(ROOT/'work/lib/patient_cfd_viewer.py')}
(OUT/'actual_replay.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(evidence,ensure_ascii=False))
