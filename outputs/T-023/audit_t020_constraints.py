"""Independent target-loop controls and source-edge witness audit."""
import os
for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']:os.environ[key]='1'
import hashlib,json,math,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'work/lib'))
import numpy as np
import vtk
from export_candidate_preview import triangle_arrays
from connectivity_opened_surface import flood_mask
from outlet_selection_constraints import selection_binding,target_loop_catalog,constrained_target_selector,SelectionConstraintError
def spec(point,normal,keep=True):return {'point_lps_mm':point,'normal_lps':normal,'keep_positive':keep,'roi_lps_mm':{'min':[-20,-20,-20],'max':[20,20,20]}}
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
checks=[]
def reject(fn,msg):
    try:fn()
    except ValueError as e:assert msg in str(e);return str(e)
    raise AssertionError('expected rejection '+msg)

# Two separate boxes with equal cross section. Explicitly selecting one cannot
# silently pick the largest, trim a protected vertex or consume the other box.
p=np.array([[0,0,0],[4,0,0],[4,4,0],[0,4,0],[0,0,8],[4,0,8],[4,4,8],[0,4,8]],float)
f=np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],[0,1,5],[0,5,4],[1,2,6],[1,6,5],[2,3,7],[2,7,6],[3,0,4],[3,4,7]])
p=np.vstack([p,p+[10,0,0]]);f=np.vstack([f,f+8]);s=spec([0,0,3],[0,0,1])
cat=target_loop_catalog(p,f,s);assert len(cat['loops'])==2
left=next(x['id'] for x in cat['loops'] if max(v[0] for v in x['contour_lps_mm'])<5)
mask,note=constrained_target_selector(p,f,s,[left],expected_binding=cat['binding'])
assert mask[:8].sum()==4 and not mask[8:].any()
protected=np.zeros(len(p),bool);protected[8:]=True
np.testing.assert_array_equal(mask,constrained_target_selector(p,f,s,[left],expected_binding=cat['binding'],protected_vertices=protected)[0])
protected[0]=True
reject(lambda:constrained_target_selector(p,f,s,[left],expected_binding=cat['binding'],protected_vertices=protected),'conflicts')
allowed=np.ones(len(p),bool);allowed[0]=False
reject(lambda:constrained_target_selector(p,f,s,[left],expected_binding=cat['binding'],allowed_delete_vertices=allowed),'conflicts')
assert not note['anatomy_approved'] and not note['patient_solver_allowed'] and note['final_clipper_area_N6_required']
checks.append('two exact disjoint boxes select one whole component; protection/allowance conflict rejects without trim')
for wrongp,wrongf,wrongs in [(p+.1,f,s),(p,f[::-1],s),(p,f,spec([0,0,3],[0,0,2])),(p,f,spec([0,0,3],[0,0,1],False))]:
    reject(lambda:constrained_target_selector(wrongp,wrongf,wrongs,[left],expected_binding=cat['binding']),'binding')
checks.append('source coordinates, face order, normal identity and kept side mutations reject frozen binding')

# Build the exact boundary of a U from occupied unit cubes. Below z=3.5 the
# two arms are connected by the base (z<2), so one upper rim cannot be selected.
occupied={(x,0,z) for x in range(6) for z in range(6) if z<2 or x<2 or x>=4}
verts=[];faces=[];lookup={}
directions=[((1,0,0),[(1,0,0),(1,1,0),(1,1,1),(1,0,1)]),((-1,0,0),[(0,0,0),(0,0,1),(0,1,1),(0,1,0)]),
 ((0,1,0),[(0,1,0),(0,1,1),(1,1,1),(1,1,0)]),((0,-1,0),[(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
 ((0,0,1),[(0,0,1),(1,0,1),(1,1,1),(0,1,1)]),((0,0,-1),[(0,0,0),(0,1,0),(1,1,0),(1,0,0)])]
for cell in sorted(occupied):
    for delta,corners in directions:
        if tuple(a+b for a,b in zip(cell,delta)) in occupied:continue
        ids=[]
        for corner in corners:
            vertex=tuple(a+b for a,b in zip(cell,corner))
            if vertex not in lookup:lookup[vertex]=len(verts);verts.append(vertex)
            ids.append(lookup[vertex])
        faces.extend([[ids[0],ids[1],ids[2]],[ids[0],ids[2],ids[3]]])
up,uf=np.array(verts,float),np.array(faces);us=spec([0,0,3.5],[0,0,1])
uc=target_loop_catalog(up,uf,us);assert len(uc['loops'])==2
assert all(x['coupled_loop_ids']==[0,1] for x in uc['loops'])
reject(lambda:constrained_target_selector(up,uf,us,[0],expected_binding=uc['binding']),'inseparable')
constrained_target_selector(up,uf,us,[0,1],expected_binding=uc['binding'])
checks.append('independent cubical U has two rims sharing a negative component; one-loop selection rejects')

# Verify all p0 cap-protection witnesses by exact source parent edges and a
# separately derived dot-product halfspace and union-find graph. No proximity.
original=json.loads((ROOT/'outputs/T-013/real_cases_results.json').read_text(encoding='utf-8'))['cases']['p0']
published=json.loads((ROOT/'outputs/T-020/fixed_outlet_target_constraints.json').read_text(encoding='utf-8'))
catalog=json.loads((ROOT/'outputs/T-020/fixed_outlet_target_loop_catalog.json').read_text(encoding='utf-8'))
for file,h in original['frozen_inputs'].items():assert sha(file)==h
file=next(pathlib.Path(x) for x in original['frozen_inputs'] if pathlib.Path(x).name=='source_surface.vtp')
r=vtk.vtkXMLPolyDataReader();r.SetFileName(str(file));r.Update();p,f=triangle_arrays(r.GetOutput())
def signed(s):
    n=np.array(s['normal_lps'],float);n/=np.linalg.norm(n)
    if not s['keep_positive']:n=-n
    return (p-np.array(s['point_lps_mm']))@n,n
outsign,outn=signed(original['planes']['nasopharynx_outlet']);negative=outsign < -1e-7
edges=np.unique(np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1),axis=0)
parent=np.arange(len(p))
def root(a):
    while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
    return int(a)
for a,b in edges[negative[edges].all(axis=1)]:
    a,b=root(a),root(b)
    if a!=b:parent[b]=a
roots=np.array([root(i) for i in range(len(p))])
expected=set();witnesses=published['protected_witnesses'];edge_set={tuple(x) for x in edges}
for name in ['nostril_L','nostril_R']:
    ns,_=signed(original['planes'][name]);ns[np.abs(ns)<=1e-7]=0
    nm,_=flood_mask(p,f,original['planes'][name]);affected=np.any(nm[f],axis=1)&np.any(ns[f]<0,axis=1)
    ae=np.unique(np.sort(np.concatenate([f[affected][:,[0,1]],f[affected][:,[1,2]],f[affected][:,[2,0]]]),axis=1),axis=0)
    ae=ae[(ns[ae[:,0]]<0)!=(ns[ae[:,1]]<0)]
    for a,b in ae:
        q=p[a]+ns[a]/(ns[a]-ns[b])*(p[b]-p[a])
        if (q-np.array(original['planes']['nasopharynx_outlet']['point_lps_mm']))@outn < -1e-7:expected.add((name,int(a),int(b)))
assert {(x['patch'],*x['source_parent_edge']) for x in witnesses}==expected
assert len(witnesses)==len(expected)==774
protected_roots=set()
for w in witnesses:
    a,b=w['source_parent_edge'];assert (a,b) in edge_set
    ns,_=signed(original['planes'][w['patch']]);fraction=ns[a]/(ns[a]-ns[b]);assert 0<=fraction<=1
    point=p[a]+fraction*(p[b]-p[a]);np.testing.assert_allclose(point,w['prospective_cap_point_lps_mm'],rtol=0,atol=1e-12)
    d=float((point-np.array(original['planes']['nasopharynx_outlet']['point_lps_mm']))@outn)
    assert math.isclose(d,w['outlet_signed_mm'],abs_tol=1e-12) and d<0
    a=w['negative_parent_vertex'];assert a in w['source_parent_edge'] and negative[a]
    protected_roots.add(root(a))
loopfacts=[]
for loop in catalog['loops']:
    ids=np.unique(f[loop['rim_source_faces']]);lr=set(roots[ids[negative[ids]]])
    contour=np.array(loop['contour_lps_mm']);area=.5*np.linalg.norm(np.cross(contour,np.roll(contour,-1,axis=0)).sum(axis=0))
    n=np.array(original['planes']['nasopharynx_outlet']['normal_lps'],float);n/=np.linalg.norm(n)
    helper=np.array([1.,0,0]) if abs(n[0])<.9 else np.array([0.,1,0])
    u=np.cross(n,helper);u/=np.linalg.norm(u);v=np.cross(n,u)
    xy=np.round(np.stack([contour@u,contour@v],axis=1),6)
    projected_area=abs(.5*(np.dot(xy[:,0],np.roll(xy[:,1],-1))-np.dot(xy[:,1],np.roll(xy[:,0],-1))))
    assert projected_area==loop['area_mm2'],(projected_area,loop['area_mm2'])
    loopfacts.append({'loop_id':loop['id'],'independent_3d_polygon_area_mm2':float(area),'independent_six_decimal_projected_area_mm2':float(projected_area),'published_projected_area_mm2':loop['area_mm2'],
                      'protected_root_conflict':bool(lr&protected_roots),'component_roots':sorted(int(x) for x in lr)})
assert [x['protected_root_conflict'] for x in loopfacts]==[True,True,True,False]
assert loopfacts[0]['component_roots']==loopfacts[2]['component_roots']
assert loopfacts[3]['independent_3d_polygon_area_mm2']<120
checks.append('all 774 p0 witnesses are complete exact parent-edge intersections; independent source graph confirms ring 0/1/2 cap conflict')
checks.append('only unprotected ring 3 has polygon area below 120mm2; this cannot grant final cap area/N6/anatomy')
report={'passed':True,'scope':'target-loop constraint software and frozen p0 mathematical feasibility only',
        'checks':checks,'p0_witness_count':774,'p0_loop_facts':loopfacts,
        'source_hashes':{str(file):sha(file),str(ROOT/'work/lib/outlet_selection_constraints.py'):sha(ROOT/'work/lib/outlet_selection_constraints.py')}}
target=OUT/'t020_constraints_result.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'check_groups':len(checks),'witnesses':774,'loops':loopfacts},ensure_ascii=False))
