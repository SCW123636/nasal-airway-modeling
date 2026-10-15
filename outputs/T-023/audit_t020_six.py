"""Independent bounded six-case replay of frozen T013 inputs, no solver."""
import os
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']: os.environ[key]='1'
import hashlib, importlib.util, json, pathlib, sys, time
from datetime import datetime, timezone
ROOT=pathlib.Path(__file__).resolve().parents[2]
OUT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'work/lib'))
import numpy as np
import vtk
from export_candidate_preview import triangle_arrays
from connectivity_opened_surface import flood_mask
from partitioned_surface import clip_and_cap
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def run(fn,p,f,planes,masks):
    try:
        p,f,l,q=fn(p,f,planes,selectors=masks)
        return {'passed':True,'array_sha256':{k:hashlib.sha256(x.tobytes()).hexdigest()
                for k,x in [('points',p),('faces',f),('labels',l.astype('U'))]},'qc':q}
    except ValueError as e:return {'passed':False,'error':str(e),'details':getattr(e,'details',None)}
orig=json.loads((ROOT/'outputs/T-013/real_cases_results.json').read_text(encoding='utf-8-sig'))
record=json.loads((ROOT/'outputs/T-020/fixed_clip_results.json').read_text(encoding='utf-8-sig'))
sp=importlib.util.spec_from_file_location('t023_frozen_for_six',OUT/'t020_frozen_before.py')
old=importlib.util.module_from_spec(sp);sp.loader.exec_module(old)
files=[ROOT/'work/lib/partitioned_surface.py',ROOT/'work/lib/outlet_selection_lineage.py',ROOT/'work/lib/connectivity_opened_surface.py',OUT/'t020_frozen_before.py',pathlib.Path(__file__)]
for c in ['p0','b01','b02','b21','b22','b23']:
    for p,h in orig['cases'][c]['frozen_inputs'].items():
        assert sha(p)==h,('frozen hash mismatch',c,p)
        files.append(pathlib.Path(p))
start={str(p):sha(p) for p in files}
report={'started_at':datetime.now(timezone.utc).isoformat(),'case_results':{},'start_fingerprints':start,
        'commands':['python outputs/T-023/audit_t020_six.py'],'thread_limits':{k:os.environ[k] for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']}}
begun=time.monotonic()
for c in ['p0','b01','b02','b21','b22','b23']:
    assert time.monotonic()-begun<85,'90-second bounded lane exhausted'
    x=orig['cases'][c]
    inp=next(pathlib.Path(p) for p in x['frozen_inputs'] if pathlib.Path(p).name=='source_surface.vtp')
    reader=vtk.vtkXMLPolyDataReader();reader.SetFileName(str(inp));reader.Update()
    p,f=triangle_arrays(reader.GetOutput());planes=x['planes']
    masks={k:flood_mask(p,f,s)[0] for k,s in planes.items()}
    new=run(clip_and_cap,p,f,planes,masks);before=run(old.clip_and_cap,p,f,planes,masks)
    if c=='p0':
        assert not new['passed'] and not before['passed']
        assert new['details']['conflicting_triangles']==774
        assert new['details']['fully_in_delete_halfspace_triangles']==774
        assert new['details']['strictly_crossing_plane_triangles']==0
        assert new['details']['earlier_patch_counts']=={'nostril_L':458,'nostril_R':316}
        assert 'outside cutting plane or ROI' in before['error']
        comparison={'honest_cap_refusal':True,'report_matches_executor':new['details']==record['cases'][c]['actual']['details']}
    else:
        assert new['passed'] and before['passed']
        comparison={'new_equals_frozen_old_arrays':new['array_sha256']==before['array_sha256'],
                    'matches_executor_new_arrays':new['array_sha256']==record['cases'][c]['actual']['array_sha256'],
                    'historical_array_equality':{k:v==x['baseline']['array_sha256'][k] for k,v in new['array_sha256'].items()},
                    'new_minus_old_cap_area':{k:new['qc']['caps'][k]['area_mm2']-before['qc']['caps'][k]['area_mm2'] for k in planes},
                    'new_minus_historical_cap_area':{k:new['qc']['caps'][k]['area_mm2']-x['baseline']['qc']['caps'][k]['area_mm2'] for k in planes}}
        assert comparison['new_equals_frozen_old_arrays'] and comparison['matches_executor_new_arrays']
        assert all(v==0 for v in comparison['new_minus_old_cap_area'].values())
    report['case_results'][c]={'new':new,'frozen_before':before,'comparison':comparison}
    path=OUT/('t020_six_'+c+'.json');assert not path.exists();path.write_text(json.dumps(report['case_results'][c],ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'case':c,'passed':new['passed'],'comparison':comparison,'elapsed_s':time.monotonic()-begun},ensure_ascii=False),flush=True)
report['end_fingerprints']={str(p):sha(p) for p in files}
assert report['end_fingerprints']==start
report.update(passed=True,elapsed_s=time.monotonic()-begun,finished_at=datetime.now(timezone.utc).isoformat())
target=OUT/'t020_six_result.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('INDEPENDENT_SIX_COMPLETE',report['elapsed_s'],flush=True)
