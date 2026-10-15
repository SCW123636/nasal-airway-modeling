"""One bounded source graph/loop trial, fixed planes; no mesh or solver."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'work/lib'))
import numpy as np
import vtk
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from export_candidate_preview import triangle_arrays
from connectivity_opened_surface import flood_mask
from outlet_selection_lineage import signed_distance
from outlet_selection_constraints import target_loop_catalog

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(name,obj):(OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

start=time.monotonic()
old=json.loads((ROOT/'outputs/T-013/real_cases_results.json').read_text(encoding='utf-8'))['cases']['p0']
inputs={p:sha(p) for p in old['frozen_inputs']};assert inputs==old['frozen_inputs']
source=next(Path(p) for p in inputs if Path(p).name=='source_surface.vtp')
files=[Path(__file__),*(ROOT/'work/lib'/x for x in ('partitioned_surface.py','outlet_selection_lineage.py',
    'outlet_selection_constraints.py','cross_section_scan.py','connectivity_opened_surface.py'))]
fingerprint={str(p):sha(p) for p in files}|inputs
save('target_trial_start.json',{'files':fingerprint,'planes':old['planes'],'threads':{x:os.getenv(x) for x in
    ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS')}})
r=vtk.vtkXMLPolyDataReader();r.SetFileName(str(source));r.Update();p,f=triangle_arrays(r.GetOutput())
spec=old['planes']['nasopharynx_outlet'];s=signed_distance(p,spec,1e-7);negative=s<0
edges=np.unique(np.sort(np.concatenate((f[:,[0,1]],f[:,[1,2]],f[:,[2,0]])),axis=1),axis=0)
ne=edges[negative[edges].all(axis=1)]
graph=coo_matrix((np.ones(len(ne)),(ne[:,0],ne[:,1])),shape=(len(p),len(p))).tocsr()
_,labels=connected_components(graph,directed=False)
roi_mask,note=flood_mask(p,f,spec);roi_components=set(labels[roi_mask].tolist())
catalog=target_loop_catalog(p,f,spec);save('fixed_outlet_target_loop_catalog.json',catalog)
protected=[]
for patch in ('nostril_L','nostril_R'):
    nspec=old['planes'][patch];ns=signed_distance(p,nspec,1e-7);nm,_=flood_mask(p,f,nspec)
    affected=np.any(nm[f],axis=1)&np.any(ns[f]<0,axis=1)
    boundary_edges=np.unique(np.sort(np.concatenate((f[affected][:,[0,1]],f[affected][:,[1,2]],f[affected][:,[2,0]])),axis=1),axis=0)
    boundary_edges=boundary_edges[(ns[boundary_edges[:,0]]<0)!=(ns[boundary_edges[:,1]]<0)]
    for a,b in boundary_edges:
        t=ns[a]/(ns[a]-ns[b]);point=p[a]+t*(p[b]-p[a]);future=float(signed_distance(np.array([point]),spec,1e-7)[0])
        if future<0:
            parent=next(int(v) for v in (a,b) if s[v]<0)
            protected.append({'patch':patch,'source_parent_edge':[int(a),int(b)],'negative_parent_vertex':parent,
                'outlet_negative_component':int(labels[parent]),'prospective_cap_point_lps_mm':point.tolist(),
                'outlet_signed_mm':future})
protected_components={x['outlet_negative_component'] for x in protected}
loops=[]
for entry in catalog['loops']:
    reached=set(entry['negative_components']); conflict=reached&protected_components
    loops.append({'loop_id':entry['id'],'area_mm2':entry['area_mm2'], 'components':entry['negative_components'],
        'coupled_loop_ids':entry['coupled_loop_ids'],'reached_from_original_roi':bool(reached&roi_components),
        'prospective_nostril_cap_conflict':bool(conflict),'protected_components':sorted(conflict),
        'witness':next((x for x in protected if x['outlet_negative_component'] in conflict),None)})
result={'scope':'mathematical fixed-plane target-loop alternatives; anatomy not selected',
    'source_sha256':inputs[str(source)],'binding':catalog['binding'],'original_roi_selection':note,
    'roi_reached_components':sorted(roi_components), 'roi_negative_component_vertex_counts':{
         str(c):int(np.count_nonzero(negative&(labels==c))) for c in sorted(roi_components)},
    'prospective_cap_boundary_vertices_negative':len(protected),'protected_components':sorted(protected_components),
    'protected_witnesses':protected, 'loops':loops,
    'semantic_evidence':'Frozen landmark nasopharynx/oropharynx interface is a plane proposal; no reviewed target_loop_id',
    'engineering_candidate_admitted':False,'patient_solver_allowed':False,'elapsed_s':time.monotonic()-start}
save('fixed_outlet_target_constraints.json',result)
end={p:sha(p) for p in fingerprint};save('target_trial_end.json',{'files':end,'unchanged':end==fingerprint,
    'elapsed_s':time.monotonic()-start});assert end==fingerprint
print(json.dumps({'elapsed_s':time.monotonic()-start,'loops':loops,
    'protected_components':sorted(protected_components),'roi_component_counts':result['roi_negative_component_vertex_counts']},
    ensure_ascii=False),flush=True)
