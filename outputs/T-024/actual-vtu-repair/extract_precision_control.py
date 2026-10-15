"""Trace degenerate cutter output to source cells without editing the source."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy,numpy_to_vtk
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2];sys.path.insert(0,str(ROOT/'work/lib'))
from patient_cfd_viewer import _grid
job=Path('C:/ts_work/project_cases/simulation_jobs/s_aa79a63027b94bfb9a273898')
source=next((job/'export').rglob('internal.vtu'));digest=hashlib.sha256(source.read_bytes()).hexdigest()
grid,_=_grid(source);bounds=grid.GetBounds();center=[(bounds[2*i]+bounds[2*i+1])/2 for i in range(3)]
ids=numpy_to_vtk(np.arange(grid.GetNumberOfCells(),dtype=np.int64),deep=True);ids.SetName('read_only_source_cell_id');grid.GetCellData().AddArray(ids)
plane=vtk.vtkPlane();plane.SetOrigin(*center);plane.SetNormal(0,0,1)
cut=vtk.vtkCutter();cut.SetCutFunction(plane);cut.SetInputData(grid);cut.Update()
poly=cut.GetOutput();p=vtk_to_numpy(poly.GetPoints().GetData()).astype(float);f=vtk_to_numpy(poly.GetPolys().GetConnectivityArray()).reshape(-1,3)
area=np.linalg.norm(np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]]),axis=1)
cells=vtk_to_numpy(poly.GetCellData().GetArray('read_only_source_cell_id'));bad=np.flatnonzero(area<=1e-20)
samples=[]
for idx in bad[:3]:
    cell_id=int(cells[idx]);cell=grid.GetCell(cell_id);point_ids=[cell.GetPointId(i) for i in range(cell.GetNumberOfPoints())]
    samples.append({'cutter_triangle_id':int(idx),'source_cell_id':cell_id,'vtk_cell_type':cell.GetCellType(),
        'source_point_ids':point_ids,'source_points_m':[grid.GetPoint(i) for i in point_ids]})
evidence={'source':str(source),'source_sha256':digest,'source_dtype':grid.GetPoints().GetData().GetDataTypeAsString(),
          'bounds_m':bounds,'plane_origin_m':center,'normal':[0,0,1],'bad_triangle_count':len(bad),'samples':samples,
          'source_unchanged':digest==hashlib.sha256(source.read_bytes()).hexdigest()}
path=OUT/'precision_control_source.json'
if path.exists():raise RuntimeError('Do not overwrite provenance evidence')
path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(evidence,ensure_ascii=False))
