"""GET/read-only inspection of the service that appeared before WMI Create."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import importlib.util
import json

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('t023_guard_v2',HERE/'reload_8769_only_t029_v2.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)


def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(number):
    source=guard.ROOT/'outputs/T-029/t029a_source_freeze_v2.json';freeze=read(source)
    assert sha(source)=='4382e6e213026bbeaf08acb8e42a87ed05bdec08c4e197798fcb626233ad3304'
    actual={p:sha(guard.ROOT/p) for p in freeze['code_sha256']};assert actual==freeze['code_sha256']
    package=Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering_t029a')
    previous=read(HERE/'frozen-input-audit.json')
    inputs={p.relative_to(package).as_posix():sha(p) for p in package.rglob('*') if p.is_file()}
    assert inputs==previous['candidate_files']
    current=guard.listener(8769);assert current['pid']==35408
    args=guard.verify_project_service(current)
    old=read(HERE/'service-reload-v2/launch.json')['command']
    assert args==old+['--open'],('actual changed commandline',args)
    raw=guard.powershell("$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(current['parent_pid'])+"'; if($p){$p|Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate|ConvertTo-Json -Compress}")
    parent=json.loads(raw or 'null');ancestor=None
    if parent:
        raw=guard.powershell("$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(parent['ParentProcessId'])+"'; if($p){$p|Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate|ConvertTo-Json -Compress}")
        ancestor=json.loads(raw or 'null')
    other=guard.listener(8774);assert guard.same_process(other,read(HERE/'service-reload-v2/before.json')['preserved_8774'])
    health=guard.get('/health.json');assert health['service']=='nasal-cfd-local-workspace/v1'
    catalog=guard.get('/api/simulation/catalog');items=[c for c in catalog['cases'] if c['id']=='b15_engineering_t029a'];assert len(items)==1
    case=items[0];assert case['run_allowed'] and case['run_action']=='run_patient_engineering'
    assert case['clinical_validation']=='not_validated' and not case['blocking_reasons']
    jobs=guard.get('/api/simulation/jobs')['jobs'];assert not [j for j in jobs if j['status'] in ('queued','running')]
    assert not [j for j in jobs if j['case_id']=='b15_engineering_t029a']
    quiet=guard.no_active_work();static={}
    for name in ['simulation.js','workspace.js']:
        blob=guard.get('/workspace/'+name,binary=True);local=guard.ROOT/'work/07_cfd_pipeline/workspace'/name
        assert blob==local.read_bytes();static[name]=hashlib.sha256(blob).hexdigest()
    report={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'inspection_round':number,'listener_8769':current,
            'launcher_parent':parent,'launcher_ancestor':ancestor,'actual_argv':args,'original_argv':old,
            'actual_extra_open_flag':True,'this_verifier_did_not_launch_this_process':True,
            'WMI_Create_executed_by_verifier':False,'health':health,'catalog':catalog,'candidate_catalog':case,
            'jobs':jobs,'quiet':quiet,'preserved_8774':other,'served_current_static_sha256':static,
            'T029_15_source_sha256':actual,'candidate_34_input_sha256':inputs,'read_only_no_POST':True,
            'scope':'Actual existing entrance/catalog inspection; not a successful T023 WMI recovery or patient numerical acceptance'}
    path=HERE/f'existing-service-observation-{number}.json'
    with path.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'round':number,'actual_listener_pid':current['pid'],'parent_pid':current['parent_pid'],
                      'new_case_run_allowed':case['run_allowed'],'no_candidate_job':True,'no_POST':True,
                      'actual_extra_open_flag_not_started_by_verifier':True},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--round',type=int,required=True);args=parser.parse_args();main(args.round)
