"""Expand the previous immutable freeze to the approved manager dependency."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

previous = OUT / 't029a_source_freeze.json'
old = json.loads(previous.read_text(encoding='utf-8'))
for name, expected in old['code_sha256'].items():
    assert digest(ROOT / name) == expected, 'old frozen dependency changed: ' + name
assert digest(OUT / 't029a_input_freeze.json') == old['input_freeze_sha256']
assert digest(Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering_t029a/admission.json')) == old['admission_sha256']
paths = ['work/lib/cfd_workspace_jobs.py', 'work/lib/test_cfd_workspace_jobs.py', 'work/lib/ct_case_pipeline.py']
data = {**old, 'schema':'nasal_t029_source_freeze/v2', 'frozen_at':datetime.now(timezone.utc).isoformat(),
        'parent_commit':subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
        'previous_freeze_sha256':digest(previous),
        'code_sha256':{**old['code_sha256'], **{p:digest(ROOT / p) for p in paths}},
        'manager_change':'two engineering discriminators share strict ENGINEERING_CASE_RE; no gate/path/execution change',
        'manager_known_answers':15, 'actual_package_manager_check_sha256':digest(OUT / 'real-manager-package-check.json')}
path = OUT / 't029a_source_freeze_v2.json'
if path.exists():
    existing = json.loads(path.read_text(encoding='utf-8'))
    assert existing['code_sha256'] == data['code_sha256'] and existing['input_freeze_sha256'] == data['input_freeze_sha256']
    print(json.dumps({'existing_v2_freeze_unchanged':True, 'v2_freeze_sha256':digest(path)}))
else:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'v2_freeze_sha256':digest(path), 'manager_sha256':data['code_sha256']['work/lib/cfd_workspace_jobs.py'],
                      'admission_sha256':data['admission_sha256'], 'input_freeze_sha256':data['input_freeze_sha256']}))
