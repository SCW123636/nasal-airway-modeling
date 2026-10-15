"""Read-only stage diagnosis; never changes the source job or its report."""
import hashlib
import json
from pathlib import Path
import sys
import traceback
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'work/lib'))
from patient_cfd_viewer import _grid,_surface,_interior_slices
OUT=Path(__file__).resolve().parent
JOB=Path('C:/ts_work/project_cases/simulation_jobs/s_aa79a63027b94bfb9a273898')
SOURCE=next((JOB/'export').rglob('internal.vtu'))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def stats(poly):
    p=vtk_to_numpy(poly.GetPoints().GetData()).astype(float)
    raw=vtk_to_numpy(poly.GetPolys().GetConnectivityArray())
    offsets=vtk_to_numpy(poly.GetPolys().GetOffsetsArray())
    if not np.all(np.diff(offsets)==3):return {'points':len(p),'polygon_sizes':np.unique(np.diff(offsets),return_counts=True)[0].tolist()}
    f=raw.reshape(-1,3);xyz=p[f]
    area=np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)
    bad=np.flatnonzero(area<=1e-20)
    repeated=np.any((f[:,0]==f[:,1])|(f[:,0]==f[:,2])|(f[:,1]==f[:,2]))
    return {'points':len(p),'triangles':len(f),'point_dtype':poly.GetPoints().GetData().GetDataTypeAsString(),
        'zero_area':int(np.count_nonzero(area==0)),'at_or_below_existing_gate':len(bad),
        'minimum_cross_norm_m2':float(area.min()),'area_quantiles_m2':np.quantile(area,[0,.001,.01,.5,1]).tolist(),
        'any_repeated_index':bool(repeated),
        'bad_samples':[{'triangle':int(i),'point_ids':f[i].tolist(),'points_m':xyz[i].tolist(),
                        'cross_norm_m2':float(area[i])} for i in bad[:5]]}

before={str(p):sha(p) for p in (SOURCE,JOB/'job.json',SOURCE.parents[2]/'config.json')}
grid,association=_grid(SOURCE)
evidence={'source':str(SOURCE),'source_before':before,'vtk_version':vtk.vtkVersion.GetVTKVersion(),
    'source_points':grid.GetNumberOfPoints(),'source_cells':grid.GetNumberOfCells(),
    'source_point_dtype':grid.GetPoints().GetData().GetDataTypeAsString(),'bounds_m':grid.GetBounds(),
    'source_association':association,'stages':{}}
surface=vtk.vtkDataSetSurfaceFilter();surface.SetInputData(grid);surface.Update()
triangle=vtk.vtkTriangleFilter();triangle.SetInputConnection(surface.GetOutputPort());triangle.PassVertsOff();triangle.PassLinesOff();triangle.Update()
evidence['stages']['surface_before_triangle']=stats(surface.GetOutput())
evidence['stages']['surface_after_triangle']=stats(triangle.GetOutput())
try:_surface(grid);evidence['production_surface']='pass'
except Exception:evidence['production_surface']=traceback.format_exc()
bounds=grid.GetBounds();center=np.array([(bounds[2*i]+bounds[2*i+1])/2 for i in range(3)])
for axis,name in enumerate('xyz'):
    for precision in ('default','double'):
        plane=vtk.vtkPlane();plane.SetOrigin(*center);plane.SetNormal(*np.eye(3)[axis])
        cutter=vtk.vtkCutter();cutter.SetInputData(grid);cutter.SetCutFunction(plane)
        if precision=='double':cutter.SetOutputPointsPrecision(vtk.vtkAlgorithm.DOUBLE_PRECISION)
        cutter.Update();tri=vtk.vtkTriangleFilter();tri.SetInputConnection(cutter.GetOutputPort());tri.Update()
        evidence['stages'][name+'_'+precision]=stats(tri.GetOutput())
try:_interior_slices(grid,1.2,sha(SOURCE));evidence['production_slices']='pass'
except Exception:evidence['production_slices']=traceback.format_exc()
evidence['source_after']={path:sha(path) for path in before}
evidence['source_unchanged']=evidence['source_before']==evidence['source_after']
target=OUT/'stage_diagnosis.json'
if target.exists():raise RuntimeError('Do not overwrite diagnosis evidence')
target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in evidence.items() if k not in ('source_before','source_after')},ensure_ascii=False))
