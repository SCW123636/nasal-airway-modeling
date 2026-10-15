"""Independent coordinate/field audit; no production extractor is imported here."""
import hashlib,json,math,pathlib
import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy,numpy_to_vtk

def sha(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
def check_dataset(geometry,fields):
    p=np.asarray(geometry['vertices'],float).reshape(-1,3)
    f=np.asarray(geometry['indices'],np.int64).reshape(-1,3)
    u=np.asarray(fields['velocity']['values'],float);q=np.asarray(fields['pressure']['values'],float)
    assert len(p)>0 and len(f)>0 and u.shape==p.shape and q.shape==(len(p),)
    assert all(np.isfinite(x).all() for x in (p,u,q))
    assert f.min()>=0 and f.max()<len(p)
    assert np.all(np.linalg.norm(np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]]),axis=1)>1e-14)
    assert fields['velocity']['unit']=='m/s' and fields['pressure']['unit']=='Pa'
    assert fields['pressure']['source_unit']=='m2/s2' and fields['pressure']['conversion']=='p_Pa = rho_kg_m3 * p_kinematic'
    return p,f,u,q

def audit(mesh,manifest,source,config,job,case):
    assert mesh['schema']=='patient_engineering_surface/v1' and mesh['coordinate_system']=='LPS' and mesh['unit']=='mm'
    assert mesh['job_id']==job and mesh['case']==case and mesh['cfd_ready'] is False
    assert mesh['result']['schema']=='nasal_patient_engineering_diagnostic/v1'
    r=mesh['result'];pv=r['provenance'];rho=config['physics']['rho_kg_m3']
    assert r['type']=='patient_engineering_diagnostic' and r['patient_data'] is True and r['engineering_trial'] is True
    assert r['clinical_validation']=='not_validated' and r['numerical_validation'] in ('unchecked','failed')
    assert r['job_id']==pv['job_id']==job and r['case_id']==pv['case_id']==case
    assert pv['source_vtu_sha256']==sha(source) and pv['config_sha256']==r['input_fingerprint']['config_sha256']
    assert manifest['patient_cfd_results']==manifest['patient_scan_count']==0
    assert len(manifest['cases'])==1 and manifest['cases'][0]['id']==job
    assert manifest['cases'][0]['type']=='patient_engineering_diagnostic'
    assert manifest['cases'][0]['mesh_url']=='/simulation-assets/'+job+'/viewer_mesh.json'
    assert '非临床' in manifest['cases'][0]['note']
    reader=vtk.vtkXMLUnstructuredGridReader();reader.SetFileName(str(source));reader.Update();g=reader.GetOutput()
    assert g.GetNumberOfPoints()>0 and g.GetNumberOfCells()>0
    expected_assoc={}
    for k in ('U','p'):
        a=g.GetPointData().GetArray(k)
        if a is None:
            assert g.GetCellData().GetArray(k) is not None
            expected_assoc[k]='cell_to_point_average'
        else:expected_assoc[k]='point'
    if 'cell_to_point_average' in expected_assoc.values():
        c=vtk.vtkCellDataToPointData();c.SetInputData(g);c.ProcessAllArraysOff()
        for k,v in expected_assoc.items():
            if v=='cell_to_point_average':c.AddCellDataArray(k)
        c.Update();g=c.GetOutput()
    assert pv['source_association']==expected_assoc
    source_p=vtk_to_numpy(g.GetPoints().GetData()).astype(float)
    source_u=vtk_to_numpy(g.GetPointData().GetArray('U')).astype(float)
    source_q=vtk_to_numpy(g.GetPointData().GetArray('p')).astype(float)
    assert source_u.shape==source_p.shape and source_q.shape==(len(source_p),)
    assert all(np.isfinite(x).all() for x in (source_p,source_u,source_q))
    p,f,u,q=check_dataset(mesh['geometry'],r['fields'])
    assert r['fields']['pressure']['rho_kg_m3']==rho
    # Boundary extraction cannot invent/move points. Match exact coordinates,
    # never closest-neighbour distances; reject duplicate coordinates with
    # inconsistent raw point fields.
    lookup={}
    for i,xyz in enumerate(source_p):
        key=tuple(np.round(xyz,12));prior=lookup.get(key)
        if prior is not None:
            np.testing.assert_allclose(source_u[prior],source_u[i],rtol=0,atol=1e-10)
            np.testing.assert_allclose(source_q[prior],source_q[i],rtol=0,atol=1e-10)
        lookup[key]=i
    ids=np.array([lookup[tuple(np.round(xyz/1000,12))] for xyz in p])
    np.testing.assert_allclose(p,source_p[ids]*1000,rtol=0,atol=1e-9)
    np.testing.assert_allclose(u,source_u[ids],rtol=0,atol=1e-10)
    np.testing.assert_allclose(q,source_q[ids]*rho,rtol=0,atol=1e-9)
    center=(source_p.min(axis=0)+source_p.max(axis=0))/2
    slices=[];assert 1<=len(mesh['interior_slices'])<=3
    assert len({s['id'] for s in mesh['interior_slices']})==len(mesh['interior_slices'])
    for s in mesh['interior_slices']:
        a='xyz'.index(s['axis']);assert s['id']==s['axis']
        assert s['source_vtu_sha256']==sha(source)
        np.testing.assert_allclose(s['plane_lps_mm'],center*1000,rtol=0,atol=1e-9)
        np.testing.assert_array_equal(s['normal_lps'],np.eye(3)[a])
        assert abs(s['position_lps_mm']-center[a]*1000)<1e-9
        sp,sf,su,sq=check_dataset(s['geometry'],s['fields'])
        np.testing.assert_allclose(sp[:,a],center[a]*1000,rtol=0,atol=1e-6)
        assert s['fields']['pressure']['rho_kg_m3']==rho
        # Probe every declared cut vertex against the original volume. This is
        # distinct from the production vtkCutter triangulation/extraction.
        points=vtk.vtkPoints();points.SetData(numpy_to_vtk(sp/1000,deep=True))
        targets=vtk.vtkPolyData();targets.SetPoints(points)
        probe=vtk.vtkProbeFilter();probe.SetInputData(targets);probe.SetSourceData(g)
        probe.ComputeToleranceOff();probe.SetTolerance(1e-9);probe.Update();sample=probe.GetOutput()
        valid=vtk_to_numpy(sample.GetPointData().GetArray('vtkValidPointMask')).astype(bool)
        assert valid.all(),(s['axis'],'unlocated raw-volume sample points',int((~valid).sum()))
        pu=vtk_to_numpy(sample.GetPointData().GetArray('U')).astype(float)
        pq=vtk_to_numpy(sample.GetPointData().GetArray('p')).astype(float)*rho
        np.testing.assert_allclose(su,pu,rtol=2e-6,atol=2e-7)
        np.testing.assert_allclose(sq,pq,rtol=2e-6,atol=2e-6)
        slices.append({'axis':s['axis'],'points':len(sp),'triangles':len(sf),'raw_probe_valid_points':int(valid.sum()),
                       'max_velocity_difference_m_s':float(np.max(np.abs(su-pu))),
                       'max_pressure_difference_pa':float(np.max(np.abs(sq-pq)))})
    return {'passed':True,'source_points':len(source_p),'source_cells':g.GetNumberOfCells(),
            'surface_points_exact_coordinate_matched':len(p),'surface_triangles':len(f),
            'source_vtu_sha256':sha(source),'source_association':expected_assoc,'slices':slices,
            'numerical_validation':r['numerical_validation'],'clinical_validation':r['clinical_validation'],
            'scope':'Identity/units/coordinates/fields only; no numerical or clinical acceptance'}
