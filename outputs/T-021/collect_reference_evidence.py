"""Collect small immutable evidence; volume meshes and fields remain runtime."""
from pathlib import Path
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
source = HERE / 'reference_split_run'
target = HERE / 'reference_evidence';target.mkdir(exist_ok=True)
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
report = json.loads((source/'feedback_suite_report.json').read_text())
shutil.copy2(source/'feedback_suite_report.json',target/'feedback_suite_report.json')
index = {'native_root':'/home/lenovo2/nasal_t021_split_20261015','selected':{},'raw_field_sha256':{}}
for name,scenario in report['scenarios'].items():
    folder = target/name;folder.mkdir(exist_ok=True)
    inputs = source/name/'evaluations/input_fingerprint.json'
    shutil.copy2(inputs,folder/'input_fingerprint.json')
    for record in scenario['evaluations']:
        case = source/name/'evaluations'/Path(record['case']).name
        saved = folder/case.name;saved.mkdir(exist_ok=True)
        record_name = 'evaluation_' + case.name.split('_')[1] + '.json'
        shutil.copy2(case.parent/record_name,saved/record_name)
        for filename in ('run_manifest.json','case_manifest.json','log.blockMesh','log.checkMesh'):
            shutil.copy2(case/filename,saved/filename)
        if record is scenario['evaluations'][-1]:
            shutil.copy2(case/'log.simpleFoam',saved/'log.simpleFoam')
        for field in (case/'VTK').rglob('internal.vtu'):
            index['raw_field_sha256'][str(field.relative_to(source))] = sha(field)
for path in target.rglob('*'):
    if path.is_file(): index['selected'][path.relative_to(HERE).as_posix()] = sha(path)
(HERE/'reference_evidence_index.json').write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'selected_files':len(index['selected']),'raw_fields':len(index['raw_field_sha256'])}))
