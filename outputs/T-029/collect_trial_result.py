"""Freeze the actual terminal trial evidence without copying huge solution fields."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()
def freeze(path, value):
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == value, 'prior terminal evidence differs: ' + str(path)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def copy_exact(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert digest(target) == digest(source), 'prior actual evidence differs: ' + str(target)
    else:
        shutil.copy2(source, target)
    return {'source':str(source), 'sha256':digest(source), 'bytes':source.stat().st_size}

response = json.loads((OUT / 't029a_post_response.json').read_text(encoding='utf-8'))
job_id = response['id']
job_dir = Path('C:/ts_work/project_cases/simulation_jobs') / job_id
job = json.loads((job_dir / 'job.json').read_text(encoding='utf-8'))
assert job['status'] in ('completed','failed','interrupted'), 'job is not terminal; do not freeze stale evidence'
native = Path(r'\\wsl.localhost\Ubuntu-22.04\home\lenovo2\nasal_cfd_workspace_jobs') / job_id
case = native / 'evaluations/eval_001'
input_record = json.loads((OUT / 't029a_input_freeze.json').read_text(encoding='utf-8'))
source_record = json.loads((OUT / 't029a_source_freeze_v2.json').read_text(encoding='utf-8'))
assert all(digest(ROOT / name) == expected for name, expected in source_record['code_sha256'].items()), 'frozen source changed'
package = Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering_t029a')
assert all(digest(package / name) == expected for name,expected in input_record['trial_files'].items()), 'frozen input changed'
baseline = package.with_name('b15_engineering')
assert all(digest(baseline / name) == expected for name,expected in input_record['original_files'].items()), 'original package changed'
evidence = {}
for rel in ('0/p','0/U','constant/transportProperties','constant/turbulenceProperties','constant/polyMesh/boundary',
            'system/controlDict','system/fvSchemes','system/fvSolution','config.json','case_manifest.json',
            'engineering_authorization.json','engineering_authorization_record.md','run_manifest.json','run_status.json',
            'log.checkMesh','log.simpleFoam','log.foamToVTK','execution.log'):
    source = case / rel
    if source.is_file():
        evidence[rel] = copy_exact(source, OUT / 'trial_actual' / rel)
for rel in ('patient_input_fingerprint.json','patient_engineering_report.json','evaluations/evaluation_001.json','evaluations/input_fingerprint.json'):
    source = native / rel
    if source.is_file():
        evidence['root/' + rel] = copy_exact(source, OUT / 'trial_actual/root' / rel)
for path in sorted((case / 'postProcessing').rglob('surfaceFieldValue.dat')):
    rel = path.relative_to(case).as_posix()
    evidence[rel] = copy_exact(path, OUT / 'trial_actual' / rel)
evidence['job.json'] = copy_exact(job_dir / 'job.json', OUT / 'trial_actual/job.json')
mesh = {path.relative_to(case / 'constant/polyMesh').as_posix():digest(path)
        for path in sorted((case / 'constant/polyMesh').rglob('*')) if path.is_file()}
expected_mesh = json.loads((package / 'admission.json').read_text(encoding='utf-8'))['mesh_fingerprint']
assert mesh == expected_mesh, 'actual mesh differs from frozen mesh'
fields = {}
for folder in case.iterdir():
    if folder.is_dir() and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', folder.name):
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.name in ('p','U','phi'):
                fields[path.relative_to(case).as_posix()] = {'sha256':digest(path), 'bytes':path.stat().st_size}
vtu = {path.relative_to(case).as_posix():{'sha256':digest(path), 'bytes':path.stat().st_size}
       for path in sorted((case / 'VTK').rglob('*.vtu')) if path.is_file()}
flow_rows = {}
for patch in ('nostril_L','nostril_R','nasopharynx_outlet'):
    source = case / 'postProcessing' / ('flow_' + patch) / '0/surfaceFieldValue.dat'
    flow_rows[patch] = {int(float(line.split()[0])):float(line.split()[1]) for line in source.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith('#')} if source.is_file() else {}
text = (case / 'log.simpleFoam').read_text(errors='replace') if (case / 'log.simpleFoam').is_file() else ''
timeline = []
for block in re.split(r'(?m)^Time = ', text)[1:]:
    step = int(float(block.splitlines()[0]))
    continuity = re.findall(r'time step continuity errors : sum local = ([^,]+), global = ([^,]+), cumulative = ([^\n]+)', block)
    residuals = [[field,float(initial),float(final)] for field,initial,final in re.findall(r'Solving for (\w+), Initial residual = ([^,]+), Final residual = ([^,]+)', block)]
    timeline.append({'time':step, 'residuals':residuals, 'continuity':list(map(float, continuity[0])) if continuity else None,
                     'flow_m3_s':{name:rows.get(step) for name,rows in flow_rows.items()}})
all_numbers = [value for item in timeline for _,a,b in item['residuals'] for value in (a,b)]
all_numbers += [value for item in timeline for value in item['flow_m3_s'].values() if value is not None]
all_numbers += [value for item in timeline for value in (item['continuity'] or [])]
finite = all(math.isfinite(value) for value in all_numbers)
old = {record['time']:record for record in json.loads((OUT / 'iteration_timeline.json').read_text())}
comparison = [{'step':record['time'], 'failed_baseline':old[record['time']], 'upwind_trial':record}
              for record in timeline if record['time'] in (1,20,50,100,120) and record['time'] in old]
manifest = json.loads((case / 'run_manifest.json').read_text()) if (case / 'run_manifest.json').is_file() else {}
summary = {'schema':'nasal_t029_actual_trial/v1','job_id':job_id,'case_id':job['case_id'],
           'job_status':job['status'],'outer_exit_code':job.get('exit_code'),'error':job.get('error'),
           'native_case':str(case), 'actual_manifest':manifest,
           'actual_mesh_fingerprint':mesh,'mesh_matches_frozen':True,'source_freeze_v2_sha256':digest(OUT / 't029a_source_freeze_v2.json'),
           'source_unchanged':True,'new_package_unchanged':True,'original_package_unchanged':True,
           'native_actual_evidence':evidence,'runtime_field_fingerprints':fields,'vtu_fingerprints':vtu,
           'attempted_steps':len(timeline),'last_attempted_step':timeline[-1]['time'] if timeline else None,
           'complete_monitor_steps':len(flow_rows['nostril_L']),'all_parsed_numeric_values_finite':finite,
           'fpe_in_log':bool(re.search(r'Floating point exception|sigFpe',text)),
           'solver_End_banner':bool(re.search(r'(?m)^End\s*$',text)),
           'SIMPLE_converged_banner':'SIMPLE solution converged' in text,
           'clinical_validation':'not_validated','interpretation':'Bounded engineering evidence only; gates unchanged; fields are not a converged patient solution'}
freeze(OUT / 'trial_timeline.json', timeline)
freeze(OUT / 'baseline_trial_comparison.json', comparison)
freeze(OUT / 't029a_actual_result.json', summary)
print(json.dumps({key:value for key,value in summary.items() if key not in ('actual_manifest','actual_mesh_fingerprint','native_actual_evidence','runtime_field_fingerprints','vtu_fingerprints')}, ensure_ascii=False))
