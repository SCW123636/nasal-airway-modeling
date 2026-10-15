"""Read-only review of the existing failed job; never invokes solver/exporter."""
import datetime,hashlib,json,pathlib,re,shutil,subprocess,traceback,urllib.request
OUT=pathlib.Path(__file__).resolve().parent;ROOT=OUT.parents[2]
JOB='s_942fdbebfffd433c8fcec956';RUN=pathlib.Path('C:/ts_work/project_cases/simulation_jobs')/JOB
EXPORT=RUN/'export'/JOB;D=EXPORT/'evaluations/eval_001';NATIVE='/home/lenovo2/nasal_cfd_workspace_jobs/'+JOB
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def write(p,d):
    with p.open('x',encoding='utf-8') as f:json.dump(d,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
target=OUT/'raw-review.json';assert not target.exists()
protected=[ROOT/'outputs/T-023/watch_b15_readonly_acceptance.py',ROOT/'outputs/T-023/watch_b15_readonly_acceptance_v2.py',
           ROOT/'outputs/T-023/patient-terminal-watch-v2/final_audit.json',RUN/'job.json']
before={str(p):sha(p) for p in protected};result={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'job_id':JOB}
try:
    frozen=read(ROOT/'outputs/T-023/patient_terminal_watch_contract_v2.json')
    for label in ['production_and_verifier_sha256','input_file_sha256']:
        for p,h in frozen[label].items():assert sha(p)==h,(p,'frozen fingerprint changed')
    job=read(RUN/'job.json');report=read(EXPORT/'patient_engineering_report.json');ev=read(EXPORT/'evaluations/evaluation_001.json')
    manifest=read(D/'run_manifest.json');status=read(D/'run_status.json')
    assert job['id']==JOB and job['status']==job['stage']=='failed' and job['exit_code']==1
    assert job['case_id']==report['case_id']=='b15_engineering' and report['execution_status']=='failed'
    assert report['scenario']['result'] is None and len(report['scenario']['evaluations'])==1 and ev['status']=='failed' and ev['exit_code']==1
    assert not (EXPORT/'evaluations/eval_002').exists()
    assert report['input_fingerprint']==frozen['native_patient_input_fingerprint']
    assert manifest['execution_status']==status['status']=='failed' and manifest['engineering_acceptance'] is False
    assert manifest['case']==status['case']==ev['case']==NATIVE+'/evaluations/eval_001'
    log=(D/'log.simpleFoam').read_text(encoding='utf-8');execution=(D/'execution.log').read_text(encoding='utf-8')
    commands=[json.loads(l) for l in execution.splitlines() if l.startswith('{')]
    assert [(x['command'][0],x['exit_code']) for x in commands]==[('checkMesh',0),('simpleFoam',-8)]
    assert [s['command'][0] for s in manifest['steps']]==['checkMesh']
    assert ev['command'][ev['command'].index('--steps')+1]=='checkMesh,simpleFoam,foamToVTK'
    markers=list(re.finditer(r'(?m)^Time = (\S+)',log));assert markers[-1].group(1)=='223'
    assert 'GAMGSolver' in log and 'sigFpe' in log and not re.search(r'(?m)^End\s*$',log)
    assert 'SIMPLE solution converged' not in log
    mesh_log=(D/'log.checkMesh').read_text(encoding='utf-8');assert 'Failed 2 mesh checks' in mesh_log
    raw_list=['patient_engineering_report.json','patient_input_fingerprint.json','evaluations/evaluation_001.json']
    raw_list+=['evaluations/eval_001/'+x for x in ['run_manifest.json','run_status.json','execution.log','log.simpleFoam','log.checkMesh','case_manifest.json','config.json','0/p','0/U']]
    hashes={p:sha(EXPORT/p) for p in raw_list}
    code="import pathlib,json,hashlib,re,subprocess,sys;p=pathlib.Path(sys.argv[1]);d=p/'evaluations/eval_001';q=subprocess.run(['pgrep','-a','-x','simpleFoam'],text=True,capture_output=True);print(json.dumps({'hashes':{r:hashlib.sha256((p/r).read_bytes()).hexdigest() for r in json.loads(sys.argv[2])},'numeric_field_directories':[x.name for x in d.iterdir() if x.is_dir() and re.fullmatch(r'[0-9]+(?:[.][0-9]+)?',x.name)],'vtu_files':[str(x.relative_to(p)) for x in p.rglob('*.vtu')],'foamToVTK_log_exists':(d/'log.foamToVTK').exists(),'simpleFoam_pgrep_exit':q.returncode,'simpleFoam_processes':q.stdout.splitlines()}))"
    native=json.loads(subprocess.check_output(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',code,NATIVE,json.dumps(raw_list)],text=True,encoding='utf-8',timeout=30))
    assert native['hashes']==hashes and native['vtu_files']==[] and not native['foamToVTK_log_exists'] and native['simpleFoam_processes']==[]
    assert sorted(native['numeric_field_directories'],key=float)==['0','200']
    missing={'native_VTU':not native['vtu_files'],'export_VTU':not list(EXPORT.rglob('*.vtu')),
             'native_foamToVTK_log':not native['foamToVTK_log_exists'],'export_foamToVTK_log':not(D/'log.foamToVTK').exists(),
             'final_223_fields':not(D/'223').exists(),'job_viewer_manifest':not(RUN/'viewer.json').exists(),'job_viewer_mesh':not(RUN/'viewer_mesh.json').exists()}
    assert all(missing.values())
    assert not any(a['name']=='viewer' or '.vtu' in a['name'] or 'viewer_mesh' in a['name'] for a in job['artifacts'])
    assert job['result']['viewer_export_error']=='本次最终评估VTU缺失或不唯一'
    old_audit=read(protected[2]);assert old_audit['audit_passed'] is False and "m['steps']" in old_audit['failure']
    snap=OUT/'raw-snapshots';snap.mkdir()
    for relative in raw_list:
        if relative.endswith('/0/p') or relative.endswith('/0/U'):continue
        dest=snap/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(EXPORT/relative,dest);assert sha(dest)==hashes[relative]
    with urllib.request.urlopen('http://127.0.0.1:8769/api/simulation/jobs/'+JOB) as f:api=json.load(f)
    write(OUT/'actual-api-job.json',api);assert api['status']=='failed' and api['result']['scenario']['result'] is None
    denied=[]
    for name in ['viewer.json','viewer_mesh.json','patient-final-internal.vtu']:
        try:
            urllib.request.urlopen('http://127.0.0.1:8769/simulation-assets/'+JOB+'/'+name)
        except urllib.error.HTTPError as e:assert e.code==404;denied.append({'asset':name,'http_status':e.code})
        else:raise AssertionError('Missing current field unexpectedly served: '+name)
    result.update(evidence_review_complete=True,patient_numerical_accepted=False,clinical_validation='not_validated',
                  actual_job_status=job['status'],actual_job_finished=job['updated_at'],runner_exit_code=1,
                  raw_executed_commands=commands,manifest_successfully_recorded_steps=manifest['steps'],
                  last_started_iteration='223',solver_ended=False,convergence_banner=False,stack_contains_GAMG_and_sigFpe=True,
                  existing_unaccepted_field_times=native['numeric_field_directories'],missing_outputs=missing,
                  native_export_sha256_equal=hashes,missing_asset_http_denials=denied,
                  source_and_input_fingerprint_counts={k:len(frozen[k]) for k in ['production_and_verifier_sha256','input_file_sha256']},
                  product_numerical_failure='simpleFoam raw execution exit -8 with GAMG/sigFpe stack at started iteration223; no causal diagnosis inferred',
                  independent_watcher_error='Wrong assumption that every failed run_manifest contains all planned steps. Failed execute raises before simpleFoam step append; foamToVTK never ran. This verifier assertion is not a product solver diagnosis.',
                  watcher_original_final_audit_sha256=sha(protected[2]),native_simpleFoam_processes=native['simpleFoam_processes'])
except Exception:result.update(evidence_review_complete=False,review_error=traceback.format_exc());raise
finally:
    after={str(p):sha(p) for p in protected};result['protected_before_sha256']=before;result['protected_after_sha256']=after
    assert before==after,'A protected source or old evidence changed during review'
    write(target,result)
print(json.dumps({'evidence_review_complete':True,'job_status':'failed','simpleFoam_raw_exit':-8,'last_started_iteration':223,'native_export_files_equal':len(hashes),'VTU_exists':False,'watcher_error_confirmed':True},ensure_ascii=False))
