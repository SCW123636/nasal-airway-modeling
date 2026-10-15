"""Provision the B zero-CPU candidate from immutable A, with one scheme change."""
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

ORIGIN = 'b15_engineering_t029a'
CASE_ID = 'b15_engineering_t029b'
SOURCE = Path('C:/ts_work/project_cases/patient_cfd_inputs') / ORIGIN
TARGET = SOURCE.with_name(CASE_ID)
OLD_LAPLACIAN = 'default Gauss linear corrected;'
NEW_LAPLACIAN = 'default Gauss linear limited corrected 0.5;'


def single_replacement(text, old, new):
    if text.count(old) != 1:
        raise ValueError('expected exactly one frozen default laplacian entry')
    return text.replace(old, new)


def tree_identity(root):
    return {p.relative_to(root).as_posix(): sha256(p) for p in sorted(root.rglob('*')) if p.is_file()}


def provision(source=SOURCE, target=TARGET, evidence=ROOT / 'outputs/T-029'):
    source, target, evidence = Path(source), Path(target), Path(evidence)
    if source.name != ORIGIN or target.name != CASE_ID or source.parent != target.parent:
        raise ValueError('explicit A origin/B versioned identity and shared controlled root required')
    if target.exists():
        raise FileExistsError('versioned B input already exists; preserve it')
    before = tree_identity(source)
    source_admission = admission(ORIGIN, source.parent)
    if not source_admission['passed']:
        raise ValueError('A source package failed admission: ' + repr(source_admission['blocking_reasons']))
    source_template = source / 'template'
    schemes = single_replacement((source_template / 'system/fvSchemes').read_text(encoding='ascii'), OLD_LAPLACIAN, NEW_LAPLACIAN)
    if 'default corrected;' not in (source_template / 'system/fvSchemes').read_text(encoding='ascii'):
        raise ValueError('A source snGrad default is not corrected')
    target.mkdir()
    shutil.copytree(source_template, target / 'template')
    shutil.copytree(source / 'sources', target / 'sources')
    shutil.copy2(source / 'checkMesh.log', target / 'checkMesh.log')
    (target / 'template/system/fvSchemes').write_text(schemes, encoding='ascii')
    provenance = engineering_provenance(CASE_ID)
    config_path = target / 'template/config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    config.update(config_id='b15_engineering_t029b_upwind_limitedSnGrad05', engineering_provenance=provenance)
    config['geometry']['case_id'] = CASE_ID
    config['numerical_trial'] = {
        'task': 'T-029', 'base_version': 't029a', 'U_convection': 'bounded Gauss upwind',
        'laplacian_default': 'Gauss linear limited corrected 0.5', 'snGrad_default': 'corrected',
        'endTime': 120, 'writeInterval': 20,
        'meaning': 'bounded engineering stability candidate; not convergence or accuracy validation',
        'status': 'prepared_zero_cpu_no_post',
    }
    config['notes'] += [
        'T-029b candidate: retains A upwind and changes only default laplacian to limited corrected 0.5.',
        'The independent snGrad default remains corrected; no flow, pressure, mesh, physical, relaxation or quality gate changes.',
        'T024 viewer repair 421fc31 is required before formal production source freeze; no POST is authorized by this generator.',
    ]
    write_json(config_path, config)
    manifest_path = target / 'template/case_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest.update(patient_case_id=CASE_ID, engineering_provenance=provenance,
                    engineering_input_provenance='T-029b candidate: version of frozen b15_engineering_t029a; only scheme/identity records changed')
    write_json(manifest_path, manifest)
    record = target / 'template/engineering_authorization_record.md'
    record.write_text(
        '# T-029b zero-CPU candidate authorization\n\n'
        'Base: b15_engineering_t029a (A), which retains the frozen b15 geometry, mesh, pressure adapter, and upwind U convection.\n'
        'Candidate sole numerical change: laplacianSchemes.default from Gauss linear corrected to Gauss linear limited corrected 0.5.\n'
        'snGradSchemes.default remains corrected; nNonOrthogonalCorrectors, pressure/momentum settings, physical parameters, mesh, boundaries and gates remain.\n'
        'OpenFOAM v1912 exact source evidence: limitedSnGrad limits the explicit non-orthogonal correction; coefficient 0.5 limits that contribution so it does not exceed the orthogonal part. It is not a blanket 0.5 multiplier.\n'
        'This is a zero-CPU candidate only. T024 viewer repair commit 421fc31 is bound for the next production source freeze; no POST or solver execution is authorized here.\n'
        'Clinical validation remains not_validated and Failed 2 mesh checks remain.\n', encoding='utf-8')
    authority_path = target / 'template/engineering_authorization.json'
    authority = json.loads(authority_path.read_text(encoding='utf-8'))
    authority.update(case_id=CASE_ID, engineering_provenance=provenance, config_sha256=sha256(config_path),
                     record_sha256=sha256(record), source_record='tasks/T-029.md Lead authorized B zero-CPU candidate preparation on 2026-10-15')
    write_json(authority_path, authority)
    admission_data = json.loads((source / 'admission.json').read_text(encoding='utf-8'))
    admission_data.update(case_id=CASE_ID, engineering_provenance=provenance,
                          config_sha256=sha256(config_path), current_source_binding={'kind':'frozen_standalone_sample','sample_id':CASE_ID},
                          engineering_authorization=dict(authority, record_file='template/' + record.name))
    write_json(target / 'admission.json', admission_data)
    result = admission(CASE_ID, target.parent)
    authorization = validate_engineering_authorization(target / 'template', config_path, authority_path)
    assert result['passed'], result
    assert authorization['allowed']
    assert mesh_fingerprint(target / 'template') == admission_data['mesh_fingerprint'] == mesh_fingerprint(source_template)
    assert tree_identity(source) == before, 'A package changed while provisioning B'
    target_identity = tree_identity(target)
    changed = sorted(name for name, value in before.items() if target_identity.get(name) != value)
    expected = ['admission.json', 'template/case_manifest.json', 'template/config.json',
                'template/engineering_authorization.json', 'template/engineering_authorization_record.md',
                'template/system/fvSchemes']
    assert changed == expected and before.keys() == target_identity.keys(), changed
    frozen = {
        'schema': 'nasal_t029b_input_candidate/v1', 'case_id': CASE_ID, 'base_case_id': ORIGIN,
        'engineering_provenance': provenance, 'source_a_unchanged': True, 'source_a_files': before,
        'candidate_files': target_identity, 'changed_files': changed,
        'numerical_change': {'old': OLD_LAPLACIAN, 'new': NEW_LAPLACIAN, 'snGrad_default': 'corrected'},
        'retained_a_change': {'div(phi,U)': 'bounded Gauss upwind'},
        'retained_run_controls': {'endTime': 120, 'writeInterval': 20},
        'mesh_unchanged': True, 'surface_unchanged': True, 'clinical_validation': 'not_validated',
        'status': 'prepared_zero_cpu_no_post',
    }
    write_json(evidence / 't029b_input_candidate.json', frozen)
    write_json(evidence / 't029b_admission.json', result)
    return {'passed': True, 'case_id': CASE_ID, 'folder': str(target), 'changed_files': changed,
            'status': frozen['status']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--target', type=Path, default=TARGET)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'outputs/T-029')
    args = parser.parse_args()
    print(json.dumps(provision(args.source, args.target, args.evidence), ensure_ascii=False))
