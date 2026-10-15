"""Read-only evidence freeze. Does not invoke WSL commands or any solver."""
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = Path(r'\\wsl.localhost\Ubuntu-22.04\home\lenovo2')
FAILED = BASE / 'nasal_cfd_workspace_jobs/s_942fdbebfffd433c8fcec956/evaluations/eval_001'
STABLE = BASE / 'patient_cfd/t004_diag'


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha(destination) != sha(source):
        raise RuntimeError('Existing evidence differs: ' + str(destination))
    if not destination.exists():
        shutil.copy2(source, destination)
    return {'source': str(source), 'sha256': sha(source), 'bytes': source.stat().st_size}


def main():
    files = ['0/p', '0/U', 'system/fvSchemes', 'system/fvSolution', 'system/controlDict',
             'constant/transportProperties', 'constant/turbulenceProperties', 'constant/polyMesh/boundary',
             'case_manifest.json', 'config.json', 'engineering_authorization.json',
             'engineering_authorization_record.md', 'run_manifest.json', 'run_status.json',
             'log.checkMesh', 'log.simpleFoam', 'execution.log']
    record = {'schema': 't029_failed_input_evidence/v1', 'failed': {}, 'stable': {},
              'native_case': '/home/lenovo2/nasal_cfd_workspace_jobs/s_942fdbebfffd433c8fcec956/evaluations/eval_001',
              'solver_or_checkmesh_invoked': False}
    for name in files:
        record['failed'][name] = copy(FAILED / name, OUT / 'failed_actual' / name)
    for path in sorted((FAILED / 'postProcessing').rglob('surfaceFieldValue.dat')):
        name = path.relative_to(FAILED).as_posix()
        record['failed'][name] = copy(path, OUT / 'failed_actual' / name)
    for name in ['0/p', '0/U', 'system/fvSchemes', 'system/fvSolution', 'system/controlDict',
                 'constant/transportProperties', 'constant/turbulenceProperties',
                 'log.simpleFoam.part1_T533']:
        record['stable'][name] = copy(STABLE / name, OUT / 't006_actual' / name)
    for name in ['input_fingerprint.json', 'evaluation_001.json']:
        copy(FAILED.parent / name, OUT / 'failed_actual' / name)
    copy(FAILED.parent.parent / 'patient_input_fingerprint.json',
         OUT / 'failed_actual/patient_input_fingerprint.json')
    previous = json.loads((FAILED.parent / 'input_fingerprint.json').read_text())
    actual_mesh = {path.relative_to(FAILED).as_posix(): sha(path)
                   for path in sorted((FAILED / 'constant/polyMesh').rglob('*')) if path.is_file()}
    record['actual_mesh_sha256'] = actual_mesh
    record['mesh_matches_recorded_input'] = all(previous['files'].get(name) == value
                                                for name, value in actual_mesh.items())
    record['numerical_templates_byte_identical_to_t006'] = {
        name: sha(FAILED / name) == sha(STABLE / name)
        for name in ['system/fvSchemes', 'system/fvSolution', 'constant/transportProperties',
                     'constant/turbulenceProperties']}
    code = ['work/lib/openfoam_pressure_adapter.py', 'work/lib/patient_cfd_runner.py',
            'work/07_cfd_pipeline/solver/run_openfoam_case.py', 'work/lib/pressure_feedback.py']
    record['current_source_sha256'] = {name: sha(ROOT / name) for name in code}
    record['recorded_adapter_sha256'] = previous['adapter_sha256']
    record['recorded_runner_sha256'] = previous['solver_sha256']
    record['current_adapter_matches_failure'] = record['current_source_sha256'][code[0]] == previous['adapter_sha256']
    record['current_runner_matches_failure'] = record['current_source_sha256'][code[2]] == previous['solver_sha256']
    record['runtime_time_200'] = {}
    for name in ['p', 'U', 'phi']:
        path = FAILED / '200' / name
        with path.open('rb') as stream:
            head = stream.read(4096).decode('ascii', errors='replace')
            stream.seek(max(0, path.stat().st_size - 4 * 1024 * 1024))
            tail = stream.read().decode('ascii', errors='replace')
        start = tail.find('boundaryField')
        boundary = tail[start:] if start >= 0 else None
        metadata = {'bytes': path.stat().st_size,
                    'dimensions': re.search(r'dimensions\s*([^;]+);', head).group(1),
                    'boundary_found_in_last_4MiB': boundary is not None}
        if boundary is not None:
            target = OUT / 'runtime200_boundary' / (name + '.txt')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(boundary, encoding='ascii')
            metadata['boundary_sha256'] = sha(target)
        record['runtime_time_200'][name] = metadata
    record['all_frozen_checks_passed'] = (record['mesh_matches_recorded_input']
        and all(record['numerical_templates_byte_identical_to_t006'].values())
        and record['current_adapter_matches_failure'] and record['current_runner_matches_failure'])
    (OUT / 'failed_input_identity.json').write_text(json.dumps(record, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in record.items() if key not in ('failed', 'stable', 'actual_mesh_sha256')}, ensure_ascii=False))
    assert record['all_frozen_checks_passed']


if __name__ == '__main__':
    main()
