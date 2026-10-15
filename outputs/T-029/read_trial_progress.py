"""Read one actual new-job checkpoint, append evidence, and report finite monitors."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

OUT = Path(__file__).resolve().parent
response = json.loads((OUT / 't029a_post_response.json').read_text(encoding='utf-8'))
job_id = response['id']
job_dir = Path('C:/ts_work/project_cases/simulation_jobs') / job_id
job = json.loads((job_dir / 'job.json').read_text(encoding='utf-8'))
native = '/home/lenovo2/nasal_cfd_workspace_jobs/' + job_id
case = Path(r'\\wsl.localhost\Ubuntu-22.04') / native.lstrip('/') / 'evaluations/eval_001'
record = {'at':datetime.now(timezone.utc).isoformat(), 'job_id':job_id,
          'job_status':job['status'], 'job_stage':job['stage'],
          'worker_pid':job.get('worker_pid'), 'solver_launcher_pid':job.get('solver_pid'),
          'native_root':native, 'native_case':str(case), 'iteration':None, 'nonfinite_numeric':False}
status = case / 'run_status.json'
if status.is_file():
    record['native_status'] = json.loads(status.read_text(encoding='utf-8'))
log = case / 'log.simpleFoam'
if log.is_file():
    text = log.read_text(errors='replace')
    steps = re.findall(r'(?m)^Time = ([0-9.eE+-]+)', text)
    record['iteration'] = float(steps[-1]) if steps else None
    blocks = re.split(r'(?m)^Time = ', text)[1:]
    last = next((block for block in reversed(blocks) if 'time step continuity errors' in block), '')
    residuals = re.findall(r'Solving for (\w+), Initial residual = ([^,]+), Final residual = ([^,]+)', last)
    record['last_complete_step'] = float(last.splitlines()[0]) if last else None
    record['last_residuals'] = [[field, float(initial), float(final)] for field,initial,final in residuals]
    continuity = re.findall(r'time step continuity errors : sum local = ([^,]+), global = ([^,]+), cumulative = ([^\n]+)', last)
    record['continuity'] = list(map(float, continuity[-1])) if continuity else None
    record['nonfinite_numeric'] = bool(re.search(r'(?i)(?:Initial residual|Final residual|sum local|global|cumulative)\s*=\s*[-+]?(?:nan|inf)\b', text))
    record['log_tail'] = '\n'.join(text.splitlines()[-15:])
    record['fpe_present'] = 'Floating point exception' in text or 'sigFpe' in text
flows = {}
for patch in ('nostril_L', 'nostril_R', 'nasopharynx_outlet'):
    path = case / 'postProcessing' / ('flow_' + patch) / '0/surfaceFieldValue.dat'
    if path.is_file():
        rows = [line.split() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
        if rows:
            value = [float(item) for item in rows[-1]]
            flows[patch] = value
            record['nonfinite_numeric'] |= not all(math.isfinite(item) for item in value)
record['signed_flow_last_rows'] = flows
if job.get('error'):
    record['job_error'] = job['error']
folder = OUT / 'progress'
folder.mkdir(exist_ok=True)
path = folder / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
with path.open('x', encoding='utf-8') as stream:
    json.dump(record, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({key:value for key,value in record.items() if key not in ('log_tail','native_status')}, ensure_ascii=False))
