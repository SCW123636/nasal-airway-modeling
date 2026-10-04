"""Non-patient fixed-flow gauge shift test; keep the verified baseline intact."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


def digest_inputs(case):
    return {str(p.relative_to(case)):hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('0','constant','system') for p in sorted((case/folder).rglob('*')) if p.is_file()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--baseline',default=str(Path.home()/'nasal_cfd_reference/poiseuille_v1912_verified/medium'))
    parser.add_argument('--case',default=str(Path.home()/'nasal_cfd_reference/pressure_reference_shift_medium'))
    parser.add_argument('--export-dir',required=True)
    args=parser.parse_args();baseline=Path(args.baseline);case=Path(args.case)
    before=digest_inputs(baseline)
    case.mkdir(parents=True,exist_ok=False)
    for folder in ('0','constant','system'):shutil.copytree(baseline/folder,case/folder)
    pressure=case/'0/p';text=pressure.read_text()
    match=re.search(r'\boutlet\s*\{([^}]+)\}',text)
    if not match or not re.search(r'\btype\s+fixedValue\s*;',match.group(1)):
        raise RuntimeError('Baseline outlet is not fixedValue pressure')
    patch,n=re.subn(r'\bvalue\s+uniform\s+0\s*;', 'value uniform 15;',match.group(0))
    if n!=1:raise RuntimeError('Expected a unique zero outlet pressure')
    pressure.write_text(text[:match.start()]+patch+text[match.end():])
    after=digest_inputs(case)
    changes=[k for k in before if before[k]!=after[k]]
    if changes!=['0/p']:raise RuntimeError('Unexpected changed input files: '+repr(changes))
    env=os.environ.copy();env.update({'WM_PROJECT_DIR':'/usr/share/openfoam','FOAM_ETC':'/usr/share/openfoam/etc','WM_PROJECT_VERSION':'v1912'})
    record={'schema':'pressure_reference_shift_execution/v1','patient_data':False,'baseline':str(baseline),'case':str(case),
        'rho_kg_m3':1.2,'outlet_pressure_before_kinematic':0.,'outlet_pressure_after_kinematic':15.,
        'expected_pressure_shift_Pa':18.,'independent_inlet_pressure_added':False,
        'changed_input_files':changes,'baseline_input_hashes':before,'shifted_input_hashes':after,'commands':[]}
    try:
        for command,name in [(['simpleFoam'],'log.simpleFoam'),(['foamToVTK','-latestTime','-ascii','-fields','(p U)'],'log.foamToVTK')]:
            start=time.perf_counter()
            with (case/name).open('w') as out:
                p=subprocess.run(command,cwd=case,env=env,stdout=out,stderr=subprocess.STDOUT)
            result={'command':command,'exit_code':p.returncode,'elapsed_seconds':time.perf_counter()-start,'log':name}
            record['commands'].append(result);print(json.dumps(result),flush=True)
            if p.returncode:raise RuntimeError('Execution failed: '+name)
        record['execution_status']='completed'
        record['baseline_inputs_unchanged']=digest_inputs(baseline)==before
        if not record['baseline_inputs_unchanged']:raise RuntimeError('Baseline inputs changed')
    except Exception as exc:
        record['execution_status']='failed';record['error']=repr(exc)
        raise
    finally:
        (case/'execution.json').write_text(json.dumps(record,indent=2)+'\n')
        shutil.copytree(case,Path(args.export_dir)/'case',dirs_exist_ok=False)


if __name__=='__main__':main()
