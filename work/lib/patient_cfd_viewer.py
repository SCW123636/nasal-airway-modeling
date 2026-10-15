"""Surface fields for explicitly unvalidated patient engineering diagnostics.

This adapter never constructs nasal_cfd_result/v1 or changes patient admission.
It uses the final evaluation of this job and refuses missing/stale identities.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy

JOB_RE=re.compile(r's_[0-9a-f]{24}')
SHA_RE=re.compile(r'[0-9a-f]{64}')
RESULT_SCHEMA='nasal_patient_engineering_diagnostic/v1'
MESH_SCHEMA='patient_engineering_surface/v1'
TYPE='patient_engineering_diagnostic'


def _read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')


def _dimensions(path,expected):
    text=Path(path).read_text(encoding='utf-8',errors='replace')
    found=re.search(r'\bdimensions\s*\[([^\]]+)\]\s*;',text)
    if not found or found.group(1).split()!=[str(x) for x in expected]:
        raise ValueError('最终字段量纲不符：'+str(path))


def _grid(source):
    reader=vtk.vtkXMLUnstructuredGridReader()
    if not reader.CanReadFile(str(source)):
        raise ValueError('本次VTU不是可读取的体网格')
    reader.SetFileName(str(source));reader.Update();grid=reader.GetOutput()
    if not grid.GetNumberOfCells() or not grid.GetNumberOfPoints():
        raise ValueError('本次VTU体网格为空')
    if not np.isfinite(vtk_to_numpy(grid.GetPoints().GetData())).all():
        raise ValueError('本次VTU体网格坐标含非有限数')
    association={}
    for key in ('U','p'):
        point=grid.GetPointData().GetArray(key)
        cell=grid.GetCellData().GetArray(key)
        if point is None and cell is None:
            raise ValueError('本次VTU缺字段：'+key)
        array=point if point is not None else cell
        expected=grid.GetNumberOfPoints() if point is not None else grid.GetNumberOfCells()
        if array.GetNumberOfTuples()!=expected or array.GetNumberOfComponents()!=(3 if key=='U' else 1):
            raise ValueError('本次VTU字段长度或分量不符：'+key)
        if not np.isfinite(vtk_to_numpy(array)).all():
            raise ValueError('本次VTU字段含非有限数：'+key)
        association[key]='point' if point is not None else 'cell_to_point_average'
    if 'cell_to_point_average' in association.values():
        converter=vtk.vtkCellDataToPointData();converter.SetInputData(grid)
        converter.ProcessAllArraysOff()
        for key,value in association.items():
            if value=='cell_to_point_average':converter.AddCellDataArray(key)
        converter.Update();grid=converter.GetOutput()
    return grid,association


def _poly_arrays(poly):
    if not poly.GetNumberOfPoints() or not poly.GetNumberOfPolys():
        raise ValueError('本次体网格采样为空')
    polygons=poly.GetPolys()
    if np.any(np.diff(vtk_to_numpy(polygons.GetOffsetsArray()))!=3):
        raise ValueError('本次采样不是三角面')
    p=vtk_to_numpy(poly.GetPoints().GetData()).astype(float)
    f=vtk_to_numpy(polygons.GetConnectivityArray()).reshape(-1,3).astype(np.int64)
    if any(poly.GetPointData().GetArray(name) is None for name in ('U','p')):
        raise ValueError('本次体网格采样丢失U/p字段')
    u=vtk_to_numpy(poly.GetPointData().GetArray('U')).astype(float)
    pressure=vtk_to_numpy(poly.GetPointData().GetArray('p')).astype(float)
    if u.shape!=(len(p),3) or pressure.shape!=(len(p),) or not all(np.isfinite(x).all() for x in (p,u,pressure)):
        raise ValueError('抽取后字段长度、维度或有限值不符')
    if f.min()<0 or f.max()>=len(p) or len(p)>1_000_000 or len(f)>2_000_000:
        raise ValueError('抽取后索引无效或超过显示规模；不能静默抽稀流场')
    xyz=p[f]
    if np.any(np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)<=1e-20):
        raise ValueError('抽取后存在退化三角面')
    return p,f,u,pressure


def _surface(grid):
    surface=vtk.vtkDataSetSurfaceFilter();surface.SetInputData(grid);surface.Update()
    triangle=vtk.vtkTriangleFilter();triangle.SetInputConnection(surface.GetOutputPort())
    triangle.PassVertsOff();triangle.PassLinesOff();triangle.Update();poly=triangle.GetOutput()
    return _poly_arrays(poly)


def _fields(velocity,pressure,rho):
    return {'velocity':{'unit':'m/s','association':'point','values':velocity.tolist()},
            'pressure':{'unit':'Pa','association':'point','values':(rho*pressure).tolist(),
                'quantity':'static','reference':'gauge','source_unit':'m2/s2','source_field':'p',
                'rho_kg_m3':rho,'conversion':'p_Pa = rho_kg_m3 * p_kinematic'},'turbulence_intensity':None}


def _interior_slices(grid,rho,source_sha):
    bounds=grid.GetBounds();center=np.array([(bounds[2*i]+bounds[2*i+1])/2 for i in range(3)])
    slices=[]
    for axis,name in enumerate(('x','y','z')):
        normal=np.eye(3)[axis]
        plane=vtk.vtkPlane();plane.SetOrigin(*center);plane.SetNormal(*normal)
        cutter=vtk.vtkCutter();cutter.SetInputData(grid);cutter.SetCutFunction(plane);cutter.Update()
        triangle=vtk.vtkTriangleFilter();triangle.SetInputConnection(cutter.GetOutputPort());triangle.Update()
        if not triangle.GetOutput().GetNumberOfPolys():continue
        p,f,u,pressure=_poly_arrays(triangle.GetOutput())
        slices.append({'id':name,'label':name.upper()+' 轴中部剖面',
            'plane_lps_mm':(center*1000).tolist(),'normal_lps':normal.tolist(),
            'axis':name,'position_lps_mm':float(center[axis]*1000),'source_vtu_sha256':source_sha,
            'sampling':'vtkCutter linear interpolation of this volume VTU point field; no synthetic field',
            'geometry':{'vertices':(p*1000).ravel().tolist(),'indices':f.ravel().tolist()},
            'fields':_fields(u,pressure,rho)})
    if not slices:raise ValueError('本次VTU无法得到任何内部中心剖面；不能只以外壁冒充腔内流场')
    return slices


def export_patient_trial_viewer(directory,report,asset,data):
    directory=Path(directory).resolve()
    job=data.get('id');case=data.get('case_id')
    if not isinstance(job,str) or not JOB_RE.fullmatch(job) or data.get('action')!='run_patient_engineering':
        raise ValueError('工程流场必须绑定本次患者工程任务')
    if (report.get('schema')!='nasal_patient_engineering_trial/v1' or report.get('case_id')!=case
            or report.get('patient_data') is not True or report.get('engineering_trial') is not True
            or report.get('backend')!='real_openfoam_v1912' or report.get('clinical_validation')!='not_validated'
            or report.get('execution_status') not in ('completed','failed')
            or report.get('numerical_validation') not in ('unchecked','failed')):
        raise ValueError('患者工程报告身份或未验证状态不符')
    fingerprint=report.get('input_fingerprint',{})
    if not all(isinstance(fingerprint.get(k),str) and SHA_RE.fullmatch(fingerprint[k])
               for k in ('admission_sha256','config_sha256')):
        raise ValueError('本次工程输入缺内容绑定')
    trials=report.get('scenario',{}).get('evaluations')
    if not isinstance(trials,list) or not trials:
        raise ValueError('本次任务没有实际评估记录')
    last=trials[-1];evaluation=PurePosixPath(last.get('case','')).name
    if not re.fullmatch(r'eval_[0-9]{3,}',evaluation):
        raise ValueError('最终评估目录身份无效')
    # Runner layout is export/<job>/evaluations/eval_NNN; never use an older
    # source preview or a different evaluation when this one is missing.
    base=(directory/'export'/job/'evaluations'/evaluation).resolve()
    if not base.is_relative_to(directory/'export'/job) or not base.is_dir():
        raise ValueError('本次最终评估目录缺失')
    sources=list((base/'VTK').rglob('internal.vtu'))
    if len(sources)!=1:
        raise ValueError('本次最终评估VTU缺失或不唯一')
    source=sources[0].resolve()
    if not source.is_relative_to(base):raise ValueError('VTU越出本次评估目录')
    time_text=source.parent.name.rsplit('_',1)[-1]
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',time_text):
        raise ValueError('VTU未记录可定位的实际字段时间')
    field_time=float(time_text)
    times=[x for x in base.iterdir() if x.is_dir() and re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',x.name)
           and float(x.name)==field_time]
    if not math.isfinite(field_time) or len(times)!=1:
        raise ValueError('VTU字段时间没有唯一原始字段目录')
    p_path,u_path=times[0]/'p',times[0]/'U'
    _dimensions(p_path,[0,2,-2,0,0,0,0]);_dimensions(u_path,[0,1,-1,0,0,0,0])
    config_path=base/'config.json';config=_read(config_path);geometry=config.get('geometry',{})
    if (geometry.get('kind')!='patient' or geometry.get('case_id')!=case or geometry.get('coordinate_system')!='LPS'
            or geometry.get('units')!='mm' or geometry.get('solver_units')!='m' or geometry.get('scale_to_m')!=.001
            or not SHA_RE.fullmatch(str(geometry.get('sha256',''))) or _sha(config_path)!=fingerprint['config_sha256']):
        raise ValueError('本次配置的患者身份、LPS/长度单位或内容指纹不符')
    physics=config.get('physics',{});rho=physics.get('rho_kg_m3')
    if isinstance(rho,bool) or not isinstance(rho,(int,float)) or not math.isfinite(rho) or rho<=0:
        raise ValueError('本次rho必须是明确正数，不能用参考默认值')
    bound_paths=(source,config_path,p_path,u_path)
    source_hashes={str(path):_sha(path) for path in bound_paths}
    grid,association=_grid(source)
    points,faces,velocity,pressure=_surface(grid)
    slices=_interior_slices(grid,rho,source_hashes[str(source)])
    if source_hashes!={str(path):_sha(path) for path in bound_paths}:
        raise ValueError('读取流场期间本次VTU/配置/字段发生变化')
    numerical='failed' if report['execution_status']=='failed' or report['numerical_validation']=='failed' or last.get('status')=='failed' else 'unchecked'
    prefix='/simulation-assets/'+job+'/'
    result={'schema':RESULT_SCHEMA,'type':TYPE,'job_id':job,'case_id':case,'patient_data':True,
            'engineering_trial':True,'clinical_validation':'not_validated','numerical_validation':numerical,
            'geometry':geometry,'physics':physics,'execution_status':report['execution_status'],
            'diagnostics':last.get('diagnostics',{}),'input_fingerprint':fingerprint,
            'provenance':{'method':'cfd_solver','solver_name':'simpleFoam','solver_version':'OpenFOAM-v1912',
                'job_id':job,'case_id':case,'evaluation':evaluation,'field_time':time_text,
                'native_case':last['case'],'source_vtu_sha256':source_hashes[str(source)],'config_sha256':source_hashes[str(config_path)],
                'p_file_sha256':source_hashes[str(p_path)],'U_file_sha256':source_hashes[str(u_path)],
                'display_mapping':'LPS axes unchanged; coordinates m to mm once; velocity components unchanged',
                'sampling':'outer boundary of this evaluation volume VTU; no old preview geometry',
                'source_association':association,'source_vtu_url':prefix+'patient-final-internal.vtu'},
            'fields':_fields(velocity,pressure,rho),
            'turbulence_intensity_status':'not_applicable_laminar' if physics.get('turbulence_model')=='laminar' else 'not_exported'}
    note='患者工程试算，非临床；数值状态 '+numerical+'。内部剖面来自本次VTU；外壁速度不能代表腔内流速。未完成网格无关性/临床验证。'
    mesh={'schema':MESH_SCHEMA,'case':case,'job_id':job,'status':'unvalidated_patient_engineering_diagnostic',
          'coordinate_system':'LPS','unit':'mm','display_geometry_only':True,'cfd_ready':False,
          'geometry':{'vertices':(points*1000).ravel().tolist(),'indices':faces.ravel().tolist()},'result':result,
          'interior_slices':slices}
    viewer={'schema':'nasal_workspace/v1','patient_scan_count':0,'patient_cfd_results':0,
            'cases':[{'id':job,'case_id':case,'job_id':job,'label':case+' · 本次患者工程流场',
                      'type':TYPE,'mesh_url':prefix+'viewer_mesh.json','note':note,'landmarks':[]}]}
    # All validation is complete before making any manifest visible.
    _write(directory/'viewer_mesh.json',mesh);_write(directory/'viewer.json',viewer)
    asset('patient-final-internal.vtu',source,'本次患者工程试算原始VTU（非临床）')
    asset('patient-final-config.json',config_path,'本次患者工程试算配置与单位')
    asset('viewer_mesh.json',directory/'viewer_mesh.json','本次患者工程诊断表面字段（非临床）')
    asset('viewer.json',directory/'viewer.json','本次患者工程诊断三维索引')
    data['artifacts'].append({'name':'viewer','label':'三维工程诊断 · 非临床 · '+numerical,
                              'url':'/viewer/index.html?manifest='+prefix+'viewer.json'})
    return {'schema':RESULT_SCHEMA,'points':len(points),'triangles':len(faces),'case_id':case,'job_id':job,
            'source_vtu_sha256':result['provenance']['source_vtu_sha256'],'field_time':time_text,
            'internal_slice_ids':[s['id'] for s in slices],
            'numerical_validation':numerical,'clinical_validation':'not_validated','formal_patient_result':False}
