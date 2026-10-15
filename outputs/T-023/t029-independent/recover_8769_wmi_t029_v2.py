"""Lead contract10: one hidden WMI recovery of the already stopped 8769 service.

No Stop-Process, Popen service launch, POST, solver or monitor. Fresh evidence only.
"""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import time
import urllib.request

HERE=Path(__file__).resolve().parent
OUT=HERE/'service-recovery-wmi'
spec=importlib.util.spec_from_file_location('reload_guard_v2',HERE/'reload_8769_only_t029_v2.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)


def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def write_once(name,value):
    with (OUT/name).open('x',encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def absent_and_quiet():
    code="$listeners=@(Get-NetTCPConnection -State Listen -LocalPort 8769 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess); $service=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -match '\\\\python(?:w)?[.]exe$' -and $_.CommandLine -match 'serve_cfd_workspace[.]py.+--port\\s+8769(?:\\s|$)'} | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate); $workers=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -match '\\\\python(?:w)?[.]exe$' -and $_.CommandLine -match 'cfd_workspace_jobs[.]py.+--worker'} | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate); @{listeners=$listeners;services=$service;workers=$workers} | ConvertTo-Json -Depth 6 -Compress"
    observed=json.loads(guard.powershell(code))
    assert not observed['listeners'] and not observed['services'] and not observed['workers'],observed
    root=Path('C:/ts_work/project_cases/simulation_jobs')
    jobs=[read(p) for p in sorted(root.glob('*/job.json'))]
    assert not [j for j in jobs if j['status'] in ('queued','running')]
    status={j['id']:j['status'] for j in jobs}
    assert status['s_942fdbebfffd433c8fcec956']=='failed'
    assert status['s_1811f735241e4d75b5fdf10e']=='completed'
    assert not [j for j in jobs if j.get('case_id')=='b15_engineering_t029a']
    return {'os':observed,'local_job_status':status,'no_candidate_job':True}


def snapshot():
    current=guard.listener(8769)
    health=guard.get('/health.json');assert health['service']=='nasal-cfd-local-workspace/v1'
    catalog=guard.get('/api/simulation/catalog')
    candidate=[x for x in catalog['cases'] if x['id']=='b15_engineering_t029a'];assert len(candidate)==1
    case=candidate[0]
    assert case['run_allowed'] is True and case['run_action']=='run_patient_engineering'
    assert case['clinical_validation']=='not_validated' and not case['blocking_reasons']
    assert guard.verify_project_service(current)==read(HERE/'service-reload-v2/launch.json')['command']
    other=guard.listener(8774);prior=read(HERE/'service-reload-v2/before.json')['preserved_8774']
    assert guard.same_process(other,prior)
    raw=guard.powershell("$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(current['parent_pid'])+"'; if($p){$p|Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate|ConvertTo-Json -Compress}")
    parent=json.loads(raw or 'null')
    ancestor=None
    if parent:
        raw=guard.powershell("$p=Get-CimInstance Win32_Process -Filter 'ProcessId="+str(parent['ParentProcessId'])+"'; if($p){$p|Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate|ConvertTo-Json -Compress}")
        ancestor=json.loads(raw or 'null')
    static={}
    for name in ['simulation.js','workspace.js']:
        blob=guard.get('/workspace/'+name,binary=True)
        assert blob==(guard.ROOT/'work/07_cfd_pipeline/workspace'/name).read_bytes()
        static[name]=hashlib.sha256(blob).hexdigest()
    return {'at':now(),'listener_8769':current,'launcher_parent':parent,'wmi_ancestor':ancestor,
            'health':health,'candidate_catalog':case,'catalog':catalog,'preserved_8774':other,
            'quiet':guard.no_active_work(),'static_sha256':static,'no_POST':True}


def main():
    guard.frozen_contract(HERE/'service-recovery-contract-v3.json')
    OUT.mkdir(exist_ok=False)
    report={'at':now(),'script_sha256':sha(__file__),'authorization':'Lead a325bb5 contract10 explicit recovery notice; no further stop; same argv/ROOT/case-root; ShowWindow0 with no CreateFlags',
            'prior_Popen_failure_sha256':sha(HERE/'service-reload-v2/failure.json')}
    try:
        before=read(HERE/'service-reload-v2/before.json')
        assert guard.same_process(guard.listener(8774),before['preserved_8774'])
        report['preflight']=absent_and_quiet()
        old=before['old_8769'];command=old['cmdline']
        assert guard.verify_project_service(old)==read(HERE/'service-reload-v2/launch.json')['command']
        report.update(original_commandline=command,original_argv=guard.argv_windows(command),cwd=str(guard.ROOT),
                      preserved_8774=guard.listener(8774))
        write_once('before.json',report)
        guard.frozen_contract(HERE/'service-recovery-contract-v3.json')
        absent_and_quiet()
        literal=lambda value:str(value).replace("'","''")
        code="$startup=([wmiclass]'Win32_ProcessStartup').CreateInstance(); $startup.ShowWindow=0; $result=([wmiclass]'Win32_Process').Create('"+literal(command)+"','"+literal(guard.ROOT)+"',$startup); [pscustomobject]@{ReturnValue=$result.ReturnValue;ProcessId=$result.ProcessId;ShowWindow=$startup.ShowWindow;CreateFlagsSpecified=$false}|ConvertTo-Json -Compress"
        created=json.loads(guard.powershell(code))
        write_once('wmi-create.json',{'at':now(),**created,'commandline':command,'cwd':str(guard.ROOT)})
        assert created['ReturnValue']==0 and created['ShowWindow']==0 and not created['CreateFlagsSpecified']
        for _ in range(30):
            try:
                with urllib.request.urlopen(guard.BASE+'/health.json',timeout=1) as response:
                    if json.load(response)['service']=='nasal-cfd-local-workspace/v1':break
            except OSError: pass
            time.sleep(.25)
        else: raise RuntimeError('WMI recovery not healthy; no second launch')
        first=snapshot();write_once('snapshot-1.json',first)
        guard.frozen_contract(HERE/'service-recovery-contract-v3.json')
        print(json.dumps({'initial_health_observed':True,'wmi_launcher_pid':created['ProcessId'],
                          'actual_listener_pid':first['listener_8769']['pid'],'candidate_run_allowed':first['candidate_catalog']['run_allowed'],
                          'cross_tool_persistence_not_yet_checked':True,'no_POST':True},ensure_ascii=False))
    except Exception as exc:
        report.update(failed=True,exception=repr(exc));write_once('failure.json',report);raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true',required=True);parser.parse_args();main()
