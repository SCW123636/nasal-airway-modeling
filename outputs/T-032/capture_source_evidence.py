"""Capture focused installed version/source and an official repository pointer."""
from pathlib import Path
import hashlib,json,datetime,urllib.request,base64,sys

OUT=Path(__file__).resolve().parent
BASE=Path(r'C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Lib\site-packages\totalsegmentator')
rows={}
terms={'map_tasks_config.py':('"head_glands_cavities"','"headneck_bones_vessels"','"task_id": 775','"task_id": 776','"crop": ["skull"]'),
       'map_to_binary.py':('"hypopharynx"','"oropharynx"','"larynx_air"','"hyoid"','"cricoid_cartilage"','"thyroid_cartilage"'),
       'python_api.py':('def get_task_config','def totalsegmentator','crop_model_task = 298','seg_img, ct_img, stats = nnUNet_predict_image'),
       'nnunet.py':('def nnUNet_predict_image','torch.set_num_threads(multiprocessing.cpu_count())','def nnUNetv2_predict')}
for name,t in terms.items():
    p=BASE/name;raw=p.read_bytes();lines=raw.decode('utf-8').splitlines()
    rows[name]={'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'matches':[{'line':i,'text':l.strip()} for i,l in enumerate(lines,1) if any(x in l for x in t)]}
report={'created':datetime.datetime.now().astimezone().isoformat(),'installed_source':rows,'official':{}}
url='https://api.github.com/repos/wasserth/TotalSegmentator/commits/master'
try:
    request=urllib.request.Request(url,headers={'User-Agent':'nasal-cfd-engineering-source-check'})
    with urllib.request.urlopen(request,timeout=20) as r:meta=json.load(r)
    rev=meta['sha'];url=f'https://raw.githubusercontent.com/wasserth/TotalSegmentator/{rev}/README.md'
    try:
        with urllib.request.urlopen(url,timeout=20) as r:raw=r.read()
    except Exception as raw_error:
        report['official_fetch_raw_error']=repr(raw_error)
        url=f'https://api.github.com/repos/wasserth/TotalSegmentator/contents/README.md?ref={rev}'
        request=urllib.request.Request(url,headers={'User-Agent':'nasal-cfd-engineering-source-check'})
        with urllib.request.urlopen(request,timeout=20) as r:readme=json.load(r)
        raw=base64.b64decode(readme['content'])
    text=raw.decode('utf-8')
    report['official']={'commit_sha':rev,'readme_url':url,'readme_sha256':hashlib.sha256(raw).hexdigest(),
                        'has_head_glands_cavities':'head_glands_cavities' in text,'has_hypopharynx':'hypopharynx' in text,
                        'has_headneck_bones_vessels':'headneck_bones_vessels' in text,'has_larynx_air':'larynx_air' in text}
except Exception as e:report['official']={'url':url,'fetch_error':repr(e)}
target=OUT/(sys.argv[1] if len(sys.argv)>1 else 'source_evidence.json')
if target.exists():raise FileExistsError(target)
target.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(report,indent=2,ensure_ascii=False))
