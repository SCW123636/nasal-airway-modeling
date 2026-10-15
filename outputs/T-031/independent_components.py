"""T031 independent known-answer checks. No author tests are invoked."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import traceback

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True,exist_ok=False)
spec=importlib.util.spec_from_file_location('reviewed_upper_airway',ROOT/'work/lib/upper_airway_workspace.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
expected=json.loads((ROOT/'outputs/T-031/known_answers.json').read_text(encoding='utf-8'))
checks=[]
def check(name,condition,detail=None):
    checks.append({'name':name,'passed':bool(condition),'detail':detail})
    if not condition: raise AssertionError(name)
def refused(name,func):
    try: func()
    except (ValueError,FileNotFoundError,KeyError) as exc:
        check(name,True,str(exc));return
    check(name,False,'request unexpectedly accepted')

try:
    source=ROOT/'outputs/T-026/runs/20261015_04_full'
    bundle=ROOT/'outputs/T-030/assets-v1'
    service=module.UpperAirwayWorkspace(source,bundle)
    catalog=service.catalog()
    check('exact five-case order',[x['case'] for x in catalog['cases']]==list(expected['cases']))
    for item in catalog['cases']:
        e=expected['cases'][item['case']]
        check(item['case']+' known coverage',item['inferior_face_air_voxels']==e['inferior_air_voxels'] and item['hypopharynx_empty'] and not item['larynx_air_exists'])
        check(item['case']+' not granted approval',item['clinical_review']=='not_reviewed' and not item['outlet_selected'] and not item['CFD_admitted'] and item['patient_symptom_mapping']=='unknown')
        result=service.case(item['case'])
        check(item['case']+' generated identity',('candidate' in result)==e['generated_candidate'])
    for case in ['p4','p3t2','u_fbca9137690e4837','../p3','p3/../p0','']:
        refused('unknown case '+repr(case),lambda case=case:service.case(case))
    for case,name in [('p0','baseline.vertices.bin'),('p3','../manifest.json'),('p3','ct-comparison.png/../../manifest.json'),('p3','manifest.json'),('p3','ct.nii.gz')]:
        refused('asset allowlist '+repr((case,name)),lambda case=case,name=name:service.asset_bytes(case,name))
    # Expected six crossings are literal algebra in known_answers, not a call to module math.
    control=expected['single_voxel_control']
    mask=np.zeros(tuple(control['size_xyz'][::-1]),dtype=np.uint8)
    mask[tuple(control['foreground_index_xyz'][::-1])]=1
    verts,faces,facts=module.surface_from_mask(mask,control['spacing_xyz_mm'],control['origin_LPS_mm'],control['direction_row_major'])
    order=lambda a:np.array(sorted(map(tuple,np.asarray(a).round(5))))
    check('single voxel rotated LPS coordinates',verts.shape==(6,3) and np.allclose(order(verts),order(control['axis_crossings_LPS_mm']),atol=2e-5),verts.tolist())
    check('single voxel unaltered topology',faces.shape==(8,3) and facts['source_voxels']==1 and facts['open_boundary_edges']==0)
    disconnected=np.zeros((6,6,6),dtype=np.uint8);disconnected[1,1,1]=1;disconnected[4,4,4]=1
    dv,df,di=module.surface_from_mask(disconnected,(1,1,1),(0,0,0),(1,0,0,0,1,0,0,0,1))
    check('two known disconnected components retained',len(dv)==12 and len(df)==16 and di['source_voxels']==2 and any(np.all(np.isclose(p,[1,1,.5])) for p in dv) and any(np.all(np.isclose(p,[4,4,4.5])) for p in dv))
    boundary=np.zeros((5,6,7),dtype=np.uint8);boundary[0:3,2:4,2:5]=1
    v,f,info=module.surface_from_mask(boundary,(.7,1.1,2.3),(11,23,37),(1,0,0,0,1,0,0,0,1))
    check('inferior boundary remains open',info['open_boundary_edges']>0 and np.isclose(v[:,2].min(),37) and not any(np.all(np.isclose(v[face,2],37)) for face in f),info)
    refused('empty mask',lambda:module.surface_from_mask(np.zeros((3,3,3),dtype=np.uint8),(1,1,1),(0,0,0),(1,0,0,0,1,0,0,0,1)))
    # Real already-generated display arrays, no new segmentation or extraction.
    manifest=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    check('manifest pinned hash',hashlib.sha256((bundle/'manifest.json').read_bytes()).hexdigest()==module.BUNDLE_MANIFEST_SHA256)
    check('p3 candidate fingerprints',manifest['source_sha256']['p3_nasal_original_candidate.nii.gz']==expected['p3']['original_sha256'] and manifest['source_sha256']['p3_nasal_oropharynx_candidate.nii.gz']==expected['p3']['extended_sha256'])
    geometry=manifest['CT'];direction=np.array(geometry['direction_row_major']).reshape(3,3)
    detail={}
    for name in ('baseline','added'):
        v=np.fromfile(bundle/f'{name}.vertices.bin',dtype='<f4').reshape(-1,3)
        f=np.fromfile(bundle/f'{name}.triangles.bin',dtype='<u4').reshape(-1,3)
        check(name+' finite vertices and valid faces',np.isfinite(v).all() and f.min()>=0 and f.max()<len(v))
        index=((v.astype(float)-geometry['origin_LPS_mm'])@np.linalg.inv(direction).T)/geometry['spacing_xyz_mm']
        check(name+' original-grid half-index positions',np.allclose(index*2,np.round(index*2),atol=6e-5),float(np.max(abs(index*2-np.round(index*2)))))
        edges=np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1)
        uniq,counts=np.unique(edges,axis=0,return_counts=True)
        graph=coo_matrix((np.ones(len(uniq)),(uniq[:,0],uniq[:,1])),shape=(len(v),len(v)))
        components,ids=connected_components(graph,directed=False)
        open_edges=uniq[counts==1]
        check(name+' surface totals match manifest',len(v)==manifest['surfaces'][name]['vertices'] and len(f)==manifest['surfaces'][name]['triangles'] and len(open_edges)==manifest['surfaces'][name]['open_boundary_edges'])
        if name=='baseline':
            original_report=json.loads((source/'p3_candidate_report.json').read_text(encoding='utf-8'))
            check('baseline full-source extent retained',len(open_edges)==0 and np.allclose([v.min(0),v.max(0)],original_report['profiles']['nasal_original']['bounds_LPS_mm'],atol=2e-5),{'surface_components':components,'open_edges':len(open_edges),'note':'surface shells and voxel connectivity are distinct; component preservation is independently checked by the two-voxel control'})
        if name=='added':check('real CT-face edges are open',len(open_edges)>0 and np.allclose(index[open_edges,2],0,atol=6e-5),{'open_edges':len(open_edges)})
        detail[name]={'vertices':len(v),'triangles':len(f),'components':int(components),'open_edges':len(open_edges),'bounds_LPS_mm':[v.min(0).tolist(),v.max(0).tolist()]}
    check('same CT preview exact bytes',hashlib.sha256((bundle/'ct-comparison.png').read_bytes()).hexdigest()=='d254c92256351f7de1c6c4b28c4bedb2f531654d56165512543b1cb7cfef9886')
    # Faults affect copies only. Keep each changed fixture to make refusal reproducible.
    for fault in ('missing_asset','changed_asset','changed_manifest','changed_source'):
        target=OUT/'fixtures'/fault;target.mkdir(parents=True)
        shutil.copytree(bundle,target/'bundle')
        shutil.copytree(source,target/'source')
        if fault=='missing_asset':(target/'bundle/added.vertices.bin').unlink()
        if fault=='changed_asset':
            p=target/'bundle/added.vertices.bin';b=bytearray(p.read_bytes());b[4]^=1;p.write_bytes(b)
        if fault=='changed_manifest':
            p=target/'bundle/manifest.json';p.write_bytes(p.read_bytes()+b' ')
        if fault=='changed_source':
            p=target/'source/p3_audit.json';p.write_bytes(p.read_bytes()+b' ')
        obj=module.UpperAirwayWorkspace(target/'source',target/'bundle')
        refused(fault+' rejects case',lambda:obj.case('p3'))
        refused(fault+' rejects asset',lambda:obj.asset_bytes('p3','ct-comparison.png'))
    result={'passed':True,'checks':checks,'real_display':detail,'source_code_sha256':hashlib.sha256((ROOT/'work/lib/upper_airway_workspace.py').read_bytes()).hexdigest()}
except Exception:
    result={'passed':False,'checks':checks,'exception':traceback.format_exc()}
(OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed':[x for x in checks if not x['passed']],'exception':result.get('exception')},ensure_ascii=False))
sys.exit(0 if result['passed'] else 1)
