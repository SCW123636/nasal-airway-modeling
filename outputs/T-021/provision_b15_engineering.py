"""Reproduce the frozen engineering input package; big inputs stay in runtime."""
from pathlib import Path
import json
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'work/lib'))
from patient_cfd_admission import sha256, mesh_fingerprint, admission
from ct_case_pipeline import write_json

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('C:/ts_work/mesh_tools/patient_mesh_20261013')
NATIVE = Path(r'\\wsl.localhost\Ubuntu-22.04\home\lenovo2\patient_cfd\t004_diag')
TARGET = Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering')
if TARGET.exists():
    raise SystemExit('input package already exists: preserve it; create a new version deliberately')
export = json.loads((SOURCE / 'b15_patches_ascii.export.json').read_text())
mesh_record = json.loads((SOURCE / 'b15_patient_maxh1.msh.mesh.json').read_text())
repair = json.loads((SOURCE / 'b15_patient_maxh1_repaired.repair.json').read_text())
native_manifest = json.loads((NATIVE / 'case_manifest.json').read_text())
assert sha256(SOURCE / 'b15_patches_ascii.stl') == export['stl_sha256'] == mesh_record['source_sha256']
assert sha256(Path(export['source'])) == export['source_sha256']
assert sha256(SOURCE / 'b15_patient_maxh1.msh') == mesh_record['output_sha256'] == repair['source_sha256']
mesh_hash = sha256(SOURCE / 'b15_patient_maxh1_repaired.msh')
assert mesh_hash == repair['output_sha256'] == native_manifest['surface']['source_sha256']
TARGET.mkdir(parents=True)
template = TARGET / 'template'
for folder in ('0','constant','system'):
    shutil.copytree(NATIVE / folder,template / folder)
source_mesh = mesh_fingerprint(NATIVE)
assert mesh_fingerprint(template) == source_mesh
tri = template / 'constant/triSurface';tri.mkdir(exist_ok=True)
shutil.copy2(SOURCE / 'b15_patches_ascii.stl',tri / 'surface.stl')
sources = TARGET / 'sources';sources.mkdir()
frozen = {}
for name,path in [('source_vtp',Path(export['source'])),('surface_export',SOURCE / 'b15_patches_ascii.export.json'),
                  ('source_msh',SOURCE / 'b15_patient_maxh1_repaired.msh'),('mesh_conversion',SOURCE / 'b15_patient_maxh1.msh.mesh.json'),
                  ('mesh_repair',SOURCE / 'b15_patient_maxh1_repaired.repair.json')]:
    destination = sources / path.name
    shutil.copy2(path,destination)
    frozen[name] = {'file':destination.relative_to(TARGET).as_posix(),'sha256':sha256(destination)}
config = json.loads((ROOT / 'work/07_cfd_pipeline/configs/total_flow_laminar_medium.json').read_text())
config['config_id'] = 'b15_engineering_common_pressure_20261015'
config['geometry'].update(case_id='b15_engineering',source_file='constant/triSurface/surface.stl',sha256=export['stl_sha256'])
config['mesh'].update(level='existing_b15_engineering_maxh1',bulk_target_mm=1.)
# Adapter has real reference evidence; clinical readiness remains pending.
config['solver_adapter'].update(status='implemented_and_verified',name='real_openfoam_common_pressure_reference_verified',version='1.0.0')
config['notes'] += ['Frozen b15 engineering example, not p0/p3 or an uploaded case.',
                    'Existing mesh has Failed 2 mesh checks; surface optimisation cap deviations and six-cell gap resolution are not accuracy-certified.',
                    'This uses the user-approved M1/M2 engineering trial branch. Clinical validation remains absent.']
write_json(template / 'config.json',config)
control = template / 'system/controlDict'
text = control.read_text()
import re
text = re.sub(r'\bendTime\s+\S+;', 'endTime 1500;', text)
control.write_text(text,encoding='ascii')
native_manifest.update(patient_case_id='b15_engineering',final_surface_sha256=export['stl_sha256'],source_mesh_sha256=mesh_hash,
                       clinical_validation='not_validated',engineering_input_provenance='Copied 0/constant/system only from T-006 case; old results excluded')
write_json(template / 'case_manifest.json',native_manifest)
record = template / 'engineering_authorization_record.md'
record.write_text('# Bound engineering trial authorization\n\n'
    'Source: plan/主计划.md M1/M2 user decisions on 2026-10-14 and tasks/T-021.md Lead execution record on 2026-10-15.\n'
    'The user authorized engineering work ahead of final clinical review. Mesh OK and residualControl are recorded risks under the accepted double-track policy.\n'
    'This package is b15_engineering only, frozen and distinct from p0/p3/uploads. It authorizes a new isolated trial, not clinical accuracy or patient split conclusions.\n'
    'Original evidence: outputs/T-006/数值复跑_网格vs数值.md, outputs/T-001/患者体网格复验报告.md.\n'
    'Actual baseline source: /home/lenovo2/patient_cfd/t004_diag (read-only copied inputs; no old results or logs reused).\n',encoding='utf-8')
authorization = {'schema':'nasal_bound_engineering_authorization/v1','scope':'isolated_engineering_trial_not_clinical',
    'case_id':'b15_engineering','surface_file':'constant/triSurface/surface.stl','surface_sha256':export['stl_sha256'],
    'source_mesh_sha256':mesh_hash,'mesh_fingerprint':mesh_fingerprint(template),'config_sha256':sha256(template / 'config.json'),
    'record_file':record.name,'record_sha256':sha256(record),'source_record':'plan/主计划.md M1/M2 user decisions 2026-10-14; tasks/T-021.md Lead authorization 2026-10-15'}
write_json(template / 'engineering_authorization.json',authorization)
shutil.copy2(ROOT / 'outputs/T-001/logs/checkMesh.log',TARGET / 'checkMesh.log')
data = {'schema':'nasal_patient_engineering_admission/v1','case_id':'b15_engineering',
    'current_source_binding':{'kind':'frozen_standalone_sample','sample_id':'b15_engineering'},'frozen_sources':frozen,
    'surface':{'file':'template/constant/triSurface/surface.stl','sha256':export['stl_sha256']},
    'template_dir':'template','config_file':'template/config.json','config_sha256':sha256(template / 'config.json'),
    'mesh_fingerprint':mesh_fingerprint(template),'source_mesh_sha256':mesh_hash,'check_mesh_log':'checkMesh.log',
    'engineering_authorization':{**authorization,'record_file':'template/' + record.name},
    'source_native_case':'/home/lenovo2/patient_cfd/t004_diag','source_native_polyMesh_fingerprint':source_mesh,
    'clinical_validation':'not_validated'}
write_json(TARGET / 'admission.json',data)
result = admission('b15_engineering',TARGET.parent)
write_json(ROOT / 'outputs/T-021/b15_input_admission.json',result)
write_json(ROOT / 'outputs/T-021/b15_input_fingerprint.json',data)
print(json.dumps({'passed':result['passed'],'blocking_reasons':result['blocking_reasons'],'path':str(TARGET)},ensure_ascii=False))
