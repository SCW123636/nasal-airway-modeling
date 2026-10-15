"""Read-only native/export identity and same-step numerical evidence, T029 only."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
JOB = 's_aa79a63027b94bfb9a273898'
OLD = 's_942fdbebfffd433c8fcec956'
JOBS = Path('C:/ts_work/project_cases/simulation_jobs')
NATIVE = '/home/lenovo2/nasal_cfd_workspace_jobs/'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


READER = r'''
import pathlib,hashlib,json,re,sys,math
root=pathlib.Path(sys.argv[1]);case=root/'evaluations/eval_001'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
log=(case/'log.simpleFoam').read_text();segments=re.split(r'(?m)^Time = (\S+)\s*$',log)
iterations=[]
for i in range(1,len(segments),2):
 step=float(segments[i]);body=segments[i+1]
 equations=[{'field':m[0],'initial':float(m[1]),'final':float(m[2])} for m in re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+), Final residual = ([\deE+.-]+)',body)]
 continuity=re.findall(r'time step continuity errors : sum local = ([\deE+.-]+), global = ([\deE+.-]+), cumulative = ([\deE+.-]+)',body)
 iterations.append({'time':step,'equations':equations,'continuity':dict(zip(('sum_local','global','cumulative'),map(float,continuity[-1]))) if continuity else None,'execution_time_present':bool(re.search(r'(?m)^ExecutionTime =',body))})
times=[p.name for p in case.iterdir() if p.is_dir() and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',p.name)]
latest=max(times,key=float)
names=['run_status.json','run_manifest.json','execution.log','log.simpleFoam','log.checkMesh','system/controlDict','system/fvSchemes','system/fvSolution','constant/transportProperties','constant/turbulenceProperties','config.json','case_manifest.json']
names += [f'{latest}/{n}' for n in ['p','U','phi']]
names += [str(p.relative_to(case)) for p in (case/'constant/polyMesh').rglob('*') if p.is_file()]
names += [str(p.relative_to(case)) for p in (case/'VTK').rglob('*') if p.is_file()] if (case/'VTK').is_dir() else []
monitors={}
for p in sorted((case/'postProcessing').rglob('surfaceFieldValue.dat')):
 rel=str(p.relative_to(case));names.append(rel)
 rows=[[float(x) for x in line.split()] for line in p.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
 assert all(len(r)==2 and all(math.isfinite(x) for x in r) for r in rows)
 monitors[rel]=rows
small={p.name:json.loads(p.read_text()) for p in [case/'run_status.json',case/'run_manifest.json',root/'evaluation_001.json',root/'patient_trial_report.json'] if p.is_file()}
print(json.dumps({'native_root':str(root),'native_case':str(case),'latest_field_time':latest,'fields':sorted(times,key=float),'files':{n:digest(case/n) for n in names if (case/n).is_file()},'iterations':iterations,'monitors':monitors,'small':small,'End':bool(re.search(r'(?m)^End\s*$',log)),'SIMPLE_convergence':bool(re.search(r'SIMPLE solution converged',log)),'actual_signal_stack':bool(re.search(r'Foam::sigFpe::sigHandler|FOAM FATAL|Floating point exception \(core dumped\)',log)),'startup_trap_banner_present':'Floating point exception trapping enabled' in log,'mesh_failed_checks':[int(x) for x in re.findall(r'Failed\s+(\d+)\s+mesh checks', (case/'log.checkMesh').read_text())]},allow_nan=False))
'''


def native(job):
    return json.loads(subprocess.check_output(['wsl.exe', '-d', 'Ubuntu-22.04', '--', 'python3', '-c', READER, NATIVE + job], text=True, encoding='utf-8', timeout=90))


def main():
    local = json.loads((JOBS / JOB / 'job.json').read_text(encoding='utf-8'))
    assert local['id'] == JOB and local['case_id'] == 'b15_engineering_t029a'
    assert local['status'] in ('completed', 'failed', 'interrupted'), 'not terminal yet'
    current = native(JOB)
    old = native(OLD)
    exported = JOBS / JOB / 'export' / JOB / 'evaluations/eval_001'
    compared = {name: {'native': value, 'export': sha(exported / name)} for name, value in current['files'].items()}
    assert all(v['native'] == v['export'] for v in compared.values())
    assert current['mesh_failed_checks'] == old['mesh_failed_checks'] == [2]
    assert old['actual_signal_stack'] and old['startup_trap_banner_present']
    # Signal matching is source-backed. The startup trap banner is not a failure.
    assert current['startup_trap_banner_present']
    overlap = []
    by_old = {x['time']: x for x in old['iterations']}
    for item in current['iterations']:
        prior = by_old.get(item['time'])
        if prior and item['time'] in (20, 40, 60, 80, 100, 120):
            overlap.append({'time': item['time'], 'original_linearUpwind': prior, 'candidate_upwind': item})
    data = {
        'schema': 't023_t029_terminal_native_identity/v1',
        'at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'job': local, 'actual_native': current,
        'native_export_sha256': compared,
        'native_export_all_equal': True,
        'original_actual_signal_positive_control': {'job': OLD, 'signal_stack': old['actual_signal_stack'], 'last_started': old['iterations'][-1]['time'], 'log_sha256': old['files']['log.simpleFoam']},
        'same_step_bounded_comparison': overlap,
        'scope': 'Raw native/export provenance, started/completed step evidence and bounded same-step trend only; no convergence, target-flow, accuracy or clinical acceptance.',
        'script_sha256': sha(__file__),
        'no_POST_solver_service_or_monitor_launch': True,
    }
    with (HERE / 'terminal-native-identity.json').open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
    print(json.dumps({'status': local['status'], 'outer_exit': local.get('exit_code'), 'actual_commands': current['small']['run_manifest.json']['steps'], 'latest_field': current['latest_field_time'], 'End': current['End'], 'SIMPLE_convergence': current['SIMPLE_convergence'], 'real_signal_stack': current['actual_signal_stack'], 'native_export_equal_file_count': len(compared), 'mesh_failed_checks': current['mesh_failed_checks']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
