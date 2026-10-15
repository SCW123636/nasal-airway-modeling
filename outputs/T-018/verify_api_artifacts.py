"""Fresh independent review. Reads a completed reference; never starts CFD."""
from pathlib import Path
import hashlib, http.client, json, re, subprocess, sys
from datetime import datetime
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

ROOT = Path(r'D:\项目\鼻腔建模')
OUT = ROOT / 'outputs/T-018'
JOB = sys.argv[1] if len(sys.argv)>1 else 's_7dc6eb58cad24de48d3da028'
DIR = Path(r'C:\ts_work\project_cases\simulation_jobs') / JOB
OUT.mkdir(parents=True, exist_ok=True)
report = {'checked_at': datetime.now().astimezone().isoformat(), 'base': 'http://127.0.0.1:8769', 'job': JOB, 'requests': [], 'checks': [], 'failures': []}

def check(name, condition, detail=None):
    item = {'name': name, 'passed': bool(condition), 'detail': detail}
    report['checks'].append(item)
    if not condition:
        report['failures'].append(item)

def request(path, payload=None, method='GET', headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', 8769, timeout=30)
    body = json.dumps(payload).encode() if payload is not None else None
    connection.request(method, path, body, {'Content-Type': 'application/json', **(headers or {})})
    response = connection.getresponse()
    content = response.read()
    try: data = json.loads(content)
    except ValueError: data = None
    report['requests'].append({'method': method, 'path': path, 'status': response.status, 'headers_sent': headers, 'payload': payload, 'error': data.get('error') if isinstance(data, dict) else None, 'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)})
    status = response.status
    connection.close()
    return status, data, content

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

try:
    status, health, _ = request('/health.json')
    check('live 8769 supports simulation jobs', status == 200 and health.get('simulation_jobs') is True, health)
    status, catalog, _ = request('/api/simulation/catalog')
    check('catalog source and separation', status == 200 and catalog['schema'] == 'nasal_simulation_catalog/v1' and all(not c['run_allowed'] for c in catalog['cases'] if c['kind'] == 'patient'), catalog)
    (OUT / 'catalog_snapshot.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
    _, before_jobs, _ = request('/api/simulation/jobs')
    status, public, _ = request('/api/simulation/jobs/' + JOB)
    raw = json.loads((DIR/'job.json').read_text(encoding='utf-8'))
    check('new job read matches persisted identity', status == 200 and public['id'] == raw['id'] == JOB and public['case_id'] == 'reference_channel' and raw['action'] == 'run_reference' and raw['status'] == 'completed' and raw['exit_code'] == 0, {'created_at': raw['created_at'], 'updated_at': raw['updated_at'], 'status': raw['status'], 'exit_code': raw['exit_code']})
    check('public data omit private process/command paths', not any(k in public for k in ('asset_paths','lock_root','review_root','worker_pid','solver_pid','command')))
    check('non-patient identity retained', public['result']['patient_data'] is False and public['result']['validation_status'] == 'awaiting_independent_review')
    manifest_path = DIR/raw['asset_paths']['run_manifest.json']
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    check('manifest belongs to current native run', manifest['patient_data'] is False and manifest['execution_status'] == 'completed' and all('/home/lenovo2/nasal_cfd_workspace_jobs/'+JOB+'/' in c['log'] and c['exit_code'] == 0 for case in manifest['cases'] for c in case['commands']))
    check('actual four stage execution commands', [c['command'][0] for c in manifest['cases'][0]['commands']] == ['blockMesh','checkMesh','simpleFoam','foamToVTK'])
    files = [DIR/'job.json', DIR/'input_fingerprint.json', DIR/'execution.log', manifest_path]
    for name, relative in raw['asset_paths'].items():
        local = DIR/relative
        code, _, content = request('/simulation-assets/'+JOB+'/'+name)
        check('asset bytes match current run: '+name, code == 200 and hashlib.sha256(content).hexdigest() == sha(local))
        files.append(local)
    for name in ('job.json','worker.log','private.txt','../job.json','%2e%2e%2fjob.json','..%5cjob.json'):
        code,_,_ = request('/simulation-assets/'+JOB+'/'+name)
        check('private/traversal refused: '+name, code == 404)
    for path in ('/api/simulation/jobs/not-a-job','/api/simulation/unknown','/simulation-assets/'+JOB+'/'):
        code,_,_ = request(path)
        check('unknown path refused: '+path, code == 404)
    rejects = [
        ('patient run', {'case_id':'p0','action':'run_reference','settings':{}}, None),
        ('unknown setting', {'case_id':'reference_channel','action':'preflight','settings':{'flow_L_min':15}},None),
        ('invalid level', {'case_id':'reference_channel','action':'preflight','settings':{'levels':['unknown']}},None),
        ('duplicate level', {'case_id':'reference_channel','action':'preflight','settings':{'levels':['coarse','coarse']}},None),
        ('unknown field', {'case_id':'reference_channel','action':'preflight','command':'anything'},None),
        ('invalid action', {'case_id':'reference_channel','action':'anything'},None),
        ('cross origin', {'case_id':'reference_channel','action':'preflight'},{'Origin':'https://foreign.example'}),
        ('wrong host', {'case_id':'reference_channel','action':'preflight'},{'Host':'foreign.example'}),
    ]
    for name, payload, headers in rejects:
        code,data,_ = request('/api/simulation/jobs',payload,'POST',headers)
        check('invalid write rejected: '+name,code == 400 and isinstance(data.get('error'),str),data)
    _, after_jobs, _ = request('/api/simulation/jobs')
    check('rejected requests created no CFD jobs', {j['id'] for j in before_jobs['jobs'] if j['action']=='run_reference'} == {j['id'] for j in after_jobs['jobs'] if j['action']=='run_reference'})
    selected = manifest['cases'][-1]
    case = DIR/'export'/JOB/selected['level']
    vtu_files = list((case/'VTK').rglob('internal.vtu'))
    check('single current source VTU', len(vtu_files)==1)
    source = vtu_files[0]; files.append(source)
    read = vtk.vtkXMLUnstructuredGridReader(); read.SetFileName(str(source)); read.Update()
    grid = read.GetOutput()
    point = vtk_to_numpy(grid.GetPoints().GetData()).astype(float)
    velocity = vtk_to_numpy(grid.GetPointData().GetArray('U')).astype(float)
    pressure = vtk_to_numpy(grid.GetPointData().GetArray('p')).astype(float)
    check('raw source cells and arrays', grid.GetNumberOfCells()==selected['cells'] and len(point)==len(velocity)==len(pressure) and np.isfinite(velocity).all() and np.isfinite(pressure).all(), {'cells':grid.GetNumberOfCells(),'points':len(point),'point_arrays':[grid.GetPointData().GetArrayName(i) for i in range(grid.GetPointData().GetNumberOfArrays())]})
    mesh=json.loads((DIR/'viewer_mesh.json').read_text(encoding='utf-8'))
    result=mesh['result']; fields=result['fields']; rho=manifest['parameters']['rho_kg_m3']
    check('viewer retains source provenance and validation limits', result['provenance']['source_vtu_sha256']==sha(source) and result['geometry']['kind']=='idealized' and result['geometry']['case_id'] is None and result['clinical_validation']=='not_validated' and result['numerical_validation']=='unchecked' and fields['turbulence_intensity'] is None)
    v = np.asarray(mesh['geometry']['vertices']).reshape(-1,3)
    source_coordinates=v[:,[2,0,1]]/1000
    # Independent check against original source planes at z=0 and z=W,
    # using keyed XY linear interpolation, without calling production exporter.
    key=lambda p: tuple(np.round(p[:2],10))
    lookup={}
    for i,p in enumerate(point): lookup.setdefault(key(p),[]).append(i)
    expected_u=[]; expected_p=[]
    for p in source_coordinates:
        ids=sorted(lookup[key(p)], key=lambda i: point[i,2])
        a,b=ids[0],ids[-1]
        w=(p[2]-point[a,2])/(point[b,2]-point[a,2])
        expected_u.append((1-w)*velocity[a]+w*velocity[b])
        expected_p.append(((1-w)*pressure[a]+w*pressure[b])*rho)
    expected_u=np.asarray(expected_u)[:,[1,2,0]]
    expected_p=np.asarray(expected_p)
    actual_u=np.asarray(fields['velocity']['values']);actual_p=np.asarray(fields['pressure']['values'])
    u_error=float(np.max(np.abs(expected_u-actual_u)));p_error=float(np.max(np.abs(expected_p-actual_p)))
    check('all viewer vectors from current VTU with rigid axis rotation', u_error<1e-7, {'max_abs_error_m_s':u_error,'points':len(v)})
    check('all viewer pressures use rho times kinematic source', p_error<1e-7 and fields['pressure']['unit']=='Pa' and fields['pressure']['source_unit']=='m2/s2' and fields['pressure']['reference']=='gauge',{'max_abs_error_Pa':p_error,'range_Pa':[float(actual_p.min()),float(actual_p.max())],'range_U_m_s':[float(np.linalg.norm(actual_u,axis=1).min()),float(np.linalg.norm(actual_u,axis=1).max())]})
    times=sorted([p for p in case.glob('*/p') if re.fullmatch(r'\d+(?:\.\d+)?',p.parent.name)],key=lambda p:float(p.parent.name))
    pressure_file=times[-1];files.append(pressure_file)
    check('OpenFOAM source pressure is kinematic', bool(re.search(r'dimensions\s*\[\s*0\s+2\s+-2\s+0\s+0\s+0\s+0\s*\]',pressure_file.read_text())),str(pressure_file))
    series={}
    for name in ('flowIn','flowOut','pressureIn','pressureOut'):
        p=next((case/'postProcessing'/name).glob('*/surfaceFieldValue.dat'));files.append(p)
        series[name]=np.loadtxt(p,comments='#',ndmin=2)
    qin,qout=(series[n][-1,1] for n in ('flowIn','flowOut'))
    dp=float((series['pressureIn'][-1,1]-series['pressureOut'][-1,1])*rho)
    imbalance=float(abs(qin+qout)/max(abs(qin),abs(qout)))
    check('raw monitors reproduce displayed pressure and mass values', abs(dp-public['result']['cases'][-1]['delta_p_boundary_Pa'])<1e-12 and imbalance==public['result']['cases'][-1]['mass_imbalance_fraction'],{'Qin_m3_s':float(qin),'Qout_m3_s':float(qout),'delta_p_Pa':dp,'mass_imbalance_fraction':imbalance,'recorded_precision_warning':'0 reflects serialized monitor precision'})
    log=(case/'log.simpleFoam').read_text()
    check('raw solver log says converged', bool(re.search(r'SIMPLE solution converged in \d+ iterations',log)) and log.strip().endswith('End'))
    check('checkMesh actual success evidence', 'Mesh OK.' in (case/'log.checkMesh').read_text())
    fingerprint=json.loads((DIR/'input_fingerprint.json').read_text(encoding='utf-8'))
    check('runner frozen hash matches current source', fingerprint['runner_sha256']==sha(ROOT/'work/07_cfd_pipeline/solver_reference/run_reference.py'))
    report['files']=[{'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)} for p in dict.fromkeys(files)]
    report['source_code']=[{'path':str(ROOT/p),'sha256':sha(ROOT/p)} for p in ('work/lib/cfd_workspace_jobs.py','work/lib/serve_cfd_workspace.py','work/07_cfd_pipeline/workspace/index.html','work/07_cfd_pipeline/workspace/simulation.js','work/07_cfd_pipeline/viewer/viewer.js')]
except Exception as exc:
    import traceback
    report['exception']=traceback.format_exc()
    report['failures'].append({'name':'script exception','detail':str(exc)})
finally:
    target=OUT/('api_artifact_review_'+JOB+'.json')
    report['verification_script_sha256']=sha(Path(__file__))
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(report['checks']),'failures':report['failures'],'report':str(target)},ensure_ascii=False))
sys.exit(bool(report['failures']))
