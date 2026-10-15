"""Fresh per-tet combinations/Counter oracle, not vectorized face-major logic."""
import contextlib,hashlib,importlib.util,io,itertools,json,pathlib,traceback
from collections import Counter
import numpy as np
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
newpath=ROOT/'work/lib/analyze_sliver_cells.py';oldpath=ROOT/'outputs/T-028/baseline/analyze_sliver_cells.py'
new=module('fresh_sliver_new',newpath);old=module('fresh_sliver_old',oldpath)
target=OUT/'t028_fresh_faces_result.json';assert not target.exists()
result={'source_sha256':sha(newpath),'baseline_sha256':sha(oldpath),'controls':[],'patient_mesh_loaded':False,'wsl_invoked':False}
try:
    rng=np.random.default_rng(20261015)
    layouts=[[[0,1,2,3],[0,1,2,4]],
             [[0,1,2,3],[0,1,2,4],[0,1,3,5],[0,2,3,6],[7,8,9,10]],
             [[0,1,2,3],[0,1,2,4],[0,1,4,5],[1,4,5,6],[7,8,9,10]]]
    old_mismatches=0
    for li,layout in enumerate(layouts):
        for iteration in range(12):
            order=rng.permutation(len(layout));tets=np.array([rng.permutation(layout[i]) for i in order],dtype=np.int64)
            owned=[list(itertools.combinations(map(int,tet),3)) for tet in tets]
            allkeys=Counter(tuple(sorted(face)) for faces in owned for face in faces)
            boundary=sorted(k for k,v in allkeys.items() if v==1)
            tags={key:101+13*i for i,key in enumerate(boundary)}
            expected_count=[sum(allkeys[tuple(sorted(f))]==1 for f in faces) for faces in owned]
            expected_tags=[tags[tuple(sorted(next(f for f in faces if allkeys[tuple(sorted(f))]==1)))] if n==1 else None for faces,n in zip(owned,expected_count)]
            triorder=rng.permutation(len(boundary));tri=np.array([rng.permutation(boundary[i]) for i in triorder]);labels=np.array([tags[boundary[i]] for i in triorder])
            with contextlib.redirect_stdout(io.StringIO()):
                got,gotlabels=new.exterior_faces(tets,tri,labels,int(tets.max())+1)
                prior,_=old.exterior_faces(tets,tri,labels,int(tets.max())+1)
            np.testing.assert_array_equal(got,expected_count)
            for i,label in enumerate(expected_tags):
                if label is not None:assert gotlabels[i]==label
            old_failed=not np.array_equal(prior,expected_count);old_mismatches+=old_failed
            result['controls'].append({'layout':li,'permutation':iteration,'tet_input':tets.tolist(),'expected_exterior_per_tet':expected_count,
                'actual':got.tolist(),'unambiguous_patch_tags':expected_tags,'old_actual':prior.tolist(),'old_failed':old_failed})
    assert old_mismatches>0
    with contextlib.redirect_stdout(io.StringIO()) as log:flag=new.selftest()
    assert type(flag) is bool and flag is True
    assert old.KNOWN==new.KNOWN
    known_origin=[0,1,1,1,1,2,3,4,4,4,4,5]
    np.testing.assert_array_equal(new.repair_origin(12,[1,4],6),known_origin)
    rejected=[]
    for n in [11,13]:
        try:new.repair_origin(n,[1,4],6)
        except SystemExit as e:rejected.append({'requested_output':n,'message':str(e)})
        else:raise AssertionError('Incomplete repair map was accepted')
    result.update(passed=True,old_mismatch_count=old_mismatches,selftest_python_bool=True,selftest_stdout=log.getvalue(),
                  checkMesh_constants_unchanged=new.KNOWN,repair_origin_known=known_origin,repair_origin_rejections=rejected,
                  scope='Small software diagnostics only; historical derived patch counts require separate recomputation; no patient mesh or checkMesh result changed')
except Exception:result.update(passed=False,failure=traceback.format_exc());raise
finally:target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'controls':len(result['controls']),'old_mismatch_count':old_mismatches,'selftest_python_bool':True,'checkMesh_constants_unchanged':True}))
