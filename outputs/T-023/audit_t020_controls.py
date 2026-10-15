"""Independent analytic controls; does not write production or original evidence."""
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'work/lib'))
import numpy as np
from outlet_selection_lineage import SourceSelectorLineage
from partitioned_surface import clip_and_cap, SurfaceClipError

checks = []
def ok(name, actual=None):
    checks.append({'name': name, 'passed': True, 'actual': actual})
def rejects(call, name, message):
    try:
        call()
    except ValueError as exc:
        assert message in str(exc), (name, str(exc))
        ok(name, str(exc))
        return exc
    raise AssertionError(name + ': expected rejection')

def spec(point, normal, keep=True):
    return {'point_lps_mm':point, 'normal_lps':normal, 'keep_positive':keep,
            'roi_lps_mm':{'min':[-20,-20,-20], 'max':[20,20,20]}}

# For the line from x=-4 to x=4 and the selector plane x=0, membership
# belongs only to its negative segment. OR would mark the positive segment;
# AND would lose the negative segment. This answer precedes the implementation.
p=np.array([[-4.,0,0],[4.,0,0],[4.,2,0]])
f=np.array([[0,1,2]])
for keep,normal,mask in [(True,[3,0,0],[True,False,False]),
                         (False,[-3,0,0],[True,False,False])]:
    line=SourceSelectorLineage(p,f,{'s':spec([0,0,0],normal,keep)},
                              {'s':np.array(mask)},1e-7)
    for x in [-3.,-1.,0.,1.,3.]: line.append_intersection(0,1,[x,0,0])
    assert line.get('s').tolist()==mask+[True,True,False,False,False]
    # Descendant parent at x=-1, source parent at +4; x=-0.5 still belongs
    # to the source negative component. This is a second subdivision.
    line.append_intersection(4,1,[-.5,0,0])
    assert line.get('s')[-1]
ok('mixed-sign edge, sign normalization, keep orientation and descendant subdivision')

for wrong in [np.array([True,False]),np.array([True,False,False,False]),
              np.array([[True],[False],[False]]),np.array([1,0,0])]:
    rejects(lambda:SourceSelectorLineage(p,f,{'s':spec([0,0,0],[1,0,0])},{'s':wrong},1e-7),
            'strict source boolean/length/shape '+str(wrong.shape), 'exactly one value per source vertex')
rejects(lambda:SourceSelectorLineage(p,f,{'s':spec([0,0,0],[1,0,0])},
           {'s':np.array([False,True,False])},1e-7),'kept-side selected source vertex','strict delete halfspace')
pn=np.array([[-2.,0,0],[-2.,1,0],[-2.,2,0]])
rejects(lambda:SourceSelectorLineage(pn,f,{'s':spec([0,0,0],[1,0,0])},
           {'s':np.array([True,False,False])},1e-7),'wholly-negative edge ambiguous membership','ambiguous selector')

# Independent rectangular box, outward faces: [0,4] x [0,4] x [0,8].
v=np.array([[0,0,0],[4,0,0],[4,4,0],[0,4,0],[0,0,8],[4,0,8],[4,4,8],[0,4,8]],float)
t=np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],
            [1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])
def masks(planes):
    result={}
    for name,s in planes.items():
        n=np.array(s['normal_lps'],float);n=n/np.linalg.norm(n)
        if not s['keep_positive']:n=-n
        result[name]=(v-np.array(s['point_lps_mm']))@n < -1e-7
    return result
cross={'z2':spec([0,0,2],[0,0,1]),'x2':spec([2,0,0],[1,0,0])}
e=rejects(lambda:clip_and_cap(v,t,cross,selectors=masks(cross)),
          'known z=2 cap crosses x=2 plane', 'delete selection would remove an earlier cap')
assert isinstance(e,SurfaceClipError) and e.details['strictly_crossing_plane_triangles']>0
swallow={'z2':cross['z2'],'z4':spec([0,0,4],[0,0,1])}
e=rejects(lambda:clip_and_cap(v,t,swallow,selectors=masks(swallow)),
          'known z=2 cap wholly swallowed below z=4', 'delete selection would remove an earlier cap')
assert e.details['strictly_crossing_plane_triangles']==0
assert e.details['fully_in_delete_halfspace_triangles']==e.details['conflicting_triangles']>0

disjoint={'z2':cross['z2'],'z6':spec([0,0,6],[0,0,1],False)}
selected=clip_and_cap(v,t,disjoint,selectors=masks(disjoint))
plain=clip_and_cap(v,t,disjoint)
empty=clip_and_cap(v,t,disjoint,selectors={})
for other in [plain,empty]:
    for a,b in zip(selected[:3],other[:3]):np.testing.assert_array_equal(a,b)
assert selected[3]['technical_qc']['signed_volume_mm3']==64
assert [selected[3]['caps'][name]['area_mm2'] for name in disjoint]==[16,16]
ok('unrelated caps: volume 4*4*4=64 and each cap area 4*4=16; None/empty selector compatibility')

baseline_bytes=subprocess.check_output(['git','show','ca9c939:work/lib/partitioned_surface.py'],cwd=ROOT)
baseline_path=OUT/'t020_frozen_before.py'
if baseline_path.exists():assert baseline_path.read_bytes()==baseline_bytes
else:baseline_path.write_bytes(baseline_bytes)
module_spec=importlib.util.spec_from_file_location('t023_frozen_before',baseline_path)
baseline=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(baseline)
old_plain=baseline.clip_and_cap(v,t,disjoint)
for a,b in zip(old_plain[:3],plain[:3]):np.testing.assert_array_equal(a,b)
rejects(lambda:baseline.clip_and_cap(v,t,cross,selectors=masks(cross)),
        'same analytic crossing with frozen old source', 'outside cutting plane or ROI')
ok('frozen pre-change no-selector output arrays exactly equal')

report={'scope':'independent small analytic source controls; no patient anatomy or solver assertion',
        'at':datetime.now(timezone.utc).isoformat(),'checks':checks,'passed':True,
        'source_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
          for path in [ROOT/'work/lib/partitioned_surface.py',ROOT/'work/lib/outlet_selection_lineage.py',pathlib.Path(__file__),baseline_path]}}
target=OUT/'t020_controls_result.json'
assert not target.exists(),'Evidence is append-only; choose a new result path'
target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'checks':len(checks),'output':str(target)},ensure_ascii=False))
