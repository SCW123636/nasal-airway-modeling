"""Persistent read-only acceptance for one existing job; never runs CFD.

--prepare freezes source/input content after T024 freeze. --watch consumes it.
Every evidence write is inside this T023 directory and refuses replacement.
No task-state changes, messages, solver commands, or production imports.
"""
from __future__ import annotations
import argparse,datetime,hashlib,json,math,os,pathlib,re,subprocess,sys,time,traceback,urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent
JOB='s_942fdbebfffd433c8fcec956';CASE='b15_engineering';BASE='http://127.0.0.1:8769'
RUN=pathlib.Path('C:/ts_work/project_cases/simulation_jobs')/JOB
INPUT=pathlib.Path('C:/ts_work/project_cases/patient_cfd_inputs')/CASE
NATIVE='/home/lenovo2/nasal_cfd_workspace_jobs/'+JOB
EVIDENCE=OUT/'patient-terminal-watch';CONTRACT=OUT/'patient_terminal_watch_contract.json'
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def read(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def write_once(p,d):
    with pathlib.Path(p).open('x',encoding='utf-8') as f:json.dump(d,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def event(d):
    with (EVIDENCE/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'at':now(),**d},ensure_ascii=False,allow_nan=False)+'\n')
def get(url):
    with urllib.request.urlopen(BASE+url,timeout=20) as response:return response.read()
def wsl(code,*args):
    return subprocess.check_output(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',code,*args],text=True,encoding='utf-8',timeout=60)
def verify_hashes(items):
    mismatch=[{'path':p,'expected':h,'actual':sha(p) if pathlib.Path(p).is_file() else None} for p,h in items.items() if not pathlib.Path(p).is_file() or sha(p)!=h]
    assert not mismatch,{'frozen_content_changed':mismatch}
def package_hashes():return {str(p.resolve()):sha(p) for p in sorted(INPUT.rglob('*')) if p.is_file()}
def prepare():
    assert not CONTRACT.exists() and not EVIDENCE.exists()
    production={}
    for file,key in [(ROOT/'outputs/T-021/backend_freeze.json','source_sha256'),(ROOT/'outputs/T-024/component_validation/validation_binding.json','sha256')]:
        binding=read(file)[key]
        for rel,h in binding.items():
            assert sha(ROOT/rel)==h,(rel,'freeze mismatch')
            if rel.startswith('work/'):production[str((ROOT/rel).resolve())]=h
    for rel in ['work/lib/pressure_feedback.py','outputs/T-023/watch_b15_readonly_acceptance.py','outputs/T-023/audit_patient_field_arrays.py','outputs/T-023/audit_patient_readonly_ui.cjs']:
        production[str((ROOT/rel).resolve())]=sha(ROOT/rel)
    package=package_hashes();assert sha(INPUT/'admission.json')=='f8e525cf579fe6d32fd55cdc9b6a0a21a74a9b0df08e158b6cfc0cbc63ea9bcc'
    j=read(RUN/'job.json');assert j['id']==JOB and j['case_id']==CASE and j['action']=='run_patient_engineering'
    native_fp=json.loads(wsl("import pathlib,json,sys;print((pathlib.Path(sys.argv[1])/'patient_input_fingerprint.json').read_text())",NATIVE))
    assert native_fp['admission_sha256']==sha(INPUT/'admission.json') and native_fp['config_sha256']==sha(INPUT/'template/config.json')
    for filename,h in native_fp['code_sha256'].items():assert sha(ROOT/'work/lib'/filename)==h
    contract={'schema':'t023_readonly_terminal_contract/v1','prepared_at':now(),'job_id':JOB,'case_id':CASE,'native_root':NATIVE,
              'job_root':str(RUN),'input_root':str(INPUT),'production_and_verifier_sha256':production,'input_file_sha256':package,
              'native_patient_input_fingerprint':native_fp,'backend_commit':'834ff852dba19894f7f4be3dd757f409542f7d64',
              'viewer_commit':'8372033','starting_job_status':j['status'],'deadline_seconds':36*3600,
              'authorization':'Lead explicit T023 persistent read-only watcher; single pre-existing job; no solver restart or state grants'}
    write_once(CONTRACT,contract);print(json.dumps({'prepared':True,'job_id':JOB,'source_count':len(production),'input_file_count':len(package)}))
def block(text,name):
    m=re.search(r'\b'+re.escape(name)+r'\s*\{([^{}]*)\}',text,re.S);assert m,name;return m.group(1)
def numeric_rows(path):
    return [[float(x) for x in l.split()] for l in path.read_text().splitlines() if l.strip() and not l.lstrip().startswith('#')]
def close(a,b):assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-14),(a,b)
def dimensions(path,expected):
    m=re.search(r'\bdimensions\s*\[([^\]]+)\]',path.read_text());assert m and list(map(int,m.group(1).split()))==expected,str(path)
def evaluation_audit(d,ev):
    assert d.name==pathlib.PurePosixPath(ev['case']).name and ev['case']==NATIVE+'/evaluations/'+d.name
    m=read(d/'run_manifest.json');s=read(d/'run_status.json');config=read(d/'config.json');rho=config['physics']['rho_kg_m3']
    assert m['case']==s['case']==ev['case'];assert m['started_at'][:10]=='2026-10-15'
    assert [x['command'][0] for x in m['steps']]==['checkMesh','simpleFoam','foamToVTK']
    assert m['execution_status']==s['status']=='completed' and all(x['exit_code']==0 for x in m['steps'])
    log=(d/'log.simpleFoam').read_text();ml=(d/'log.checkMesh').read_text();assert ev['case'] in log and 'nProcs : 1' in log
    markers=list(re.finditer(r'(?m)^Time = (\S+)',log));assert markers
    final_time=markers[-1].group(1);last=log[markers[-1].start():]
    residuals={name:float(value) for name,value in re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+)',last)}
    continuity=float(re.findall(r'global = ([\deE+.-]+)',last)[-1])
    assert {'p','Ux','Uy','Uz'}<=residuals.keys() and all(math.isfinite(x) for x in residuals.values()) and math.isfinite(continuity)
    ended=bool(re.search(r'(?m)^End\s*$',log)) and 'FOAM FATAL' not in log
    mesh_failures=[int(n) for n in re.findall(r'Failed\s+(\d+)\s+mesh checks',ml)];mesh_ok='Mesh OK.' in ml and not mesh_failures
    p=(d/'0/p').read_text();u=(d/'0/U').read_text();pressure=ev['pressure_pa']
    dimensions(d/'0/p',[0,2,-2,0,0,0,0]);dimensions(d/'0/U',[0,1,-1,0,0,0,0])
    for inlet in ['nostril_L','nostril_R']:
        pb=block(p,inlet);assert 'fixedValue' in pb
        close(float(re.search(r'value\s+uniform\s+([^;]+)',pb).group(1))*rho,pressure)
        assert 'pressureInletOutletVelocity' in block(u,inlet)
    assert float(re.search(r'value\s+uniform\s+([^;]+)',block(p,'nasopharynx_outlet')).group(1))==0
    assert not any(token in p+u for token in ['flowRateInletVelocity','massFlowRate','volumetricFlowRate'])
    td=d/final_time;dimensions(td/'p',[0,2,-2,0,0,0,0]);dimensions(td/'U',[0,1,-1,0,0,0,0]);dimensions(td/'phi',[0,3,-1,0,0,0,0])
    phi=(td/'phi').read_text();boundary=(d/'constant/polyMesh/boundary').read_text();sums={};flow_rows={};pressure_rows={}
    for name in ['nostril_L','nostril_R','nasopharynx_outlet']:
        patch=block(phi,name);mphi=re.search(r'value\s+nonuniform\s+List<scalar>\s+(\d+)\s*\((.*?)\)\s*;',patch,re.S)
        assert mphi,(name,'missing per-face phi');values=[float(x) for x in mphi.group(2).split()]
        assert len(values)==int(mphi.group(1))==int(re.search(r'nFaces\s+(\d+)',block(boundary,name)).group(1))
        sums[name]=math.fsum(values);flow_rows[name]=numeric_rows(d/('postProcessing/flow_'+name+'/0/surfaceFieldValue.dat'))
        pressure_rows[name]=numeric_rows(d/('postProcessing/pressure_'+name+'/0/surfaceFieldValue.dat'))
        assert flow_rows[name][-1][0]==pressure_rows[name][-1][0]==float(final_time)
        close(sums[name],flow_rows[name][-1][1]);close(pressure_rows[name][-1][1]*rho,pressure if name!='nasopharynx_outlet' else 0)
    ql,qr,qo=-sums['nostril_L'],-sums['nostril_R'],sums['nasopharynx_outlet'];total=ql+qr
    measured=ev.get('evaluation');diag=ev.get('diagnostics',{})
    if measured:
        for key,value in [('q_left_m3_s',ql),('q_right_m3_s',qr),('q_out_m3_s',qo)]:close(measured[key],value)
        close(measured['mass_imbalance_frac'],abs(total-qo)/max(abs(total),1e-30))
    close(diag['residual_max'],max(residuals.values()));close(diag['continuity_global'],continuity)
    assert diag['mesh_quality_passed']==mesh_ok and diag['solver_ended']==ended and diag['final_time']==final_time
    # Match the documented dP final-40% twenty-sample statistic independently.
    times=[[row[0] for row in rows] for rows in pressure_rows.values()];assert times[0]==times[1]==times[2]
    dp=[(a[1]-b[1])*rho for a,b in zip(pressure_rows['nostril_L'],pressure_rows['nasopharynx_outlet'])]
    tail=dp[int(len(dp)*.6):];means=[math.fsum(tail[i:i+20])/20 for i in range(0,len(tail)-19,20)]
    assert len(means)>=2;change=max(abs(b-a)/max(abs(b),1e-30) for a,b in zip(means,means[1:]));close(diag['monitor_relative_change'],change)
    quality=ended and max(residuals.values())<=1e-5 and abs(continuity)<=1e-6 and change<=.005 and mesh_ok and abs(total-qo)/max(abs(total),1e-30)<=.005
    if not quality:assert ev['status']!='accepted','Rejected quality point was presented as accepted'
    files=['0/p','0/U','config.json','case_manifest.json','run_manifest.json','run_status.json','execution.log','log.simpleFoam','log.checkMesh','log.foamToVTK',final_time+'/p',final_time+'/U',final_time+'/phi']
    files+=['postProcessing/'+kind+'_'+name+'/0/surfaceFieldValue.dat' for kind in ['flow','pressure'] for name in sums]
    result={'native_case':ev['case'],'field_time':final_time,'step_exit_codes':[x['exit_code'] for x in m['steps']],
            'evaluation_status':ev['status'],'solver_ended':ended,'mesh_failed_checks':mesh_failures,'mesh_quality_passed':mesh_ok,
            'raw_initial_residuals':residuals,'continuity_global':continuity,'dp_monitor_relative_change':change,
            'signed_patch_phi_sums_m3_s':sums,'q_total_m3_s':total,'left_fraction':ql/total,
            'independent_quality_all_gates':quality,'artifact_sha256':{f:sha(d/f) for f in files}}
    return result
def terminal_audit(j,c):
    write_once(EVIDENCE/'terminal_job.json',j)
    verify_hashes(c['production_and_verifier_sha256']);assert package_hashes()==c['input_file_sha256']
    assert j['id']==JOB and j['case_id']==CASE and j['action']=='run_patient_engineering'
    export=RUN/'export'/JOB;report=read(export/'patient_engineering_report.json')
    assert report['case_id']==CASE and report['patient_data'] is True and report['engineering_trial'] is True
    assert report['clinical_validation']=='not_validated' and report['numerical_validation'] in ['unchecked','failed']
    assert report['input_fingerprint']==c['native_patient_input_fingerprint']
    assert j['result']['input_fingerprint']==report['input_fingerprint'] and j['result']['execution_status']==report['execution_status']
    records=report['scenario']['evaluations'];assert records
    checks=[];allhashes={'patient_engineering_report.json':sha(export/'patient_engineering_report.json'),'patient_input_fingerprint.json':sha(export/'patient_input_fingerprint.json')}
    for ev in records:
        rel='evaluations/'+pathlib.PurePosixPath(ev['case']).name;d=export/rel
        result=evaluation_audit(d,ev);checks.append(result)
        allhashes.update({rel+'/'+f:h for f,h in result['artifact_sha256'].items()})
        rfile='evaluations/evaluation_'+d.name.split('_')[1]+'.json';allhashes[rfile]=sha(export/rfile)
    write_once(EVIDENCE/'raw_evaluations.json',checks)
    last=records[-1];d=export/'evaluations'/pathlib.PurePosixPath(last['case']).name
    source=list((d/'VTK').rglob('internal.vtu'));assert len(source)==1;source=source[0]
    allhashes[source.relative_to(export).as_posix()]=sha(source)
    code="import pathlib,hashlib,json,sys;p=pathlib.Path(sys.argv[1]);print(json.dumps({rel:hashlib.sha256((p/rel).read_bytes()).hexdigest() for rel in json.loads(sys.argv[2])}))"
    native=json.loads(wsl(code,NATIVE,json.dumps(list(allhashes))));assert native==allhashes
    write_once(EVIDENCE/'native_export_hash_identity.json',{'passed':True,'files':allhashes})
    assert not j['result'].get('viewer_export_error'),j['result'].get('viewer_export_error')
    mesh=read(RUN/'viewer_mesh.json');manifest=read(RUN/'viewer.json');config=read(d/'config.json')
    from audit_patient_field_arrays import audit
    field_result=audit(mesh,manifest,source,config,JOB,CASE)
    pv=mesh['result']['provenance'];assert pv['native_case']==last['case'] and pv['evaluation']==d.name
    assert pv['field_time']==checks[-1]['field_time']
    assert pv['p_file_sha256']==sha(d/pv['field_time']/'p') and pv['U_file_sha256']==sha(d/pv['field_time']/'U')
    if report['execution_status']=='failed':assert j['status']=='failed' and mesh['result']['numerical_validation']=='failed'
    if not checks[-1]['independent_quality_all_gates']:assert j['status']!='completed'
    write_once(EVIDENCE/'actual_patient_field_audit.json',field_result)
    served={}
    for name in ['viewer.json','viewer_mesh.json','patient-final-internal.vtu','patient-final-config.json']:
        relative=j['asset_paths'][name];local=(RUN/relative).resolve();assert local.is_relative_to(RUN)
        blob=get('/simulation-assets/'+JOB+'/'+name);actual=hashlib.sha256(blob).hexdigest();assert actual==sha(local)
        served[name]=actual
    write_once(EVIDENCE/'actual_served_asset_hashes.json',served)
    command=[r'D:\ruanjian\node.exe',str(OUT/'audit_patient_readonly_ui.cjs'),'terminal',str(EVIDENCE/'actual-terminal-ui')]
    env=os.environ.copy();env['NODE_PATH']=r'C:\Users\lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
    process=subprocess.run(command,cwd=ROOT,env=env,text=True,encoding='utf-8',capture_output=True,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    write_once(EVIDENCE/'terminal_ui_command.json',{'command':command,'exit_code':process.returncode,'stdout':process.stdout,'stderr':process.stderr})
    assert process.returncode==0,'Actual final UI audit failed; inspect preserved browser evidence'
    return {'audit_passed':True,'job_id':JOB,'job_status':j['status'],'runner_execution_status':report['execution_status'],
            'patient_numerical_accepted':bool(j['status']=='completed' and checks[-1]['independent_quality_all_gates']),
            'clinical_validation':'not_validated','native_export_files_verified':len(allhashes),'field_audit':field_result,
            'scope':'Honest engineering diagnostics/identity/field display; Lead alone can grant task verification'}
def watch():
    c=read(CONTRACT);assert c['job_id']==JOB and c['native_root']==NATIVE
    EVIDENCE.mkdir();write_once(EVIDENCE/'watcher_identity.json',{'pid':os.getpid(),'started_at':now(),'executable':sys.executable,'argv':sys.argv,'script_sha256':sha(__file__),'contract_sha256':sha(CONTRACT)})
    started=time.monotonic();previous=None;heartbeat=0
    try:
        verify_hashes(c['production_and_verifier_sha256']);assert package_hashes()==c['input_file_sha256']
        while True:
            verify_hashes(c['production_and_verifier_sha256'])
            j=read(RUN/'job.json');assert j['id']==JOB and j['case_id']==CASE
            p=j.get('live_progress') or {};state={k:j.get(k) for k in ['status','stage','worker_pid','solver_pid','updated_at']}
            state.update(iteration=p.get('iteration'),evaluation=p.get('evaluation'),native_case=p.get('native_case'),actual_step=p.get('actual_step'))
            stable={k:v for k,v in state.items() if k!='updated_at'}
            if stable!=previous or time.monotonic()-heartbeat>300:event({'observation':state});previous=stable;heartbeat=time.monotonic()
            if j['status'] in ('completed','failed','interrupted'):
                event({'stage':'terminal_raw_audit_started'});final=terminal_audit(j,c);break
            if time.monotonic()-started>c['deadline_seconds']:
                final={'audit_passed':False,'incomplete':True,'reason':'36-hour observer deadline reached; job left untouched','last_observation':state};break
            time.sleep(20)
    except Exception:final={'audit_passed':False,'failure':traceback.format_exc(),'job_id':JOB,'job_left_untouched':True}
    final['finished_at']=now();write_once(EVIDENCE/'final_audit.json',final);event({'stage':'observer_stopped','audit_passed':final['audit_passed']})
    print(json.dumps(final,ensure_ascii=False));return 0 if final['audit_passed'] else 1
def checkpoint():
    c=read(CONTRACT);verify_hashes(c['production_and_verifier_sha256']);assert package_hashes()==c['input_file_sha256']
    j=read(RUN/'job.json');assert j['id']==JOB and j['case_id']==CASE and j['status']=='running'
    code="import pathlib,json,re,hashlib,subprocess,sys;r=pathlib.Path(sys.argv[1]);p=r/'evaluations/eval_001';s=(p/'log.simpleFoam').read_text();print(json.dumps({'fingerprint':json.loads((r/'patient_input_fingerprint.json').read_text()),'run_status':json.loads((p/'run_status.json').read_text()),'last_iteration':re.findall(r'(?m)^Time = (\\S+)',s)[-1],'raw_log_sha256':hashlib.sha256(s.encode()).hexdigest(),'simpleFoam_processes':subprocess.check_output(['pgrep','-a','-x','simpleFoam'],text=True).splitlines()}))"
    native=json.loads(wsl(code,NATIVE));assert native['fingerprint']==c['native_patient_input_fingerprint']
    proof={'passed':True,'at':now(),'job_id':JOB,'status':j['status'],'worker_pid':j.get('worker_pid'),'solver_pid':j.get('solver_pid'),
           'native':native,'source_frozen_count':len(c['production_and_verifier_sha256']),'input_frozen_count':len(c['input_file_sha256'])}
    write_once(OUT/'patient_terminal_watch_running_checkpoint.json',proof);print(json.dumps(proof,ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--checkpoint',action='store_true');a=p.parse_args()
    assert sum([a.prepare,a.watch,a.checkpoint])==1
    if a.prepare:prepare()
    elif a.checkpoint:checkpoint()
    else:raise SystemExit(watch())
