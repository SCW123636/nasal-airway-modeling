"""Fresh affine known answer on six tetrahedra, separate from author fixture."""
import hashlib,json,pathlib,sys,traceback
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent/'t024-independent-affine'
sys.path.insert(0,str(ROOT/'work/lib'))
from patient_cfd_viewer import export_patient_trial_viewer
from audit_patient_field_arrays import audit,read,sha
assert not OUT.exists();OUT.mkdir()
job='s_'+'b'*24;case='fresh_synthetic_affine_control';base=OUT/'export'/job/'evaluations/eval_001'
(base/'VTK/affine_29').mkdir(parents=True);(base/'29').mkdir()
code_sha=sha(ROOT/'work/lib/patient_cfd_viewer.py')
try:
    corners=np.array([[0,0,0],[1,0,0],[1,1,0],[0,1,0],[0,0,1],[1,0,1],[1,1,1],[0,1,1]],float)
    p=np.array([-.031,.022,-.014])+corners*np.array([.008,.012,.018])
    matrix=np.array([[50,-10,2],[-20,4,5],[3,22,-8.]])
    intercept=np.array([1.,-.2,.7]);u=intercept+p@matrix;q=7+p@np.array([100.,200.,-50.]);rho=1.19
    g=vtk.vtkUnstructuredGrid();vp=vtk.vtkPoints();vp.SetData(numpy_to_vtk(p,deep=True));g.SetPoints(vp)
    for ids in [[0,1,2,6],[0,2,3,6],[0,3,7,6],[0,7,4,6],[0,4,5,6],[0,5,1,6]]:
        t=vtk.vtkTetra()
        for i,v in enumerate(ids):t.GetPointIds().SetId(i,v)
        g.InsertNextCell(t.GetCellType(),t.GetPointIds())
    for name,array in [('U',u),('p',q)]:
        a=numpy_to_vtk(array,deep=True);a.SetName(name);g.GetPointData().AddArray(a)
    source=base/'VTK/affine_29/internal.vtu';w=vtk.vtkXMLUnstructuredGridWriter();w.SetFileName(str(source));w.SetInputData(g);assert w.Write()==1
    config={'geometry':{'kind':'patient','case_id':case,'coordinate_system':'LPS','units':'mm','solver_units':'m',
                        'scale_to_m':.001,'sha256':'3'*64,'review':{'status':'pending'}},'physics':{'rho_kg_m3':rho,'turbulence_model':'laminar'}}
    (base/'config.json').write_text(json.dumps(config),encoding='utf-8')
    for name,dims in [('p','0 2 -2 0 0 0 0'),('U','0 1 -1 0 0 0 0')]:
        (base/'29'/name).write_text('dimensions ['+dims+'];',encoding='utf-8')
    report={'schema':'nasal_patient_engineering_trial/v1','case_id':case,'patient_data':True,'engineering_trial':True,
            'backend':'real_openfoam_v1912','clinical_validation':'not_validated','numerical_validation':'unchecked',
            'execution_status':'failed','input_fingerprint':{'config_sha256':sha(base/'config.json'),'admission_sha256':'4'*64},
            'scenario':{'evaluations':[{'case':'/home/fresh_control/evaluations/eval_001','status':'failed'}]}}
    data={'id':job,'case_id':case,'action':'run_patient_engineering','artifacts':[]}
    assets=[]
    def asset(name,path,label):assets.append({'name':name,'path':str(path),'sha256':sha(path)})
    exported=export_patient_trial_viewer(OUT,report,asset,data);mesh=read(OUT/'viewer_mesh.json');manifest=read(OUT/'viewer.json')
    checks=audit(mesh,manifest,source,config,job,case)
    assert {s['id'] for s in mesh['interior_slices']}==set('xyz')
    # Closed-form field values at every displayed point, independent of VTK.
    for name,geometry,fields in [('surface',mesh['geometry'],mesh['result']['fields'])]+[(s['axis'],s['geometry'],s['fields']) for s in mesh['interior_slices']]:
        xyz=np.asarray(geometry['vertices']).reshape(-1,3)/1000
        np.testing.assert_allclose(fields['velocity']['values'],intercept+xyz@matrix,rtol=0,atol=1e-6)
        np.testing.assert_allclose(fields['pressure']['values'],(7+xyz@np.array([100,200,-50]))*rho,rtol=0,atol=1e-6)
    assert mesh['result']['numerical_validation']=='failed' and mesh['result']['geometry']['review']['status']=='pending'
    assert sha(ROOT/'work/lib/patient_cfd_viewer.py')==code_sha
    final={'passed':True,'production_sha256':code_sha,'fixture':'Synthetic six-tetra affine volume, not patient CFD',
           'source_vtu_sha256':sha(source),'known_closed_form_fields':'U=[1,-.2,.7]+xyz_m@matrix; p_Pa=1.19*(7+xyz_m@[100,200,-50])',
           'audit':checks,'exported':exported,'asset_hashes':assets}
except Exception:
    final={'passed':False,'failure':traceback.format_exc(),'production_sha256':code_sha};raise
finally:
    (OUT/'verification.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(final,ensure_ascii=False))
