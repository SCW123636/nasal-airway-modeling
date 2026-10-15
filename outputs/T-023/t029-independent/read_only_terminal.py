"""Read-only reconstruction of actually executed CFD steps, not numerical acceptance.

No production imports, HTTP, WSL, process launch, watch loop or solver invocation.
Source files are read only; JSON output must be a new file inside this directory.
The old T023 watcher and its failed audit are deliberately outside this module.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
JOBS = Path('C:/ts_work/project_cases/simulation_jobs')
SUCCESS_JOB = 's_1811f735241e4d75b5fdf10e'
FAILED_JOB = 's_942fdbebfffd433c8fcec956'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_once(path: Path, value):
    path = path.resolve()
    if not path.is_relative_to(HERE):
        raise ValueError('Evidence output must stay in T023/t029-independent')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def step_name(item):
    command = item.get('command')
    assert isinstance(command, list) and command and isinstance(command[0], str)
    return command[0].rsplit('/', 1)[-1]


def raw_execution(text):
    records = []
    for line in text.splitlines():
        if not line.lstrip().startswith('{'):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and 'command' in value and 'exit_code' in value:
            assert isinstance(value['exit_code'], int)
            step_name(value)
            records.append(value)
    return records


def reconcile(plan, raw, manifest, status, *, require_failed_step=False):
    """Plan is an expected order; a failed command stops its remaining suffix."""
    assert plan and len(plan) == len(set(plan)), 'invalid planned step list'
    assert raw, 'no raw executed commands: cannot reconstruct terminal execution'
    names = [step_name(item) for item in raw]
    assert names == plan[:len(names)], ('unexpected/duplicate/out-of-order execution', names, plan)
    failed = [i for i, item in enumerate(raw) if item['exit_code'] != 0]
    assert len(failed) <= 1 and (not failed or failed[0] == len(raw)-1), 'execution continued after failure'
    mn = [step_name(item) for item in manifest['steps']]
    assert mn == names[:len(mn)], ('manifest contains an unexecuted step or wrong order', mn, names)
    for i, item in enumerate(manifest['steps']):
        assert item['exit_code'] == raw[i]['exit_code'], 'manifest/raw exit code disagreement'
        assert item['command'] == raw[i]['command'], 'manifest/raw command disagreement'
        assert item['log'] == raw[i]['log'], 'manifest/raw log identity disagreement'
    legacy_missing = False
    if failed:
        assert manifest['execution_status'] == status['status'] == 'failed'
        assert len(mn) in (len(names)-1, len(names)), 'manifest omits successful raw commands'
        legacy_missing = len(mn) != len(names)
        if require_failed_step:
            assert not legacy_missing, 'new runner must record the failed command and its real exit code'
    else:
        assert len(raw) == len(plan), 'terminal success lacks a planned command'
        assert manifest['execution_status'] == status['status'] == 'completed'
        assert len(mn) == len(names), 'completed manifest lacks executed commands'
    return {
        'actual_steps': [{'command': x['command'], 'exit_code': x['exit_code'], 'log': x['log']} for x in raw],
        'planned_steps': plan,
        'not_executed_steps': plan[len(names):],
        'failed_command': names[-1] if failed else None,
        'raw_failed_exit_code': raw[-1]['exit_code'] if failed else None,
        'execution_reconstructed': True,
        'legacy_failed_step_missing_from_manifest': legacy_missing,
        'new_failed_step_recording_required': require_failed_step,
        'manifest_execution_status': manifest['execution_status'],
    }


def audit_case(case: Path, plan, *, require_failed_step=False):
    manifest = read(case/'run_manifest.json')
    status = read(case/'run_status.json')
    assert manifest['case'] == status['case'], 'case identity mismatch'
    raw = raw_execution((case/'execution.log').read_text(encoding='utf-8'))
    result = reconcile(plan, raw, manifest, status, require_failed_step=require_failed_step)
    result.update(source_case=str(case.resolve()), native_case=manifest['case'])
    hashes = {name: sha(case/name) for name in ['run_manifest.json', 'run_status.json', 'execution.log']}
    for item in raw:
        log = case/Path(item['log']).name
        assert log.is_file(), ('executed command lacks its original log', item)
        hashes[log.name] = sha(log)
    solver = (case/'log.simpleFoam').read_text(encoding='utf-8') if (case/'log.simpleFoam').exists() else ''
    times = re.findall(r'(?m)^Time = (\S+)\s*$', solver)
    numeric_times = [float(value) for value in times]
    assert all(math.isfinite(value) for value in numeric_times), 'nonfinite iteration marker'
    assert all(b > a for a, b in zip(numeric_times, numeric_times[1:])), 'iteration restart/duplicate'
    ended = bool(re.search(r'(?m)^End\s*$', solver))
    converged = bool(re.search(r'SIMPLE solution converged', solver))
    vtk = sorted(str(p.relative_to(case)).replace('\\', '/') for p in (case/'VTK').rglob('internal.vtu')) if (case/'VTK').exists() else []
    fields = sorted((p.name for p in case.iterdir() if p.is_dir() and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', p.name)), key=float)
    if result['failed_command']:
        assert 'foamToVTK' in result['not_executed_steps'], 'failed baseline unexpectedly ran exporter'
        assert not (case/'log.foamToVTK').exists() and not vtk, 'unexecuted exporter has current output'
        if result['failed_command'] == 'simpleFoam':
            assert not ended and not converged, 'failed solver claims normal terminal completion'
    elif 'simpleFoam' in plan:
        assert ended, 'zero-exit solver is missing End'
        assert times, 'completed solver has no actual iteration'
        assert all((case/times[-1]/name).is_file() for name in ['p', 'U', 'phi']), 'final raw fields missing'
        assert len(vtk) == 1, 'completed conversion lacks one actual internal VTU'
        for name in ['p', 'U', 'phi']:
            hashes[f'{times[-1]}/{name}'] = sha(case/times[-1]/name)
        hashes[vtk[0]] = sha(case/vtk[0])
    mesh = (case/'log.checkMesh').read_text(encoding='utf-8') if (case/'log.checkMesh').exists() else ''
    result.update(
        last_started_iteration=times[-1] if times else None,
        last_started_is_not_asserted_completed=True,
        solver_End=ended, SIMPLE_convergence_banner=converged,
        numeric_field_directories=fields, internal_vtu_paths=vtk,
        mesh_failed_checks=[int(n) for n in re.findall(r'Failed\s+(\d+)\s+mesh checks', mesh)],
        source_file_sha256=hashes,
        patient_numerical_accepted=False,
        scope='Read-only execution/absence/identity evidence; no convergence, patient target, clinical or Lead status grant',
    )
    return result, (plan, raw, manifest, status)


def calibration():
    """Source-backed controls: four real completed evaluations and real b15 FPE."""
    result = {'schema': 't023_terminal_checker_calibration/v1', 'at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'checker_sha256': sha(Path(__file__)), 'controls': [], 'mutation_rejections': []}
    success = JOBS/SUCCESS_JOB/'export'/SUCCESS_JOB/'symmetric/evaluations'
    for number in range(1, 5):
        item, _ = audit_case(success/f'eval_{number:03}', ['blockMesh','checkMesh','simpleFoam','foamToVTK'])
        assert [x['exit_code'] for x in item['actual_steps']] == [0,0,0,0]
        assert not item['not_executed_steps'] and item['solver_End'] and item['SIMPLE_convergence_banner']
        item['control_origin'] = {'job_id': SUCCESS_JOB, 'evaluation': f'eval_{number:03}', 'patient_data': False}
        result['controls'].append(item)
    failed = JOBS/FAILED_JOB/'export'/FAILED_JOB/'evaluations/eval_001'
    item, inputs = audit_case(failed, ['checkMesh','simpleFoam','foamToVTK'])
    assert [x['exit_code'] for x in item['actual_steps']] == [0,-8]
    assert item['not_executed_steps'] == ['foamToVTK'] and item['last_started_iteration'] == '223'
    assert item['numeric_field_directories'] == ['0','200'] and item['mesh_failed_checks'] == [2]
    assert item['legacy_failed_step_missing_from_manifest'] and not item['internal_vtu_paths']
    item['control_origin'] = {'job_id': FAILED_JOB, 'evaluation': 'eval_001', 'patient_data': True, 'actual_patient_execution': 'failed'}
    result['controls'].append(item)

    def rejects(name, change, require_failed_step=False):
        args = copy.deepcopy(inputs)
        change(args)
        try:
            reconcile(*args, require_failed_step=require_failed_step)
        except AssertionError as exc:
            result['mutation_rejections'].append({'name': name, 'rejected': True, 'reason': str(exc)})
        else:
            raise AssertionError('Mutated evidence was incorrectly accepted: '+name)

    rejects('false_completed_status_on_actual_failure', lambda x: (x[2].update(execution_status='completed'), x[3].update(status='completed')))
    rejects('fabricated_post_failure_export_step', lambda x: x[1].append({'command':['foamToVTK'],'exit_code':0,'log':'fabricated'}))
    rejects('manifest_exit_code_disagrees_with_raw', lambda x: x[2]['steps'][0].update(exit_code=99))
    rejects('omitted_successful_raw_step', lambda x: x[2].update(steps=[]))
    rejects('new_runner_cannot_omit_failed_step', lambda x: None, require_failed_step=True)
    protected = read(PROJECT/'outputs/T-023/patient-terminal-failure-review/final-integrity.json')['protected_hashes_still_equal_after_UI']
    result['protected_originals_unchanged'] = {path: sha(Path(path)) == expected for path, expected in protected.items()}
    assert all(result['protected_originals_unchanged'].values())
    result['calibration_passed'] = True
    result['current_t029_job_bound'] = False
    result['monitor_started'] = False
    result['patient_numerical_accepted'] = False
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--calibrate', action='store_true')
    mode.add_argument('--audit-case', type=Path)
    parser.add_argument('--steps')
    parser.add_argument('--require-failed-step', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.calibrate:
        value = calibration()
    else:
        assert args.steps, '--steps required for a specific case'
        value, _ = audit_case(args.audit_case, args.steps.split(','), require_failed_step=args.require_failed_step)
    write_once(args.output, value)
    print(json.dumps({'output': str(args.output.resolve()), 'calibration_passed': value.get('calibration_passed'),
                      'execution_reconstructed': value.get('execution_reconstructed'), 'patient_numerical_accepted': False}, ensure_ascii=False))
