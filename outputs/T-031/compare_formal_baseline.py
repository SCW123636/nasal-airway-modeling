"""Compare read-only formal HTTP state to pre-integration captured state."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT=Path(__file__).resolve().parent
OUT=Path(sys.argv[1]).resolve();OUT.mkdir(parents=True,exist_ok=False)
before=json.loads((ROOT/'runs/03_baseline_workspace/baseline.json').read_text(encoding='utf-8'))['api']
checks=[];after={}
for route in ('/api/cases','/api/simulation/catalog','/api/simulation/jobs','/viewer/workspace_data.json'):
    with urllib.request.urlopen('http://127.0.0.1:8769'+route,timeout=30) as r:
        after[route]=json.load(r)
    checks.append({'route':route,'exact_json_unchanged':before[route]['json']==after[route]})
files=['work/lib/upper_airway_workspace.py','work/lib/serve_cfd_workspace.py','work/07_cfd_pipeline/workspace/index.html','work/07_cfd_pipeline/workspace/workspace.js','work/07_cfd_pipeline/workspace/upper-airway.html','work/07_cfd_pipeline/workspace/upper-airway.js','work/07_cfd_pipeline/workspace/upper-airway.css','outputs/T-030/assets-v1/manifest.json']
workspace=ROOT.parents[1]
hashes={p:hashlib.sha256((workspace/p).read_bytes()).hexdigest() for p in files}
served={}
for relative in ('index.html','workspace.js','upper-airway.html','upper-airway.js','upper-airway.css'):
    with urllib.request.urlopen('http://127.0.0.1:8769/workspace/'+relative,timeout=30) as r:raw=r.read()
    key='work/07_cfd_pipeline/workspace/'+relative
    served[relative]={'served_sha256':hashlib.sha256(raw).hexdigest(),'disk_sha256':hashes[key]}
    checks.append({'route':'/workspace/'+relative,'exact_served_source':served[relative]['served_sha256']==served[relative]['disk_sha256']})
result={'passed':all(x.get('exact_json_unchanged',x.get('exact_served_source')) for x in checks),'checks':checks,'after':after,'source_hashes':hashes,'served_hashes':served}
(OUT/'baseline_comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':result['passed'],'checks':checks},ensure_ascii=False))
sys.exit(0 if result['passed'] else 1)
