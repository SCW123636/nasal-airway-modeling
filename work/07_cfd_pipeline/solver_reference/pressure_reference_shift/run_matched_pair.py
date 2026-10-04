"""Non-patient 0/18 Pa pair with identical attainable numerical tolerances."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from run_pressure_shift import digest_inputs


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',default=str(Path.home()/'nasal_cfd_reference/poiseuille_v1912_verified/medium'))
    ap.add_argument('--work-dir',default=str(Path.home()/'nasal_cfd_reference/pressure_reference_matched_pair'))
    ap.add_argument('--export-dir',required=True);args=ap.parse_args()
    source=Path(args.source);root=Path(args.work_dir);root.mkdir(parents=True,exist_ok=False)
    verified_hashes=digest_inputs(source)
    environment=os.environ.copy();environment.update({'WM_PROJECT_DIR':'/usr/share/openfoam','FOAM_ETC':'/usr/share/openfoam/etc','WM_PROJECT_VERSION':'v1912'})
    record={'schema':'matched_pressure_reference_pair/v1','patient_data':False,'source_verified_case':str(source),
            'same_numerical_settings_as_original_verified':False,
            'shared_numerical_settings':{'linear_tolerance_p':1e-10,'linear_tolerance_U':1e-10,
                'SIMPLE_residual_p':1e-8,'SIMPLE_residual_U':1e-6,'endTime':2000},
            'description':'Both copied cases use identical tolerances. Between the pair only the outlet pressure value differs.',
            'cases':{},'strict_run_note':'The original 1e-12 linear-tolerance +18Pa run was terminated after observing a numerical pressure residual floor; retained separately.'}
    try:
        for name,value in [('reference_0Pa',0),('shifted_18Pa',15)]:
            case=root/name;case.mkdir()
            for part in ('0','system','constant'):shutil.copytree(source/part,case/part)
            solution=case/'system/fvSolution';text=solution.read_text()
            if text.count('tolerance 1e-12;')!=2:raise RuntimeError('Unexpected source solver tolerances')
            text=text.replace('tolerance 1e-12;','tolerance 1e-10;')
            old='residualControl { p 1e-10; U 1e-8; }'
            if old not in text:raise RuntimeError('Unexpected source residual control')
            solution.write_text(text.replace(old,'residualControl { p 1e-8; U 1e-6; }'))
            pressure=case/'0/p';text=pressure.read_text();match=re.search(r'\boutlet\s*\{([^}]+)\}',text)
            patch,n=re.subn(r'\bvalue\s+uniform\s+0\s*;',f'value uniform {value};',match.group(0))
            if n!=1:raise RuntimeError('Expected baseline zero-pressure outlet')
            pressure.write_text(text[:match.start()]+patch+text[match.end():])
        left,right=root/'reference_0Pa',root/'shifted_18Pa'
        hashes_left,hashes_right=digest_inputs(left),digest_inputs(right)
        changed=[k for k in hashes_left if hashes_left[k]!=hashes_right[k]]
        if changed!=['0/p']:raise RuntimeError('Pair has additional unequal inputs: '+repr(changed))
        record['changed_input_files_within_pair']=changed
        for name in ('reference_0Pa','shifted_18Pa'):
            case=root/name;commands=[]
            for command,log in [(['simpleFoam'],'log.simpleFoam'),(['foamToVTK','-latestTime','-ascii','-fields','(p U)'],'log.foamToVTK')]:
                started=time.perf_counter()
                with (case/log).open('w') as output:
                    p=subprocess.run(command,cwd=case,env=environment,stdout=output,stderr=subprocess.STDOUT)
                result={'command':command,'exit_code':p.returncode,'elapsed_seconds':time.perf_counter()-started}
                commands.append(result);print(json.dumps({'case':name,**result}),flush=True)
                if p.returncode:raise RuntimeError('Pair command failed: '+name+'/'+log)
            record['cases'][name]={'commands':commands,'SIMPLE_automatic_stopping_satisfied':'SIMPLE solution converged' in (case/'log.simpleFoam').read_text()}
        record['verified_source_inputs_unchanged']=digest_inputs(source)==verified_hashes
        execution={'comparison_mode':'matched_numerical_settings_pair','changed_input_files':['0/p'],
            'baseline_inputs_unchanged':digest_inputs(left)==hashes_left,
            'verified_source_inputs_unchanged':record['verified_source_inputs_unchanged'],
            'shared_numerical_settings':record['shared_numerical_settings'],
            'same_numerical_settings_as_original_verified':False}
        (right/'execution.json').write_text(json.dumps(execution,indent=2)+'\n')
        record['status']='completed'
    except Exception as exc:
        record['status']='failed';record['error']=repr(exc);raise
    finally:
        (root/'pair_execution.json').write_text(json.dumps(record,indent=2)+'\n')
        shutil.copytree(root,Path(args.export_dir),dirs_exist_ok=False)


if __name__=='__main__':main()
