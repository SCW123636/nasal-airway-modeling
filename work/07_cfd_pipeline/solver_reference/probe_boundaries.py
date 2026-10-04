"""One-step, non-patient API probe of shared-pressure / total-outflow types."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


def replace_patch(text, patch, body):
    result,n=re.subn(r'\b'+re.escape(patch)+r'\s*\{[^}]*\}',patch+' { '+body+' }',text,count=1,flags=re.S)
    if n!=1:raise RuntimeError('Patch not found: '+patch)
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source-case',required=True);ap.add_argument('--case',required=True)
    ap.add_argument('--export-dir',required=True);args=ap.parse_args()
    source=Path(args.source_case);case=Path(args.case)
    case.mkdir(parents=True,exist_ok=False)
    for part in ('0','system','constant'):shutil.copytree(source/part,case/part)
    up=case/'0/U';text=up.read_text()
    text=replace_patch(text,'inlet','type pressureInletOutletVelocity; value uniform (0.1 0 0);')
    text=replace_patch(text,'outlet','type flowRateOutletVelocity; volumetricFlowRate constant 2e-7; value uniform (0.1 0 0);')
    up.write_text(text)
    pp=case/'0/p';text=pp.read_text()
    text=replace_patch(text,'inlet','type totalPressure; p0 uniform 0; value uniform 0;')
    text=replace_patch(text,'outlet','type zeroGradient;');pp.write_text(text)
    env=os.environ.copy();env.update({'WM_PROJECT_DIR':'/usr/share/openfoam','FOAM_ETC':'/usr/share/openfoam/etc','WM_PROJECT_VERSION':'v1912'})
    with (case/'log.dry-run').open('w') as f:
        p=subprocess.run(['simpleFoam','-dry-run'],cwd=case,env=env,stdout=f,stderr=subprocess.STDOUT)
    result={'patient_data':False,'command':['simpleFoam','-dry-run'],'exit_code':p.returncode,
            'boundary_types':['totalPressure','pressureInletOutletVelocity','flowRateOutletVelocity'],
            'interpretation':'one-step syntax/runtime API check only; not converged flow, split validation, or clinical confirmation'}
    (case/'api_probe.json').write_text(json.dumps(result,indent=2)+'\n')
    shutil.copytree(case,Path(args.export_dir),dirs_exist_ok=False)
    print(json.dumps(result));return p.returncode


if __name__=='__main__':raise SystemExit(main())
