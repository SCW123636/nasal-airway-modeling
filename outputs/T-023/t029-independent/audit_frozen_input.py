"""Independent byte/semantic comparison; does not import production or build inputs."""
from pathlib import Path
import copy
import datetime as dt
import difflib
import hashlib
import json
import re

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=Path('C:/ts_work/project_cases/patient_cfd_inputs/b15_engineering')
NEW=OLD.with_name('b15_engineering_t029a')


def read(p): return json.loads(Path(p).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def files(root): return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
def write_once(name,data):
    with (HERE/name).open('x',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def main():
    producer=ROOT/'outputs/T-029/t029a_source_freeze.json'
    input_freeze=ROOT/'outputs/T-029/t029a_input_freeze.json'
    sf=read(producer); inf=read(input_freeze)
    assert sha(producer)=='5f8137c43c6ff324f8f679de22a4ec1557a7bfbc562e520bf6d50bb09c1497bc'
    assert sha(input_freeze)==sf['input_freeze_sha256']=='e70371c3f9bf1093031fc60bb0420cc517272f2e92b1628cd1b0abf95f92a518'
    assert sha(NEW/'admission.json')==sf['admission_sha256']=='add039ea026012b1b9479c4a19f1e75138b08038a1ccbef88d3317b7ab26ee04'
    code={str((ROOT/p).resolve()):sha(ROOT/p) for p in sf['code_sha256']}
    assert code=={str((ROOT/p).resolve()):h for p,h in sf['code_sha256'].items()}
    a,b=files(OLD),files(NEW)
    assert a==inf['original_files'] and b==inf['trial_files']
    prior=read(HERE/'original-baseline-v1.json')
    assert {str((OLD/p).resolve()):h for p,h in a.items()}==prior['original_input_file_sha256']
    assert set(a)==set(b) and len(a)==len(b)==34
    changes=[p for p in a if a[p]!=b[p]]
    allowed={'admission.json','template/case_manifest.json','template/config.json','template/engineering_authorization.json',
             'template/engineering_authorization_record.md','template/system/controlDict','template/system/fvSchemes'}
    assert set(changes)==allowed
    old_scheme=(OLD/'template/system/fvSchemes').read_text(encoding='utf-8')
    new_scheme=(NEW/'template/system/fvSchemes').read_text(encoding='utf-8')
    original='div(phi,U) bounded Gauss linearUpwind grad(U);'
    replacement='div(phi,U) bounded Gauss upwind;'
    assert old_scheme.count(original)==1 and new_scheme==old_scheme.replace(original,replacement)
    old_control=(OLD/'template/system/controlDict').read_text(encoding='utf-8')
    new_control=(NEW/'template/system/controlDict').read_text(encoding='utf-8')
    expected,n1=re.subn(r'(?m)^endTime\s+1500;', 'endTime 120;',old_control)
    expected,n2=re.subn(r'(?m)^writeInterval\s+200;', 'writeInterval 20;',expected)
    assert n1==n2==1 and new_control==expected
    oc,nc=read(OLD/'template/config.json'),read(NEW/'template/config.json')
    physical=copy.deepcopy(nc)
    physical['config_id']=oc['config_id'];physical['geometry']['case_id']=oc['geometry']['case_id']
    assert physical.pop('engineering_provenance')=={'origin_case_id':'b15_engineering','version':'t029a'}
    trial=physical.pop('numerical_trial');assert trial['endTime']==120 and trial['writeInterval']==20 and trial['U_convection']=='bounded Gauss upwind'
    assert physical['notes'][:len(oc['notes'])]==oc['notes'] and len(physical['notes'])==len(oc['notes'])+3
    physical['notes']=oc['notes'];assert physical==oc,'physical/boundary/quality/geometry contract changed'
    oa,na=read(OLD/'admission.json'),read(NEW/'admission.json')
    assert na['case_id']==na['current_source_binding']['sample_id']=='b15_engineering_t029a'
    assert na['engineering_provenance']=={'origin_case_id':'b15_engineering','version':'t029a'}
    assert na['mesh_fingerprint']==oa['mesh_fingerprint']
    assert na['source_native_polyMesh_fingerprint']==oa['source_native_polyMesh_fingerprint']
    assert na['frozen_sources']==oa['frozen_sources'] and na['surface']==oa['surface']
    assert na['clinical_validation']==oa['clinical_validation']=='not_validated'
    assert na['config_sha256']==sha(NEW/'template/config.json')
    def authorization(p,old):
        x=copy.deepcopy(p)
        if not old:
            assert x.pop('engineering_provenance')==na['engineering_provenance']
        for k in ['case_id','config_sha256','record_sha256','source_record']:x.pop(k)
        return x
    assert authorization(oa['engineering_authorization'],True)==authorization(na['engineering_authorization'],False)
    assert na['engineering_authorization']['case_id']==na['case_id']
    assert na['engineering_authorization']['config_sha256']==na['config_sha256']
    assert na['engineering_authorization']['record_sha256']==sha(NEW/na['engineering_authorization']['record_file'])
    oa2,na2=read(OLD/'template/engineering_authorization.json'),read(NEW/'template/engineering_authorization.json')
    assert authorization(oa2,True)==authorization(na2,False)
    assert na2['record_sha256']==sha(NEW/'template'/na2['record_file'])
    na_comparable=copy.deepcopy(na)
    na_comparable.pop('engineering_provenance');na_comparable['case_id']=oa['case_id']
    na_comparable['current_source_binding']['sample_id']=oa['current_source_binding']['sample_id']
    na_comparable['config_sha256']=oa['config_sha256'];na_comparable['engineering_authorization']=oa['engineering_authorization']
    assert na_comparable==oa,'unapproved admission difference'
    om,nm=read(OLD/'template/case_manifest.json'),read(NEW/'template/case_manifest.json')
    nm_comparable=copy.deepcopy(nm);assert nm_comparable.pop('engineering_provenance')==na['engineering_provenance']
    nm_comparable['patient_case_id']=om['patient_case_id'];nm_comparable['engineering_input_provenance']=om['engineering_input_provenance']
    assert nm_comparable==om,'unapproved case manifest difference'
    mesh={p:h for p,h in b.items() if p.startswith('template/constant/polyMesh/')}
    assert len(mesh)==12 and all(a[p]==h for p,h in mesh.items())
    assert all(a[p]==b[p] for p in ['template/0/p','template/0/U','template/system/fvSolution',
                  'template/constant/transportProperties','template/constant/turbulenceProperties','checkMesh.log'])
    diffs={p:''.join(difflib.unified_diff((OLD/p).read_text(encoding='utf-8').splitlines(True),
                    (NEW/p).read_text(encoding='utf-8').splitlines(True),fromfile='original/'+p,tofile='candidate/'+p)) for p in changes}
    report={'schema':'t023_t029_frozen_input_audit/v1','at':dt.datetime.now(dt.timezone.utc).isoformat(),
            'producer_commit':'946f3f7364a91fe5e2d169bdb15127115ff0bcfa','source_freeze_sha256':sha(producer),
            'input_freeze_sha256':sha(input_freeze),'actual_source_sha256':code,'original_files':a,'candidate_files':b,
            'changed_files':changes,'actual_text_diffs':diffs,'mesh_file_count_unchanged':len(mesh),
            'physical_boundary_geometry_quality_equal':True,'only_numerical_change':'div(phi,U): bounded Gauss upwind',
            'run_control_changes':{'endTime':[1500,120],'writeInterval':[200,20]},
            'version_and_content_binding_metadata_changes_explicit':True,'passed':True,
            'patient_numerical_accepted':False,'job_created_or_monitored':False,'source_script_sha256':sha(__file__)}
    write_once('frozen-input-audit.json',report)
    contract_files={**code,**{str((NEW/p).resolve()):h for p,h in b.items()},str(input_freeze.resolve()):sha(input_freeze)}
    for rel in ['work/lib/serve_cfd_workspace.py','work/07_cfd_pipeline/workspace/simulation.js','work/07_cfd_pipeline/workspace/workspace.js']:
        contract_files[str((ROOT/rel).resolve())]=sha(ROOT/rel)
    contract={'schema':'t023_t029_service_reload_contract/v1','project_root':str(ROOT),'case_id':na['case_id'],
              'lead_execution_authorization':'2026-10-15 Lead: freeze与新包actual差异/原包保护通过后按T023第9条专门重载8769；不POST新任务。',
              'freeze_artifact':{'path':str(producer.resolve()),'sha256':sha(producer)},'frozen_file_sha256':contract_files}
    write_once('service-reload-contract.json',contract)
    print(json.dumps({'passed':True,'code_files':len(code),'input_files':len(b),'unchanged_mesh_files':len(mesh),
                      'changed_files':changes,'reload_contract_created':True,'no_POST':True},ensure_ascii=False))


if __name__=='__main__':main()
