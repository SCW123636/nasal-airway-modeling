"""Real, resumable common-pressure evaluations in isolated native Linux cases.

The total flow remains an outer objective. Every PDE evaluation has two equal
static inlet pressures, a zero gauge outlet, and signed phi measurements.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from pressure_feedback import FlowEvaluation, PressureFeedbackError, signed_patch_fluxes
from solver_adapter import CommonPressureAdapter

ROOT = Path(__file__).resolve().parents[2]
SOLVER = ROOT / 'work/07_cfd_pipeline/solver/run_openfoam_case.py'
VERSION = '1.0.0'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def fingerprint(template):
    template = Path(template)
    files = sorted(p for folder in ('0', 'constant', 'system')
                   for p in (template / folder).rglob('*') if p.is_file())
    files += [p for p in (template / 'case_manifest.json', template / 'config.json') if p.is_file()]
    if not files:
        raise PressureFeedbackError('empty input case')
    return {'files': {p.relative_to(template).as_posix(): digest(p) for p in files},
            'solver_sha256': digest(SOLVER), 'adapter_sha256': digest(__file__),
            'controller_sha256': digest(Path(__file__).with_name('pressure_feedback.py'))}


def block_span(text, name):
    match = re.search(r'(?m)^\s*' + re.escape(name) + r'\s*\{', text)
    if not match:
        raise PressureFeedbackError('missing OpenFOAM block: ' + name)
    start = text.index('{', match.start())
    depth = 1
    end = start + 1
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    if depth:
        raise PressureFeedbackError('unbalanced OpenFOAM block: ' + name)
    return start, end


def replace_block(text, name, body):
    start, end = block_span(text, name)
    return text[:start] + '{\n' + body + '\n}' + text[end:]


def set_pressure_boundaries(case, pressure_pa, rho, inlets, outlet):
    if not math.isfinite(pressure_pa) or pressure_pa <= 0 or not math.isfinite(rho) or rho <= 0:
        raise PressureFeedbackError('pressure and rho must be finite and positive')
    pfile, ufile = case / '0/p', case / '0/U'
    p, u = pfile.read_text(), ufile.read_text()
    if not re.search(r'dimensions\s*\[\s*0\s+2\s+-2\s+0\s+0\s+0\s+0\s*\]', p):
        raise PressureFeedbackError('p must explicitly carry kinematic pressure dimensions')
    for name in inlets:
        p = replace_block(p, name, 'type fixedValue; value uniform %.16g;' % (pressure_pa / rho))
        u = replace_block(u, name, 'type pressureInletOutletVelocity; value uniform (0 0 0);')
    p = replace_block(p, outlet, 'type fixedValue; value uniform 0;')
    u = replace_block(u, outlet, 'type zeroGradient;')
    pfile.write_text(p, encoding='ascii')
    ufile.write_text(u, encoding='ascii')
    control_file = case / 'system/controlDict'
    control = control_file.read_text()
    functions = []
    for name in (*inlets, outlet):
        for label, operation, field in [('flow', 'sum', 'phi'), ('pressure', 'areaAverage', 'p')]:
            functions.append('''%s_%s
{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name %s;
 operation %s;
 fields (%s);
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}''' % (label, name, name, operation, field))
    control = replace_block(control, 'functions', '\n'.join(functions)) if re.search(r'\bfunctions\s*\{', control) else control + '\nfunctions\n{\n' + '\n'.join(functions) + '\n}\n'
    control = re.sub(r'\bstartFrom\s+\w+;', 'startFrom startTime;', control)
    control = re.sub(r'\bstartTime\s+[-+\d.eE]+;', 'startTime 0;', control)
    control_file.write_text(control, encoding='ascii')


def monitor_rows(case, name):
    files = list((case / 'postProcessing' / name).glob('*/surfaceFieldValue.dat'))
    if not files:
        raise PressureFeedbackError('missing signed flux/pressure monitor: ' + name)
    rows = []
    for path in sorted(files, key=lambda p: float(p.parent.name)):
        for line in path.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                row = [float(x) for x in line.split()]
                if len(row) != 2 or not all(math.isfinite(x) for x in row):
                    raise PressureFeedbackError('invalid monitor row: ' + str(path))
                rows.append(row)
    return rows


def solver_diagnostics(case, inlets, outlet, rho):
    log = (case / 'log.simpleFoam').read_text(errors='replace')
    mesh = (case / 'log.checkMesh').read_text(errors='replace')
    residuals, final_residuals = {}, {}
    for field, initial, final in re.findall(r'Solving for (\w+), Initial residual = ([\deE+.-]+), Final residual = ([\deE+.-]+)', log):
        residuals[field], final_residuals[field] = float(initial), float(final)
    if not {'p', 'Ux', 'Uy'}.issubset(residuals):
        raise PressureFeedbackError('missing solver equation residual evidence')
    continuity = re.findall(r'global = ([\deE+.-]+)', log)
    if not continuity or not math.isfinite(float(continuity[-1])):
        raise PressureFeedbackError('missing/nonfinite continuity evidence')
    flows = {name: monitor_rows(case, 'flow_' + name) for name in (*inlets, outlet)}
    if len({rows[-1][0] for rows in flows.values()}) != 1:
        raise PressureFeedbackError('patch monitors do not share final timestep')
    signed = {name: rows[-1][1] for name, rows in flows.items()}
    flux = signed_patch_fluxes(signed, list(inlets), [outlet])
    changes = []
    for rows in flows.values():
        if len(rows) < 20:
            raise PressureFeedbackError('monitor needs two complete ten-step windows')
        prior = sum(r[1] for r in rows[-20:-10]) / 10
        latest = sum(r[1] for r in rows[-10:]) / 10
        changes.append(abs(latest - prior) / max(abs(latest), 1e-30))
    pressure_rows = {name: monitor_rows(case, 'pressure_' + name) for name in (*inlets, outlet)}
    if len({tuple(r[0] for r in rows) for rows in pressure_rows.values()}) != 1:
        raise PressureFeedbackError('pressure monitors have mismatched time samples')
    # These fixedValue inlet pressures are equal by construction; their common
    # value equals the area-weighted mean, without assuming equal nostril areas.
    dp = [(pressure_rows[inlets[0]][i][1] - pressure_rows[outlet][i][1]) * rho
          for i in range(len(pressure_rows[outlet]))]
    tail = dp[int(len(dp) * .6):]
    windows = [sum(tail[i:i+20])/20 for i in range(0, len(tail)-19, 20)]
    if len(windows) < 2:
        raise PressureFeedbackError('dP monitor needs two twenty-sample windows in final forty percent')
    dp_change = max(abs(b-a)/max(abs(b),1e-30) for a,b in zip(windows,windows[1:]))
    pressure = {name: rows[-1][1] * rho for name,rows in pressure_rows.items()}
    return {'signed_phi_m3_s': signed, 'flux': flux, 'pressure_Pa_gauge': pressure,
            'initial_residuals': residuals, 'linear_final_residuals': final_residuals,
            'residual_max': max(residuals.values()), 'continuity_global': float(continuity[-1]),
            'monitor_relative_change': dp_change,
            'monitor_definition': 'T-008: dP final forty percent, consecutive nonoverlapping twenty-sample window means, maximum successive relative change',
            'flow_monitor_relative_change': max(changes),
            'flow_monitor_definition': 'reference-only per-patch ten-step mean signed phi change',
            'mesh_quality_passed': 'Mesh OK.' in mesh and not re.search(r'Failed\s+\d+\s+mesh checks', mesh),
            'solver_ended': bool(re.search(r'(?m)^End\s*$', log)) and 'FOAM FATAL' not in log,
            'SIMPLE_convergence_banner': 'SIMPLE solution converged' in log,
            'final_time': next(iter(re.findall(r'(?m)^Time = ([\deE+.-]+)', log)[-1:]), None)}


class OpenFOAMPressureEvaluator:
    """Callable used directly by CommonPressureAdapter, never a synthetic callback."""
    evaluation_backend = 'real_openfoam_v1912'

    def __init__(self, template, work_dir, rho=1.2, inlets=('nostril_L', 'nostril_R'),
                 outlet='nasopharynx_outlet', config=None, engineering_authorization=None):
        self.template, self.work_dir = Path(template).resolve(), Path(work_dir).resolve()
        if os.name != 'posix' or str(self.work_dir).startswith('/mnt/'):
            raise PressureFeedbackError('real evaluations require native Linux filesystem')
        if not self.work_dir.is_absolute() or not str(self.work_dir).isascii():
            raise PressureFeedbackError('native case path must be absolute ASCII')
        if len(inlets) != 2 or len(set((*inlets, outlet))) != 3 or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', n) for n in (*inlets, outlet)):
            raise PressureFeedbackError('requires two distinct inlet patches and one outlet')
        self.rho, self.inlets, self.outlet = float(rho), tuple(inlets), outlet
        self.config = Path(config) if config else None
        self.engineering_authorization = Path(engineering_authorization) if engineering_authorization else None
        self.fingerprint = fingerprint(self.template)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        bound = self.work_dir / 'input_fingerprint.json'
        if bound.is_file() and json.loads(bound.read_text()) != self.fingerprint:
            raise PressureFeedbackError('input/code fingerprint changed; refusing resume')
        write_json(bound, self.fingerprint)
        self.evaluations = []

    def __call__(self, pressure_pa):
        if fingerprint(self.template) != self.fingerprint:
            raise PressureFeedbackError('input/code fingerprint changed before evaluation')
        index = len(self.evaluations) + 1
        case = self.work_dir / ('eval_%03d' % index)
        record_path = self.work_dir / ('evaluation_%03d.json' % index)
        if record_path.is_file():
            cached = json.loads(record_path.read_text())
            if cached.get('status') != 'accepted' or cached.get('pressure_pa') != pressure_pa:
                raise PressureFeedbackError('existing evaluation failed or pressure differs; evidence preserved')
            self.evaluations.append(cached)
            return FlowEvaluation(**cached['evaluation'])
        if case.exists():
            raise PressureFeedbackError('incomplete evaluation exists; evidence preserved: ' + str(case))
        case.mkdir()
        record = {'schema': 'nasal_real_pressure_evaluation/v1', 'pressure_pa': pressure_pa,
                  'case': str(case), 'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
                  'backend': self.evaluation_backend, 'clinical_validation': 'not_validated'}
        write_json(record_path, record)
        try:
            for folder in ('0', 'constant', 'system'):
                shutil.copytree(self.template / folder, case / folder)
            for filename in ('case_manifest.json', 'config.json', 'engineering_authorization.json', 'engineering_authorization_record.md'):
                if (self.template / filename).is_file():
                    shutil.copy2(self.template / filename, case / filename)
            manifest_path = case / 'case_manifest.json'
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text())
                manifest['boundary'] = {'mode': 'common_inlet_pressure_feedback',
                                        'inlet_static_pressure_Pa_gauge': pressure_pa,
                                        'outlet_static_pressure_Pa_gauge': 0.,
                                        'target_role': 'outer_iteration_objective_not_simultaneous_PDE_flow_boundary'}
                write_json(manifest_path, manifest)
            set_pressure_boundaries(case, float(pressure_pa), self.rho, self.inlets, self.outlet)
            steps = ['checkMesh', 'simpleFoam', 'foamToVTK']
            if not (case / 'constant/polyMesh/points').is_file():
                steps.insert(0, 'blockMesh')
            command = [sys.executable, str(SOLVER), '--case', str(case), '--steps', ','.join(steps)]
            if self.config:
                command += ['--config', str(case / 'config.json')]
            if self.engineering_authorization:
                command += ['--engineering-authorization', str(case / 'engineering_authorization.json')]
            record['command'] = command
            write_json(record_path, record)
            with (case / 'execution.log').open('w') as output:
                process = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, env=os.environ.copy())
            record['exit_code'] = process.returncode
            write_json(record_path, record)
            if process.returncode:
                raise PressureFeedbackError('real solver failed, exit=' + str(process.returncode))
            manifest = json.loads((case / 'run_manifest.json').read_text())
            if manifest.get('execution_status') != 'completed' or any(r.get('exit_code') != 0 for r in manifest.get('steps', [])):
                raise PressureFeedbackError('run manifest is incomplete or contains failed command')
            diagnostics = solver_diagnostics(case, self.inlets, self.outlet, self.rho)
            record['diagnostics'] = diagnostics
            quality = diagnostics['solver_ended'] and diagnostics['residual_max'] <= 1e-5 and abs(diagnostics['continuity_global']) <= 1e-6 and diagnostics['monitor_relative_change'] <= .005
            flux = diagnostics['flux']
            evaluation = FlowEvaluation(float(pressure_pa), flux['q_in_by_patch'][self.inlets[0]],
                                        flux['q_in_by_patch'][self.inlets[1]], flux['q_out_m3_s'],
                                        converged=quality, mesh_quality_passed=diagnostics['mesh_quality_passed'],
                                        mass_imbalance_frac=flux['mass_imbalance_frac'], residuals_passed=quality)
            record['evaluation'] = asdict(evaluation)
            evaluation.validate(1., .005)
            if fingerprint(self.template) != self.fingerprint:
                raise PressureFeedbackError('input/code fingerprint changed during run')
            record['status'] = 'accepted'
            write_json(record_path, record)
            self.evaluations.append(record)
            print(json.dumps({'event': 'pressure_evaluation', 'case': str(case), 'pressure_pa': pressure_pa,
                              'q_total_m3_s': evaluation.q_total_m3_s}), flush=True)
            return evaluation
        except Exception as exc:
            record.update(status='failed', error=str(exc))
            write_json(record_path, record)
            raise


def run_split_suite(work_dir, scenarios):
    from structured_split_feedback import write_case, TARGET_M3_S
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    reports = {}
    definitions = {'unequal': (2., 1., False), 'symmetric': (1.5, 1.5, False), 'swapped_labels': (2., 1., True)}
    for name in scenarios:
        base = work_dir / name
        template = base / 'template'
        if not template.exists():
            write_case(template, 1., *definitions[name])
        evaluator = OpenFOAMPressureEvaluator(template, base / 'evaluations', inlets=('inlet_L', 'inlet_R'), outlet='outlet')
        adapter = CommonPressureAdapter(evaluator, target_m3_s=TARGET_M3_S, inlet_patches=('inlet_L','inlet_R'), outlet_patches=('outlet',), max_iterations=12)
        result = adapter.run()
        report = {'scenario': name, 'patient_data': False, 'result': result, 'evaluations': evaluator.evaluations,
                  'clinical_validation': 'not_validated', 'numerical_validation': 'unchecked'}
        write_json(base / 'feedback_report.json', report)
        reports[name] = report
    checks = {'all_converged': all(r['result']['status'] == 'converged' for r in reports.values())}
    if 'unequal' in reports:
        checks['unequal_not_half'] = abs(reports['unequal']['result']['left_fraction'] - .5) > .1
    if 'symmetric' in reports:
        checks['symmetric_near_half'] = abs(reports['symmetric']['result']['left_fraction'] - .5) <= .02
    if {'unequal', 'swapped_labels'} <= reports.keys():
        checks['swapped_complements'] = abs(reports['unequal']['result']['left_fraction'] + reports['swapped_labels']['result']['left_fraction'] - 1.) <= .02
    summary = {'schema': 'nasal_real_pressure_feedback_suite/v1', 'patient_data': False,
               'execution_status': 'completed' if all(checks.values()) else 'failed',
               'scenarios': reports, 'checks': checks, 'clinical_validation': 'not_validated',
               'numerical_validation': 'unchecked', 'backend': 'real_openfoam_v1912'}
    write_json(work_dir / 'feedback_suite_report.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--scenarios', nargs='+', choices=['unequal', 'symmetric', 'swapped_labels'], default=['unequal', 'symmetric', 'swapped_labels'])
    parser.add_argument('--export-dir', type=Path)
    args = parser.parse_args(argv)
    status = 1
    try:
        result = run_split_suite(args.work_dir, args.scenarios)
        status = 0 if result['execution_status'] == 'completed' else 1
    finally:
        if args.export_dir and args.work_dir.is_dir():
            shutil.copytree(args.work_dir, args.export_dir, dirs_exist_ok=True)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
