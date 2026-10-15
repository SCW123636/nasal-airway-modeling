"""Known VTU answers: synthetic component fixtures, never patient results."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk
from patient_cfd_viewer import export_patient_trial_viewer,_interior_slices,_poly_arrays


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture(root, *, cell=False):
    root=Path(root);job='s_'+'a'*24;case='synthetic_component_fixture'
    base=root/'export'/job/'evaluations/eval_001';(base/'VTK/fixture_17').mkdir(parents=True)
    (base/'17').mkdir()
    for name,dims in (('p','0 2 -2 0 0 0 0'),('U','0 1 -1 0 0 0 0')):
        (base/'17'/name).write_text('FoamFile { object '+name+'; }\ndimensions ['+dims+'];\n',encoding='utf-8')
    config={'geometry':{'kind':'patient','case_id':case,'source_file':'synthetic_fixture.stl','sha256':'b'*64,
                        'coordinate_system':'LPS','units':'mm','solver_units':'m','scale_to_m':.001,
                        'review':{'status':'pending'}},
            'physics':{'rho_kg_m3':1.25,'mu_Pa_s':1.8e-5,'turbulence_model':'laminar'}}
    (base/'config.json').write_text(json.dumps(config),encoding='utf-8')
    points=np.array([[.001,.002,.003],[.003,.002,.003],[.001,.006,.003],[.001,.002,.009]],float)
    velocity=np.array([[1.,2,3],[4,5,6],[7,8,9],[10,11,12]])
    pressure=np.array([1.,2,3,4])
    grid=vtk.vtkUnstructuredGrid();vp=vtk.vtkPoints();vp.SetData(numpy_to_vtk(points,deep=True));grid.SetPoints(vp)
    tetra=vtk.vtkTetra()
    for i in range(4):tetra.GetPointIds().SetId(i,i)
    grid.InsertNextCell(tetra.GetCellType(),tetra.GetPointIds())
    for key,value in (('U',velocity[:1] if cell else velocity),('p',pressure[:1] if cell else pressure)):
        array=numpy_to_vtk(value,deep=True);array.SetName(key)
        (grid.GetCellData() if cell else grid.GetPointData()).AddArray(array)
    source=base/'VTK/fixture_17/internal.vtu'
    writer=vtk.vtkXMLUnstructuredGridWriter();writer.SetFileName(str(source));writer.SetInputData(grid);assert writer.Write()==1
    report={'schema':'nasal_patient_engineering_trial/v1','case_id':case,'patient_data':True,'engineering_trial':True,
            'backend':'real_openfoam_v1912','clinical_validation':'not_validated','numerical_validation':'unchecked',
            'execution_status':'failed','scenario':{'result':None,'evaluations':[{'case':'/home/fixture/evaluations/eval_001',
                'status':'failed','diagnostics':{'residual_max':.1}}]},
            'input_fingerprint':{'admission_sha256':'c'*64,'config_sha256':digest(base/'config.json'),
                                 'code_sha256':{},'current_source_binding':{'kind':'synthetic_fixture'}}}
    data={'id':job,'case_id':case,'action':'run_patient_engineering','artifacts':[],'asset_paths':{}}
    def asset(name,path,label):
        relative=Path(path).resolve().relative_to(root.resolve())
        data['asset_paths'][name]=relative.as_posix()
        data['artifacts'].append({'name':name,'url':'/simulation-assets/'+job+'/'+name,'label':label})
    return base,source,report,data,asset,points,velocity,pressure


class PatientViewerTests(unittest.TestCase):
    def test_float32_source_near_vertex_cut_retains_known_intersections(self):
        # Source: actual-vtu-repair/precision_control_source.json, source cell
        # 175819, VTU SHA256 71967ea40c6e006a791a0fa1eac43d63f615fd92c5f64c45fa74930d948cac11.
        # Two unused bounds-only points isolate the real source's center plane;
        # the only cell remains the extracted, valid four-point tetrahedron.
        points=np.array([[.020625699311494827,-.05703200027346611,-.026962999254465103],
            [.020373599603772163,-.056787800043821335,-.026607800275087357],
            [.020331399515271187,-.057145100086927414,-.0271914005279541],
            [.020198699086904526,-.05732410028576851,-.026758700609207153],
            [-.014042300172150135,-.11049900203943253,-.05031510069966316],
            [.02502020075917244,-.01674880087375641,-.0029005000833421946]],dtype=np.float32)
        xyz=points.astype(float);grid=vtk.vtkUnstructuredGrid();vp=vtk.vtkPoints();vp.SetData(numpy_to_vtk(points,deep=True));grid.SetPoints(vp)
        tetra=vtk.vtkTetra()
        for i in range(4):tetra.GetPointIds().SetId(i,i)
        grid.InsertNextCell(tetra.GetCellType(),tetra.GetPointIds())
        u=np.column_stack((xyz[:,0]+2*xyz[:,1],xyz[:,1]+3*xyz[:,2],xyz[:,2]+4*xyz[:,0]))
        p=1+2*xyz[:,0]-xyz[:,1]+3*xyz[:,2]
        for name,values in (('U',u),('p',p)):
            array=numpy_to_vtk(values,deep=True);array.SetName(name);grid.GetPointData().AddArray(array)
        bounds=grid.GetBounds();center=np.array([(bounds[2*i]+bounds[2*i+1])/2 for i in range(3)])
        plane=vtk.vtkPlane();plane.SetOrigin(*center);plane.SetNormal(0,0,1)
        old=vtk.vtkCutter();old.SetInputData(grid);old.SetCutFunction(plane);old.Update()
        old_xyz=np.array([old.GetOutput().GetPoint(i) for i in range(3)])
        self.assertEqual(np.linalg.norm(np.cross(old_xyz[1]-old_xyz[0],old_xyz[2]-old_xyz[0])),0)
        expected=[]
        for a,b in ((0,1),(0,2),(0,3),(1,2),(1,3),(2,3)):
            sa,sb=xyz[a,2]-center[2],xyz[b,2]-center[2]
            if sa*sb<0:
                t=-sa/(sb-sa);expected.append((1-t)*xyz[a]+t*xyz[b])
        self.assertEqual(len(expected),3)
        slices=_interior_slices(grid,1.25,'d'*64);cut=next(value for value in slices if value['id']=='z')
        actual=np.array(cut['geometry']['vertices']).reshape(-1,3)/1000
        self.assertEqual((len(actual),len(cut['geometry']['indices'])//3),(3,1))
        for point in actual:self.assertLess(np.min(np.linalg.norm(np.array(expected)-point,axis=1)),1e-14)
        self.assertGreater(np.linalg.norm(np.cross(actual[1]-actual[0],actual[2]-actual[0])),1e-20)
        expected_u=np.column_stack((actual[:,0]+2*actual[:,1],actual[:,1]+3*actual[:,2],actual[:,2]+4*actual[:,0]))
        expected_p=(1+2*actual[:,0]-actual[:,1]+3*actual[:,2])*1.25
        np.testing.assert_allclose(cut['fields']['velocity']['values'],expected_u,rtol=0,atol=1e-14)
        np.testing.assert_allclose(cut['fields']['pressure']['values'],expected_p,rtol=0,atol=1e-14)

    def test_real_degenerate_and_below_gate_faces_still_rejected(self):
        for name,xyz,accepted in (
            ('collinear',[[0,0,0],[1,0,0],[2,0,0]],False),
            ('below_unchanged_gate',[[0,0,0],[1e-10,0,0],[0,5e-11,0]],False),
            ('above_unchanged_gate',[[0,0,0],[1e-10,0,0],[0,2e-10,0]],True)):
            with self.subTest(name=name):
                poly=vtk.vtkPolyData();points=vtk.vtkPoints();points.SetData(numpy_to_vtk(np.array(xyz,dtype=float),deep=True));poly.SetPoints(points)
                faces=vtk.vtkCellArray();faces.InsertNextCell(3)
                for i in range(3):faces.InsertCellPoint(i)
                poly.SetPolys(faces)
                for key,values in (('U',np.ones((3,3))),('p',np.ones(3))):
                    array=numpy_to_vtk(values,deep=True);array.SetName(key);poly.GetPointData().AddArray(array)
                if accepted:self.assertEqual(len(_poly_arrays(poly)[1]),1)
                else:
                    with self.assertRaisesRegex(ValueError,'退化三角面'):_poly_arrays(poly)

    def test_known_coordinates_components_pressure_and_failed_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            base,source,report,data,asset,points,u,p=fixture(tmp)
            result=export_patient_trial_viewer(tmp,report,asset,data)
            mesh=json.loads((Path(tmp)/'viewer_mesh.json').read_text(encoding='utf-8'))
            viewer=json.loads((Path(tmp)/'viewer.json').read_text(encoding='utf-8'))
            self.assertEqual((result['points'],result['triangles']),(4,4))
            self.assertEqual(result['numerical_validation'],'failed')
            self.assertFalse(result['formal_patient_result'])
            coords=np.array(mesh['geometry']['vertices']).reshape(-1,3)
            for xyz,vel,pressure in zip(coords,mesh['result']['fields']['velocity']['values'],mesh['result']['fields']['pressure']['values']):
                idx=np.flatnonzero(np.all(np.isclose(points*1000,xyz,atol=1e-12),axis=1))
                self.assertEqual(len(idx),1)
                np.testing.assert_array_equal(vel,u[idx[0]])
                self.assertEqual(pressure,p[idx[0]]*1.25)
            self.assertEqual(mesh['result']['provenance']['source_vtu_sha256'],digest(source))
            self.assertEqual(mesh['result']['provenance']['field_time'],'17')
            self.assertEqual(viewer['patient_cfd_results'],0)
            self.assertEqual(viewer['cases'][0]['type'],'patient_engineering_diagnostic')
            self.assertNotIn('idealized',json.dumps(mesh))
            self.assertEqual(mesh['result']['geometry']['review']['status'],'pending')
            self.assertIn('非临床',viewer['cases'][0]['note'])
            self.assertEqual(result['internal_slice_ids'],['x','y','z'])
            center=(points.min(axis=0)+points.max(axis=0))/2
            for axis,slice_data in enumerate(mesh['interior_slices']):
                with self.subTest(axis=slice_data['id']):
                    self.assertEqual(slice_data['source_vtu_sha256'],digest(source))
                    np.testing.assert_allclose(slice_data['plane_lps_mm'],center*1000,atol=1e-12)
                    np.testing.assert_array_equal(slice_data['normal_lps'],np.eye(3)[axis])
                    coords_m=np.array(slice_data['geometry']['vertices']).reshape(-1,3)/1000
                    np.testing.assert_allclose(coords_m[:,axis],center[axis],atol=1e-9)
                    bary=(coords_m-np.array([.001,.002,.003]))/np.array([.002,.004,.006])
                    expected_pressure=(1+bary@np.array([1,2,3]))*1.25
                    expected_velocity=np.array([1,2,3])+bary@np.array([[3,3,3],[6,6,6],[9,9,9]])
                    np.testing.assert_allclose(slice_data['fields']['pressure']['values'],expected_pressure,atol=1e-6)
                    np.testing.assert_allclose(slice_data['fields']['velocity']['values'],expected_velocity,atol=1e-6)
                    self.assertEqual(slice_data['fields']['pressure']['rho_kg_m3'],1.25)
                    self.assertEqual(slice_data['fields']['velocity']['unit'],'m/s')

    def test_cell_fields_are_explicitly_averaged_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            _,_,report,data,asset,_,_,_=fixture(tmp,cell=True)
            export_patient_trial_viewer(tmp,report,asset,data)
            mesh=json.loads((Path(tmp)/'viewer_mesh.json').read_text(encoding='utf-8'))
            self.assertEqual(mesh['result']['fields']['velocity']['values'],[[1.,2.,3.]]*4)
            self.assertEqual(mesh['result']['provenance']['source_association'],{'U':'cell_to_point_average','p':'cell_to_point_average'})
            for slice_data in mesh['interior_slices']:
                self.assertEqual(slice_data['fields']['velocity']['values'],[[1.,2.,3.]]*3)
                self.assertEqual(slice_data['fields']['pressure']['values'],[1.25]*3)

    def test_wrong_dimensions_or_stale_identity_never_publish_manifest(self):
        for kind in ('p','U','rho','axis','config_hash','job','case','last_eval','multiple_vtu','no_field','nonfinite','nonfinite_geometry'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                base,source,report,data,asset,_,_,_=fixture(tmp)
                if kind in ('p','U'):(base/'17'/kind).write_text('dimensions [1 0 0 0 0 0 0];',encoding='utf-8')
                elif kind in ('rho','axis'):
                    path=base/'config.json';config=json.loads(path.read_text())
                    if kind=='rho':config['physics']['rho_kg_m3']=0
                    else:config['geometry']['coordinate_system']='RAS'
                    path.write_text(json.dumps(config));report['input_fingerprint']['config_sha256']=digest(path)
                elif kind=='config_hash':report['input_fingerprint']['config_sha256']='d'*64
                elif kind=='job':data['id']='p0'
                elif kind=='case':report['case_id']='some_other_patient'
                elif kind=='last_eval':report['scenario']['evaluations'].append({'case':'/home/fixture/evaluations/eval_002'})
                elif kind=='multiple_vtu':
                    second=source.parent.parent/'fixture_18';second.mkdir();(second/'internal.vtu').write_bytes(source.read_bytes())
                else:
                    reader=vtk.vtkXMLUnstructuredGridReader();reader.SetFileName(str(source));reader.Update();grid=reader.GetOutput()
                    if kind=='no_field':grid.GetPointData().RemoveArray('U')
                    elif kind=='nonfinite_geometry':grid.GetPoints().SetPoint(0,float('nan'),.002,.003)
                    else:grid.GetPointData().GetArray('p').SetTuple1(0,float('nan'))
                    writer=vtk.vtkXMLUnstructuredGridWriter();writer.SetFileName(str(source));writer.SetInputData(grid);writer.Write()
                with self.assertRaises(ValueError):export_patient_trial_viewer(tmp,report,asset,data)
                self.assertFalse((Path(tmp)/'viewer.json').exists())
                self.assertFalse(data['artifacts'])


if __name__=='__main__':unittest.main()
