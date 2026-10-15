"""Create a distinct bounded U-upwind trial; never modify the original package."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'work/lib'))
from patient_cfd_admission import admission, engineering_provenance, mesh_fingerprint, sha256, validate_engineering_authorization
from ct_case_pipeline import write_json

ORIGIN = 'b15_engineering'
CASE_ID = 'b15_engineering_t029a'
SOURCE = Path('C:/ts_work/project_cases/patient_cfd_inputs') / ORIGIN
TARGET = SOURCE.with_name(CASE_ID)
OLD_SCHEME = 'div(phi,U) bounded Gauss linearUpwind grad(U);'
NEW_SCHEME = 'div(phi,U) bounded Gauss upwind;'


def single_replacement(text, old, new):
    if text.count(old) != 1:
        raise ValueError('expected exactly one frozen U convection entry')
    return text.replace(old, new)


def budget_controls(text):
    for key, old, new in (('endTime', '1500', '120'), ('writeInterval', '200', '20')):
        pattern = rf'(?m)^{key}\s+{old};'
        text, count = re.subn(pattern, f'{key} {new};', text)
        if count != 1:
            raise ValueError('unexpected frozen top-level run budget: ' + key)
    return text


def tree_identity(root):
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob('*')) if p.is_file()}


def provision(source=SOURCE, target=TARGET, evidence=ROOT / 'outputs/T-029'):
    source, target, evidence = Path(source), Path(target), Path(evidence)
    if source.name != ORIGIN or target.name != CASE_ID or source.parent != target.parent:
        raise ValueError('explicit original/versioned identity and shared controlled root required')
    if target.exists():
        raise FileExistsError('versioned input already exists; preserve it')
    before = tree_identity(source)
    original_admission = admission(ORIGIN, source.parent)
    if not original_admission['passed']:
        raise ValueError('original frozen package failed admission: ' + repr(original_admission['blocking_reasons']))
    old_template = source / 'template'
    schemes = single_replacement((old_template / 'system/fvSchemes').read_text(), OLD_SCHEME, NEW_SCHEME)
    controls = budget_controls((old_template / 'system/controlDict').read_text())
    if {p.name for p in old_template.iterdir() if p.is_dir()} != {'0', 'constant', 'system'}:
        raise ValueError('original template contains non-input directories')
    target.mkdir()
    template = target / 'template'
    shutil.copytree(old_template, template)
    shutil.copytree(source / 'sources', target / 'sources')
    shutil.copy2(source / 'checkMesh.log', target / 'checkMesh.log')
    (template / 'system/fvSchemes').write_text(schemes, encoding='ascii')
    (template / 'system/controlDict').write_text(controls, encoding='ascii')
    provenance = engineering_provenance(CASE_ID)
    config_path = template / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    config.update(config_id='b15_engineering_t029a_upwind_120', engineering_provenance=provenance,
                  numerical_trial={'task':'T-029', 'U_convection':'bounded Gauss upwind',
                                   'endTime':120, 'writeInterval':20,
                                   'meaning':'bounded engineering stability trial; not convergence or accuracy validation'})
    config['geometry']['case_id'] = CASE_ID
    config['notes'] += ['T-029: same b15 geometry/mesh/physical and quality settings; only U convection changed to upwind.',
                        '120-step budget and 20-step field writes are run controls. No automatic extension to 300.',
                        '10 Pa common nostril static pressure is the first outer evaluation; no fixed flow split is imposed.']
    write_json(config_path, config)
    manifest_path = template / 'case_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest.update(patient_case_id=CASE_ID, engineering_provenance=provenance,
                    engineering_input_provenance='T-029 numerical version of frozen b15_engineering; only input folders copied; old results excluded')
    write_json(manifest_path, manifest)
    record = template / 'engineering_authorization_record.md'
    record.write_text('# T-029 bounded engineering trial authorization\n\n'
        'Source: tasks/T-029.md Lead execution record, approved on 2026-10-15; original M1/M2 engineering authorization retained.\n'
        'Origin b15_engineering; new numerical trial identity b15_engineering_t029a. Original geometry, mesh, source hashes and clinical review pending status remain.\n'
        'Approved sole numerical variable: div(phi,U) bounded Gauss upwind. All pressure boundaries, units, rho/nu, laminar model, relaxation and quality gates remain.\n'
        'Execution budget: endTime 120, writeInterval 20; stop on FPE/nonfinite values or this bound, no automatic continuation.\n'
        'Formal 8769 creates one new isolated native-Linux job after source/input freeze and CPU-lane check.\n'
        'This authorizes an engineering stability observation only; Failed 2 mesh checks, no patient clinical approval, no asserted target flow or split.\n', encoding='utf-8')
    data = json.loads((source / 'admission.json').read_text(encoding='utf-8'))
    authority = json.loads((template / 'engineering_authorization.json').read_text(encoding='utf-8'))
    authority.update(case_id=CASE_ID, engineering_provenance=provenance, config_sha256=sha256(config_path),
                     record_sha256=sha256(record), source_record='tasks/T-029.md Lead authorized bounded single-variable engineering trial on 2026-10-15')
    write_json(template / 'engineering_authorization.json', authority)
    data.update(case_id=CASE_ID, engineering_provenance=provenance, config_sha256=sha256(config_path),
                current_source_binding={'kind':'frozen_standalone_sample', 'sample_id':CASE_ID},
                engineering_authorization=dict(authority, record_file='template/' + record.name))
    write_json(target / 'admission.json', data)
    result = admission(CASE_ID, target.parent)
    authorization = validate_engineering_authorization(template, config_path, template / 'engineering_authorization.json')
    assert result['passed'], result
    assert authorization['allowed']
    assert mesh_fingerprint(template) == data['mesh_fingerprint'] == mesh_fingerprint(old_template)
    after = tree_identity(source)
    assert after == before, 'original package changed during provisioning'
    target_identity = tree_identity(target)
    changed = sorted(name for name, value in before.items() if target_identity.get(name) != value)
    expected = ['admission.json', 'template/case_manifest.json', 'template/config.json',
                'template/engineering_authorization.json', 'template/engineering_authorization_record.md',
                'template/system/controlDict', 'template/system/fvSchemes']
    assert changed == expected and before.keys() == target_identity.keys(), changed
    evidence.mkdir(parents=True, exist_ok=True)
    frozen = {'schema':'nasal_t029_input_freeze/v1', 'case_id':CASE_ID, 'engineering_provenance':provenance,
              'original_package_unchanged':True, 'original_files':before, 'trial_files':target_identity,
              'changed_files':changed, 'numerical_change':{'old':OLD_SCHEME, 'new':NEW_SCHEME},
              'run_control_changes':{'endTime':[1500,120], 'writeInterval':[200,20]},
              'mesh_unchanged':True, 'surface_unchanged':True, 'clinical_validation':'not_validated'}
    write_json(evidence / 't029a_input_freeze.json', frozen)
    write_json(evidence / 't029a_admission.json', result)
    return {'passed':True, 'case_id':CASE_ID, 'folder':str(target), 'changed_files':changed}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--target', type=Path, default=TARGET)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'outputs/T-029')
    args = parser.parse_args()
    print(json.dumps(provision(args.source, args.target, args.evidence), ensure_ascii=False))
