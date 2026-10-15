"""Read-only independent content/provenance audit, no admission text as proof."""
import hashlib,json,pathlib,re,sys
ROOT=pathlib.Path(__file__).resolve().parents[2];OUT=pathlib.Path(__file__).resolve().parent
BASE=pathlib.Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering')
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
d=read(BASE/'admission.json');evidence=read(ROOT/'outputs/T-021/b15_input_fingerprint.json')
assert d==evidence and d['case_id']=='b15_engineering'
assert d['current_source_binding']=={'kind':'frozen_standalone_sample','sample_id':'b15_engineering'}
files={}
for key,x in d['frozen_sources'].items():
    file=(BASE/x['file']).resolve();assert file.is_relative_to(BASE.resolve())
    files[key]={'path':str(file),'actual_sha256':sha(file),'declared_sha256':x['sha256']}
    assert files[key]['actual_sha256']==x['sha256']
surface=BASE/d['surface']['file'];assert sha(surface)==d['surface']['sha256']
configfile=BASE/d['config_file'];config=read(configfile);assert sha(configfile)==d['config_sha256']
template=BASE/d['template_dir'];manifest=read(template/'case_manifest.json')
actual_mesh={p.relative_to(template/'constant/polyMesh').as_posix():sha(p) for p in sorted((template/'constant/polyMesh').rglob('*')) if p.is_file()}
assert {'points','faces','owner','neighbour','boundary'}<=actual_mesh.keys()
assert actual_mesh==d['mesh_fingerprint']
native=pathlib.Path(r'\\wsl.localhost\Ubuntu-22.04\home\lenovo2\patient_cfd\t004_diag')
native_mesh={p.relative_to(native/'constant/polyMesh').as_posix():sha(p) for p in sorted((native/'constant/polyMesh').rglob('*')) if p.is_file()}
assert native_mesh==actual_mesh==d['source_native_polyMesh_fingerprint']
export=read(BASE/d['frozen_sources']['surface_export']['file'])
conversion=read(BASE/d['frozen_sources']['mesh_conversion']['file'])
repair=read(BASE/d['frozen_sources']['mesh_repair']['file'])
assert export['source_sha256']==d['frozen_sources']['source_vtp']['sha256']
assert export['stl_sha256']==sha(surface)==conversion['source_sha256']
assert conversion['output_sha256']==repair['source_sha256']
assert repair['output_sha256']==d['source_mesh_sha256']==d['frozen_sources']['source_msh']['sha256']
assert config['geometry']['kind']=='patient' and config['geometry']['case_id']==d['case_id']
assert config['geometry']['sha256']==d['surface']['sha256']==manifest['final_surface_sha256']
assert manifest['patient_case_id']==d['case_id'] and manifest['source_mesh_sha256']==d['source_mesh_sha256']
assert config['geometry']['review']['status']!='confirmed'
auth=read(template/'engineering_authorization.json')
assert auth['case_id']==d['case_id'] and auth['scope']=='isolated_engineering_trial_not_clinical'
assert auth['surface_sha256']==d['surface']['sha256'] and auth['config_sha256']==d['config_sha256']
assert auth['mesh_fingerprint']==actual_mesh and auth['source_mesh_sha256']==d['source_mesh_sha256']
record=template/auth['record_file'];assert sha(record)==auth['record_sha256']
assert d['engineering_authorization']=={**auth,'record_file':'template/'+auth['record_file']}
meshlog=(BASE/d['check_mesh_log']).read_text(encoding='utf-8-sig')
assert 'Failed 2 mesh checks' in meshlog
sys.path.insert(0,str(ROOT/'work/lib'))
from patient_cfd_admission import admission,validate_engineering_authorization
gate=admission(d['case_id'],BASE.parent);assert gate['passed'] and gate['clinical_validation']=='not_validated'
assert gate['clinical_readiness_reasons']
allowed=validate_engineering_authorization(template,configfile,template/'engineering_authorization.json')
assert allowed['allowed'] and allowed['clinical_validation']=='not_validated' and allowed['readiness_warnings']
report={'passed':True,'scope':'b15 standalone engineering package identity/provenance; not p0/p3/uploaded patient, no new solve',
        'package_id':d['case_id'],'source_files':files,'actual_mesh_fingerprint':actual_mesh,
        'native_source_polyMesh_matches':True,'surface_sha256':sha(surface),'config_sha256':sha(configfile),
        'admission_sha256':sha(BASE/'admission.json'),'authorization_sha256':sha(template/'engineering_authorization.json'),
        'original_export_source':export['source'],'original_mesh_failed_checks':2,
        'clinical_validation':'not_validated','clinical_readiness_reasons':gate['clinical_readiness_reasons'],
        'package_is_only_frozen_inputs':not any((template/x).exists() for x in ['VTK','postProcessing','log.simpleFoam','run_status.json']),
        'command':'python outputs/T-023/audit_b15_package.py'}
assert report['package_is_only_frozen_inputs']
target=OUT/'b15_package_result.json';assert not target.exists();target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'mesh_files':len(actual_mesh),'source_files':len(files),'clinical_validation':'not_validated','failed_checks_preserved':2},ensure_ascii=False))
