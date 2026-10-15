"""Perform one authorized formal POST only after immutable and CPU entry checks."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
CASE = 'b15_engineering_t029a'
BASE = 'http://127.0.0.1:8769'
TARGET = Path('C:/ts_work/project_cases/patient_cfd_inputs') / CASE
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def write_new(name, value):
    with (OUT / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
def get(route):
    with urllib.request.urlopen(BASE + route, timeout=20) as response:
        return json.load(response)

if (OUT / 't029a_post_attempt.json').exists():
    raise SystemExit('A formal POST attempt is already recorded. Inspect the job list; never retry automatically.')
freeze = json.loads((OUT / 't029a_source_freeze_v2.json').read_text(encoding='utf-8'))
for name, expected in freeze['code_sha256'].items():
    assert digest(ROOT / name) == expected, 'frozen code changed: ' + name
input_freeze = OUT / 't029a_input_freeze.json'
assert digest(input_freeze) == freeze['input_freeze_sha256']
inputs = json.loads(input_freeze.read_text(encoding='utf-8'))
for name, expected in inputs['trial_files'].items():
    assert digest(TARGET / name) == expected, 'frozen input changed: ' + name
assert {p.relative_to(TARGET).as_posix() for p in TARGET.rglob('*') if p.is_file()} == set(inputs['trial_files'])
catalog = get('/api/simulation/catalog')
item = next(record for record in catalog['cases'] if record['id'] == CASE)
assert item['run_allowed'] and item['run_action'] == 'run_patient_engineering', item
write_new('catalog-after-service-reload.json', catalog)
jobs = get('/api/simulation/jobs')['jobs']
assert not any(job['case_id'] == CASE and job['action'] == 'run_patient_engineering' for job in jobs), 'existing versioned run found'
assert not any(job['action'].startswith('run_') and job['status'] not in ('completed','failed','interrupted') for job in jobs), 'another run is active'
cpu_code = '''import json,os,subprocess
rows=[]
for line in subprocess.check_output(['ps','-eo','pid,comm,stat,pcpu,args','--no-headers'],text=True).splitlines():
 parts=line.split(None,4)
 if len(parts)==5: rows.append(dict(zip(('pid','command','state','cpu_percent','arguments'),parts)))
heavy={'simpleFoam','checkMesh','gmshToFoam','gmsh','netgen','snappyHexMesh','blockMesh','foamToVTK'}
active=[r for r in rows if r['command'] in heavy and 'Z' not in r['state']]
print(json.dumps({'load_average':list(os.getloadavg()),'cpu_count':os.cpu_count(),'active_heavy_processes':active,'processes':rows,'uptime':subprocess.check_output(['uptime'],text=True).strip()}))
'''
probe = subprocess.run(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',cpu_code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
assert probe.returncode == 0, probe.stderr
cpu = json.loads(probe.stdout)
write_new('cpu-entry-check.json', cpu)
assert not cpu['active_heavy_processes'], cpu['active_heavy_processes']
assert cpu['load_average'][0] <= 0.5, 'native load is not approximately idle; stop before any POST'
payload = {'case_id':CASE, 'action':'run_patient_engineering', 'settings':{}}
attempt = {'at':datetime.now(timezone.utc).isoformat(), 'url':BASE+'/api/simulation/jobs',
           'request':payload, 'source_freeze_v2_sha256':digest(OUT / 't029a_source_freeze_v2.json'),
           'instruction':'One formal POST only. A transport failure must be reconciled by GET, never retried.'}
write_new('t029a_post_attempt.json', attempt)
request = urllib.request.Request(attempt['url'], data=json.dumps(payload).encode('utf-8'),
                                 headers={'Content-Type':'application/json'}, method='POST')
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
except Exception as exc:
    write_new('t029a_post_error.json', {'at':datetime.now(timezone.utc).isoformat(), 'error':repr(exc)})
    raise
write_new('t029a_post_response.json', result)
print(json.dumps({'job_id':result['id'], 'case_id':result['case_id'], 'status':result['status'],
                  'cpu_entry_load':cpu['load_average'], 'post_attempts':1}, ensure_ascii=False))
