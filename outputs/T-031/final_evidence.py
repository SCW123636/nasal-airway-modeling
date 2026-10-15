"""Final formal-service and original-input checks, independently read from disk/HTTP."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(sys.argv[1]).resolve();OUT.mkdir(parents=True,exist_ok=False)
before=json.loads((ROOT/'outputs/T-031/runs/03_baseline_workspace/baseline.json').read_text(encoding='utf-8'))['api']
after=json.loads((ROOT/'outputs/T-031/runs/08_formal_baseline_compare/baseline_comparison.json').read_text(encoding='utf-8'))['after']
old={c['id']:c for c in before['/api/simulation/catalog']['json']['cases']}
new={c['id']:c for c in after['/api/simulation/catalog']['cases']}
catalog={'original_entries_unchanged':all(new.get(k)==v for k,v in old.items()),'removed':sorted(set(old)-set(new)),'added':sorted(set(new)-set(old)),'known_external_source':'outputs/T-029/provision_b15_engineering_t029a.py and outputs/T-029/t029a_admission.json'}
with urllib.request.urlopen('http://127.0.0.1:8769/health.json',timeout=15) as r:health=json.load(r)
checks=[{'name':'formal service loaded frozen upper-airway module','passed':health.get('upper_airway')=='frozen-read-only-v1' and health.get('ct_import') and health.get('simulation_jobs')},
        {'name':'original simulation catalog entries exact unchanged','passed':catalog['original_entries_unchanged'] and not catalog['removed']},
        {'name':'catalog addition belongs only to independent T029 task','passed':catalog['added']==['b15_engineering_t029a'] and (ROOT/'outputs/T-029/provision_b15_engineering_t029a.py').is_file()}]
fingerprints=json.loads((ROOT/'outputs/T-026/runs/20261015_04_full/input_fingerprints_before.json').read_text(encoding='utf-8'))
facts=[]
for item in fingerprints:
    p=Path(item['path']);exists=p.is_file()
    actual=hashlib.sha256(p.read_bytes()).hexdigest() if exists else None
    passed=exists==item['exists'] and actual==item['sha256']
    facts.append({'path':str(p),'exists':exists,'actual_sha256':actual,'expected_sha256':item['sha256'],'passed':passed})
checks.append({'name':'35 original CT-label input fingerprints remain frozen','passed':len(facts)==35 and all(x['passed'] for x in facts)})
preserved=after['/api/simulation/jobs']['jobs']
failed=next(j for j in preserved if j['id']=='s_942fdbebfffd433c8fcec956')
checks.append({'name':'17 original jobs and latest failure retained','passed':len(preserved)==17 and failed['status']=='failed'})
result={'passed':all(x['passed'] for x in checks),'checks':checks,'health':health,'catalog_difference':catalog,'original_inputs':facts,'latest_original_failed_job':failed}
(OUT/'final_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':result['passed'],'checks':checks,'catalog_difference':catalog},ensure_ascii=False))
sys.exit(0 if result['passed'] else 1)
