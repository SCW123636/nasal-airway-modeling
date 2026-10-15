"""Read two existing native cases; compare actual mesh/dictionaries and pressure units."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import datetime as dt

HERE=Path(__file__).resolve().parent
NEW='/home/lenovo2/nasal_cfd_workspace_jobs/s_aa79a63027b94bfb9a273898/evaluations/eval_001'
OLD='/home/lenovo2/nasal_cfd_workspace_jobs/s_942fdbebfffd433c8fcec956/evaluations/eval_001'
CODE=r'''
import json,pathlib,sys,hashlib
value={}
for label,directory in zip(['old','new'],sys.argv[1:]):
 d=pathlib.Path(directory);item={'native_case':str(d),'files':{},'mesh':{}}
 for name in ['system/controlDict','system/fvSchemes','system/fvSolution','constant/transportProperties','constant/turbulenceProperties','0/p','0/U','config.json']:
  p=d/name;item['files'][name]={'text':p.read_text(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
 for p in sorted((d/'constant/polyMesh').rglob('*')):
  if p.is_file():item['mesh'][p.relative_to(d/'constant/polyMesh').as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
 item['patient_input_fingerprint']=json.loads((d.parents[1]/'patient_input_fingerprint.json').read_text())
 item['checkMesh_text']=(d/'log.checkMesh').read_text()
 value[label]=item
print(json.dumps(value,ensure_ascii=False))
'''


def block(text,name):
    m=re.search(r'\b'+re.escape(name)+r'\s*\{([^{}]*)\}',text,re.S);assert m;return m.group(1)


def main():
    data=json.loads(subprocess.check_output(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',CODE,OLD,NEW],text=True,encoding='utf-8',timeout=45))
    old,new=data['old'],data['new']
    package=json.loads((HERE/'frozen-input-audit.json').read_text(encoding='utf-8'))['candidate_files']
    mesh={p.removeprefix('template/constant/polyMesh/'):h for p,h in package.items() if p.startswith('template/constant/polyMesh/')}
    assert len(mesh)==12 and new['mesh']==old['mesh']==mesh
    changed=[p for p in new['files'] if new['files'][p]['sha256']!=old['files'][p]['sha256']]
    assert set(changed)=={'system/controlDict','system/fvSchemes','config.json'}
    scheme=old['files']['system/fvSchemes']['text'];assert scheme.count('div(phi,U) bounded Gauss linearUpwind grad(U);')==1
    assert new['files']['system/fvSchemes']['text']==scheme.replace('div(phi,U) bounded Gauss linearUpwind grad(U);','div(phi,U) bounded Gauss upwind;')
    control=old['files']['system/controlDict']['text']
    expected,n1=re.subn(r'(?m)^endTime\s+1500;', 'endTime 120;',control)
    expected,n2=re.subn(r'(?m)^writeInterval\s+200;', 'writeInterval 20;',expected)
    assert n1==n2==1 and expected==new['files']['system/controlDict']['text']
    assert re.search(r'\bstopAt\s+endTime\s*;',expected) and re.search(r'\brunTimeModifiable\s+false\s*;',expected)
    config=json.loads(new['files']['config.json']['text']);rho=config['physics']['rho_kg_m3'];assert rho==1.2
    p,u=new['files']['0/p']['text'],new['files']['0/U']['text']
    assert re.search(r'dimensions\s*\[0\s+2\s+-2\s+0\s+0\s+0\s+0\]',p)
    assert re.search(r'dimensions\s*\[0\s+1\s+-1\s+0\s+0\s+0\s+0\]',u)
    for inlet in ['nostril_L','nostril_R']:
        pb,ub=block(p,inlet),block(u,inlet)
        assert 'fixedValue' in pb and 'pressureInletOutletVelocity' in ub
        assert abs(float(re.search(r'value\s+uniform\s+([^;]+)',pb).group(1))*rho-10)<1e-12
    assert float(re.search(r'value\s+uniform\s+([^;]+)',block(p,'nasopharynx_outlet')).group(1))==0
    assert not any(x in p+u for x in ['flowRateInletVelocity','massFlowRate','volumetricFlowRate'])
    fp=new['patient_input_fingerprint'];assert fp['admission_sha256']==package['admission.json'] and fp['config_sha256']==package['template/config.json']
    assert fp['current_source_binding'] is None
    failures={k:[int(x) for x in re.findall(r'Failed\s+(\d+)\s+mesh checks',v['checkMesh_text'])] for k,v in data.items()}
    assert failures=={'old':[2],'new':[2]}
    report={'at':dt.datetime.now(dt.timezone.utc).isoformat(),'passed':True,'raw_native_sources':data,'native_changed_small_files':changed,
            'mesh_12_actual_old_new_package_equal':True,'same_10Pa_common_inlets_outlet_0_Pa':True,
            'p_kinematic_U_m_s_correct':True,'natural_flow_no_hard_split':True,'actual_stopAt_endTime120_write20_runTimeModifiable_false':True,
            'unchanged_fvSolution_transport_turbulence_and_initial_fields':True,'original_Failed2_remains':failures,
            'no_patient_convergence_or_target_acceptance':True,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (HERE/'native-entry-audit.json').open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'native_entry_passed':True,'mesh_files_equal':12,'actual_10Pa_outlet0':True,'actual_upwind_120_20_only':True,'Failed_mesh_checks':failures,'not_convergence_acceptance':True},ensure_ascii=False))


if __name__=='__main__':main()
