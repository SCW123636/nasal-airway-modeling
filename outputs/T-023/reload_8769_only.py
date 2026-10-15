"""Reload only verified project port 8769 with no active workers/jobs."""
import base64,hashlib,json,pathlib,re,subprocess,sys,time,urllib.request
from datetime import datetime,timezone
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent
BASE='http://127.0.0.1:8769'
def get(path):
    with urllib.request.urlopen(BASE+path,timeout=10) as r:return json.load(r)
def powershell(code):
    code='[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();'+code
    encoded=base64.b64encode(code.encode('utf-16-le')).decode('ascii')
    return subprocess.check_output(['powershell.exe','-NoProfile','-EncodedCommand',encoded]).decode('utf-8-sig').strip()
def listener(port):
    assert port in (8769,8774)
    code="$n=@(Get-NetTCPConnection -State Listen -LocalPort "+str(port)+" -ErrorAction Stop); if($n.Count -ne 1 -or $n[0].LocalAddress -ne '127.0.0.1'){throw 'unexpected listeners'}; $p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$n[0].OwningProcess); [pscustomobject]@{pid=$p.ProcessId;exe=$p.ExecutablePath;cmdline=$p.CommandLine;parent_pid=$p.ParentProcessId;create_time=$p.CreationDate.ToUniversalTime().ToString('o')} | ConvertTo-Json -Compress"
    return json.loads(powershell(code))
before=listener(8769);other_before=listener(8774)
assert re.search(r'(?:[\\/\s])serve_cfd_workspace[.]py(?:[\s\"]|$)',before['cmdline']),before
assert re.search(r'--port\s+8769(?:\s|$)',before['cmdline']),before
with urllib.request.urlopen(BASE+'/workspace/simulation.js',timeout=10) as response:served_js=response.read()
local_js=(ROOT/'work/07_cfd_pipeline/workspace/simulation.js').read_bytes()
assert served_js==local_js,'8769 static source does not match current project simulation.js'
health=get('/health.json');assert health['service']=='nasal-cfd-local-workspace/v1'
jobs=get('/api/simulation/jobs')['jobs'];active=[x for x in jobs if x['status'] in ['queued','running']]
assert not active,active
workers=json.loads(powershell("$p=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -match '\\\\python(?:w)?[.]exe$' -and $_.CommandLine -match 'cfd_workspace_jobs[.]py.+--worker'} | Select-Object ProcessId,ExecutablePath,CommandLine); ConvertTo-Json -InputObject $p -Compress") or '[]')
assert not workers,workers
report={'at':datetime.now(timezone.utc).isoformat(),'old_8769':before,'preserved_8774':other_before,
        'health_before':health,'active_jobs_before':active,'workers_before':workers,
        'served_current_project_simulation_js_sha256':hashlib.sha256(served_js).hexdigest(),
        'authorization':'T023 contract and Lead explicit handoff after T021 final freeze; no shortcut opened'}
if '--inspect-only' in sys.argv:
    target=OUT/'service_inspection_before_freeze.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));raise SystemExit(0)
start=OUT/'service_reload_before.json';assert not start.exists();start.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
assert listener(8769)['pid']==before['pid'] and listener(8769)['create_time']==before['create_time']
powershell('Stop-Process -Id '+str(before['pid'])+' -ErrorAction Stop')
command=[r'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Scripts\python.exe','-X','utf8',str(ROOT/'work/lib/serve_cfd_workspace.py'),'--port','8769']
case_root=re.search(r'--case-root\s+(?:"([^"]+)"|(\S+))',before['cmdline'])
if case_root:command+=['--case-root',case_root.group(1) or case_root.group(2)]
with (OUT/'service_8769_stdout.log').open('ab') as log:
    process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
        creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW)
for attempt in range(60):
    try:
        after_health=get('/health.json');new=listener(8769)
        if after_health['service']=='nasal-cfd-local-workspace/v1' and new['pid']!=before['pid']:break
    except (OSError,AssertionError):pass
    time.sleep(.25)
else:raise RuntimeError('8769 reload did not become healthy; old and startup evidence retained')
assert listener(8774)['pid']==other_before['pid'] and listener(8774)['create_time']==other_before['create_time']
report.update(new_8769=new,launcher_pid=process.pid,command=command,health_after=after_health,
              catalog_case_ids=[x['id'] for x in get('/api/simulation/catalog')['cases']],passed=True)
target=OUT/'service_reload_result.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'old_pid':before['pid'],'new_pid':new['pid'],'preserved_8774_pid':other_before['pid'],'catalog_case_ids':report['catalog_case_ids']},ensure_ascii=False))
