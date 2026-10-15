"""One-shot GET/native-file observer for one existing T029 job; never launches CFD.

No loop/daemon/POST/service operation. Only this evidence directory is writable.
"""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import urllib.request

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
JOB='s_aa79a63027b94bfb9a273898'
CASE='b15_engineering_t029a'
JOBS=Path('C:/ts_work/project_cases/simulation_jobs')
PACKAGE=Path('C:/ts_work/project_cases/patient_cfd_inputs')/CASE
NATIVE='/home/lenovo2/nasal_cfd_workspace_jobs/'+JOB
CONTRACT=HERE/'candidate-observation-contract.json'


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def write_once(p,value):
    assert p.resolve().is_relative_to(HERE)
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def frozen_identity():
    source=ROOT/'outputs/T-029/t029a_source_freeze_v2.json'
    assert sha(source)=='4382e6e213026bbeaf08acb8e42a87ed05bdec08c4e197798fcb626233ad3304'
    declared=read(source)['code_sha256'];actual={p:sha(ROOT/p) for p in declared};assert actual==declared
    files={p.relative_to(PACKAGE).as_posix():sha(p) for p in PACKAGE.rglob('*') if p.is_file()}
    assert files==read(HERE/'frozen-input-audit.json')['candidate_files']
    return {'source_freeze_sha256':sha(source),'production_15_sha256':actual,'input_34_sha256':files}


NATIVE_READER=r'''
import pathlib,json,re,sys,subprocess,hashlib
r=pathlib.Path(sys.argv[1]);value={'native_root':str(r),'native_root_exists':r.exists(),'evaluations':[]}
fp=r/'patient_input_fingerprint.json'
if fp.is_file():value['patient_input_fingerprint']=json.loads(fp.read_text())
for e in sorted((r/'evaluations').glob('eval_*')):
 if not e.is_dir():continue
 item={'evaluation':e.name,'native_case':str(e),'files':[p.name for p in e.iterdir()]}
 for name in ['run_status.json','run_manifest.json','config.json','case_manifest.json']:
  if (e/name).is_file():item[name]=json.loads((e/name).read_text())
 for name in ['system/controlDict','system/fvSchemes','system/fvSolution','constant/transportProperties','constant/turbulenceProperties','0/p','0/U']:
  p=e/name
  if p.is_file():item[name]={'text':p.read_text(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 for name in ['log.simpleFoam','log.checkMesh','execution.log']:
  p=e/name
  if p.is_file():
   text=p.read_text(errors='replace');item[name]={'size_bytes':p.stat().st_size,'tail':text[-12000:],'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
   if name=='log.simpleFoam':item['last_started_iteration']=(re.findall(r'(?m)^Time = (\S+)',text) or [None])[-1]
 item['field_directories']=sorted([p.name for p in e.iterdir() if p.is_dir() and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',p.name)],key=float)
 item['VTU_files']=[str(p.relative_to(e)) for p in (e/'VTK').rglob('*.vtu')] if (e/'VTK').exists() else []
 value['evaluations'].append(item)
process=subprocess.run(['pgrep','-a','-x','simpleFoam'],capture_output=True,text=True)
value['actual_simpleFoam_processes']=process.stdout.splitlines()
print(json.dumps(value,ensure_ascii=False,allow_nan=False))
'''


def capture(number):
    identity=frozen_identity()
    local=read(JOBS/JOB/'job.json')
    assert local['id']==JOB and local['case_id']==CASE and local['action']=='run_patient_engineering'
    assert local['settings']=={} and local['patient_binding']['admission_sha256']==identity['input_34_sha256']['admission.json']
    candidates=[read(p) for p in JOBS.glob('*/job.json') if read(p).get('case_id')==CASE]
    assert len(candidates)==1 and candidates[0]['id']==JOB,'not the single authorized candidate job'
    with urllib.request.urlopen('http://127.0.0.1:8769/api/simulation/jobs/'+JOB,timeout=10) as response:api=json.load(response)
    assert api['id']==JOB and api['case_id']==CASE and api['action']==local['action']
    native=json.loads(subprocess.check_output(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',NATIVE_READER,NATIVE],text=True,encoding='utf-8',timeout=45))
    record={'at':now(),'round':number,'identity':identity,'local_job':local,'actual_API_job':api,'native_readonly':native,
            'observer_script_sha256':sha(__file__),'no_POST':True,'no_solver_or_service_launch':True,
            'persistent_monitor_started':False,'patient_numerical_accepted':False}
    write_once(HERE/'observations'/f'{number:03}.json',record)
    print(json.dumps({'round':number,'job':JOB,'actual_status':local['status'],'actual_stage':local['stage'],
                      'worker_pid':local.get('worker_pid'),'solver_pid':local.get('solver_pid'),
                      'native_root_exists':native['native_root_exists'],'evaluations':[(e['evaluation'],e.get('last_started_iteration')) for e in native['evaluations']],
                      'no_POST':True},ensure_ascii=False))
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--bind',action='store_true');mode.add_argument('--snapshot',type=int);args=parser.parse_args()
    if args.bind:
        assert not CONTRACT.exists()
        record=capture(0)
        write_once(CONTRACT,{'schema':'t023_t029_single_existing_job_observation/v1','at':now(),
                   'job_id':JOB,'case_id':CASE,'native_root':NATIVE,'job_root':str(JOBS/JOB),
                   'frozen_identity':record['identity'],'initial_status':record['local_job']['status'],
                   'initial_stage':record['local_job']['stage'],'observer_sha256':sha(__file__),
                   'Lead_authorization':'T023合同7/8；Lead确认作者唯一POST后只读观察，不再服务/WMI操作。',
                   'persistent_monitor_started':False,'patient_numerical_accepted':False})
    else:
        contract=read(CONTRACT);assert contract['job_id']==JOB and contract['observer_sha256']==sha(__file__)
        assert args.snapshot>0;capture(args.snapshot)
