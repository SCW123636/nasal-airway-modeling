"""Record immutable source and controlled input identity before any trial POST."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
paths = ['work/lib/patient_cfd_admission.py', 'work/lib/patient_cfd_runner.py',
         'work/lib/openfoam_pressure_adapter.py', 'work/lib/pressure_feedback.py',
         'work/lib/solver_adapter.py', 'work/lib/cfd_contract.py',
         'work/07_cfd_pipeline/solver/run_openfoam_case.py',
         'work/07_cfd_pipeline/solver/mesh_cache.py',
         'work/07_cfd_pipeline/solver_reference/run_reference.py',
         'work/lib/test_patient_cfd_admission.py', 'work/lib/test_run_openfoam_case.py',
         'outputs/T-029/provision_b15_engineering_t029a.py']
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

path = OUT / 't029a_source_freeze.json'
data = {'schema':'nasal_t029_source_freeze/v1', 'frozen_at':datetime.now(timezone.utc).isoformat(),
        'parent_commit':subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'case_id':'b15_engineering_t029a', 'code_sha256':{p:digest(ROOT / p) for p in paths},
        'input_freeze_sha256':digest(OUT / 't029a_input_freeze.json'),
        'admission_sha256':digest(Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering_t029a/admission.json')),
        'known_answers':{'admission_executor_tests':36, 'adapter_controller_tests':46,
                         'new_provision_tests':2, 'actual_native_exit_fixtures':[-8,7]},
        'scope':'Engineering stability only; Failed 2 mesh checks and clinical pending retained. No automatic extension beyond 120.'}
if path.exists():
    old = json.loads(path.read_text(encoding='utf-8'))
    assert old['code_sha256'] == data['code_sha256'] and old['input_freeze_sha256'] == data['input_freeze_sha256'], 'frozen source/input changed'
    print(json.dumps({'existing_freeze_unchanged':True, 'source_freeze_sha256':digest(path)}))
else:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False))
