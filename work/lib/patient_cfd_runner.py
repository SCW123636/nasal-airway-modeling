"""Patient engineering run from a controlled, content-bound input package.

Outputs remain an unchecked engineering trial. No clinical approval is minted.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil

from openfoam_pressure_adapter import OpenFOAMPressureEvaluator, write_json, digest
from patient_cfd_admission import admission
from solver_adapter import CommonPressureAdapter


def run(folder, work_dir, source_binding=None, expected_admission_sha=None):
    folder, work_dir = Path(folder), Path(work_dir)
    work_dir.mkdir(parents=True,exist_ok=True)
    identity = folder.name
    eligible = admission(identity,folder.parent,source_binding)
    if not eligible['passed']:
        raise RuntimeError('patient engineering admission refused: ' + '; '.join(eligible['blocking_reasons']))
    if expected_admission_sha and digest(folder / 'admission.json') != expected_admission_sha:
        raise RuntimeError('admission changed after job submission')
    config = json.loads(Path(eligible['config_path']).read_text(encoding='utf-8'))
    template = Path(eligible['template'])
    target = config['boundary_conditions']['total_inspiratory_flow_m3_s']
    code_files = [Path(__file__).resolve(),Path(__file__).with_name('patient_cfd_admission.py'),
                  Path(__file__).with_name('solver_adapter.py'),Path(__file__).with_name('pressure_feedback.py'),
                  Path(__file__).with_name('openfoam_pressure_adapter.py')]
    frozen = {'admission_sha256':digest(folder / 'admission.json'),'config_sha256':digest(eligible['config_path']),
              'current_source_binding':source_binding,
              'code_sha256':{path.name:digest(path) for path in code_files}}
    fingerprint_path = work_dir / 'patient_input_fingerprint.json'
    if fingerprint_path.is_file() and json.loads(fingerprint_path.read_text()) != frozen:
        raise RuntimeError('patient input/code fingerprint changed; refusing resume without overwriting prior evidence')
    if not fingerprint_path.is_file():
        write_json(fingerprint_path,frozen)
    evaluator = OpenFOAMPressureEvaluator(template,work_dir / 'evaluations',
        rho=config['physics']['rho_kg_m3'],config=template / 'config.json',
        engineering_authorization=template / 'engineering_authorization.json')
    report = {'schema':'nasal_patient_engineering_trial/v1','case_id':identity,'patient_data':True,
              'engineering_trial':True,'backend':'real_openfoam_v1912','clinical_validation':'not_validated',
              'numerical_validation':'unchecked','execution_status':'running','scenario':{'result':None,'evaluations':[]},
              'target_m3_s':target,'initial_pressure_Pa':10.,
              'initial_pressure_basis':'Engineering initial guess only, from prior T-006 fixed-flow dP ~10.29Pa; not a new patient result',
              'clinical_readiness_reasons':eligible.get('clinical_readiness_reasons',[]),'input_fingerprint':frozen}
    write_json(work_dir / 'patient_engineering_report.json',report)
    try:
        controller = CommonPressureAdapter.from_config(config,evaluator,initial_pressure_pa=10.)
        report['scenario']['result'] = controller.run()
        report['execution_status'] = 'completed'
    except Exception as exc:
        report.update(execution_status='failed',error=str(exc),
                      interpretation='Raw engineering evidence only; rejected quality point was not used in feedback interpolation')
    finally:
        records = [json.loads(p.read_text()) for p in sorted((work_dir / 'evaluations').glob('evaluation_*.json'))]
        report['scenario']['evaluations'] = records
        if records and records[-1].get('diagnostics'):
            last = records[-1]
            report['diagnostics'] = last['diagnostics']
            if report['scenario']['result'] is None and last.get('evaluation'):
                value = last['evaluation']
                total = value['q_left_m3_s'] + value['q_right_m3_s']
                report['scenario']['result'] = {**value,'status':'quality_rejected_not_converged',
                    'target_m3_s':target,'q_total_m3_s':total,'left_fraction':value['q_left_m3_s']/total,
                    'relative_flow_error':abs(total-target)/target,'evaluation_count':len(records)}
        if digest(folder / 'admission.json') != frozen['admission_sha256']:
            report.update(execution_status='failed',error='admission changed during run')
        if {path.name:digest(path) for path in code_files} != frozen['code_sha256']:
            report.update(execution_status='failed',error='patient solver code dependencies changed during run')
        write_json(work_dir / 'patient_engineering_report.json',report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--patient-input',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path,required=True)
    parser.add_argument('--export-dir',type=Path,required=True)
    parser.add_argument('--source-binding',default=None)
    parser.add_argument('--expected-admission-sha',default=None)
    args = parser.parse_args(argv)
    status = 1
    try:
        report = run(args.patient_input,args.work_dir,json.loads(args.source_binding) if args.source_binding else None,args.expected_admission_sha)
        status = 0 if report['execution_status'] == 'completed' else 1
    finally:
        if args.work_dir.is_dir():
            shutil.copytree(args.work_dir,args.export_dir,dirs_exist_ok=True)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
