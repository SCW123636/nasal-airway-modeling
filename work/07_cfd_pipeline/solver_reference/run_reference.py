"""Run a NON-PATIENT plane-Poiseuille benchmark with Ubuntu OpenFOAM v1912.

Execute with the WSL Python, not the Windows Python. Generated data stay in a
new run directory; there is no patient file access and no clinical approval.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

L, H, W = 0.04, 0.002, 0.001
RHO, MU, UBULK = 1.20, 1.81e-5, 0.1
NU = MU / RHO
LEVELS = {"coarse": (80, 10), "medium": (160, 20), "fine": (320, 40)}
TUTORIAL = Path('/usr/share/doc/openfoam-examples/examples/incompressible/simpleFoam/pitzDaily')


def header(name, cls='dictionary'):
    return f'FoamFile\n{{\n version 2.0;\n format ascii;\n class {cls};\n object {name};\n}}\n'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='ascii')


def execute(args, case, environment, logname):
    begin = time.perf_counter()
    with (case / logname).open('w', encoding='utf-8') as output:
        process = subprocess.run(args, cwd=case, env=environment, stdout=output, stderr=subprocess.STDOUT)
    record = {'command': args, 'exit_code': process.returncode, 'elapsed_seconds': time.perf_counter()-begin,
              'log': str(case/logname)}
    print(json.dumps(record), flush=True)
    if process.returncode:
        raise RuntimeError(f'{args[0]} failed: {case/logname}')
    return record


def setup_case(case, nx, ny):
    case.mkdir(parents=True, exist_ok=False)
    for part in ('0', 'constant', 'system'):
        (case/part).mkdir()
    # The installed official tutorial supplies the actual v1912 scheme names.
    shutil.copy2(TUTORIAL/'system/fvSchemes', case/'system/fvSchemes')
    vertices = [(0,0,0),(L,0,0),(L,H,0),(0,H,0),(0,0,W),(L,0,W),(L,H,W),(0,H,W)]
    coords = '\n'.join('('+ ' '.join(f'{v:.15g}' for v in p) +')' for p in vertices)
    write(case/'system/blockMeshDict', header('blockMeshDict') + f'''
convertToMeters 1;
vertices ( {coords} );
blocks ( hex (0 1 2 3 4 5 6 7) ({nx} {ny} 1) simpleGrading (1 1 1) );
edges ();
boundary
(
 inlet {{ type patch; faces ((0 4 7 3)); }}
 outlet {{ type patch; faces ((1 2 6 5)); }}
 walls {{ type wall; faces ((0 1 5 4) (3 7 6 2)); }}
 frontAndBack {{ type empty; faces ((0 3 2 1) (4 5 6 7)); }}
);
mergePatchPairs ();
''')
    write(case/'constant/transportProperties', header('transportProperties') + f'\ntransportModel Newtonian;\nnu {NU:.16g};\n')
    write(case/'constant/turbulenceProperties', header('turbulenceProperties') + '\nsimulationType laminar;\n')
    write(case/'0/p', header('p','volScalarField') + '''
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
 inlet { type zeroGradient; }
 outlet { type fixedValue; value uniform 0; }
 walls { type zeroGradient; }
 frontAndBack { type empty; }
}
''')
    write(case/'system/fvSolution', header('fvSolution') + '''
solvers
{
 p { solver GAMG; tolerance 1e-12; relTol 0.01; smoother GaussSeidel; }
 U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
}
SIMPLE
{
 nNonOrthogonalCorrectors 0;
 consistent yes;
 residualControl { p 1e-10; U 1e-8; }
}
relaxationFactors { equations { U 0.9; } }
''')
    functions = []
    for name, patch, operation, field in [('flowIn','inlet','sum','phi'), ('flowOut','outlet','sum','phi'),
                                          ('pressureIn','inlet','areaAverage','p'), ('pressureOut','outlet','areaAverage','p')]:
        functions.append(f'''{name}
{{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name {patch};
 operation {operation};
 fields ({field});
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}}''')
    write(case/'system/controlDict', header('controlDict') + '''
application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime 2000;
deltaT 1;
writeControl timeStep;
writeInterval 200;
purgeWrite 2;
writeFormat ascii;
writePrecision 12;
writeCompression off;
timeFormat general;
timePrecision 10;
runTimeModifiable false;
functions
{
''' + '\n'.join(functions) + '\n}\n')


def foam_list_text(path):
    text = path.read_text()
    match = re.search(r'\n\s*(\d+)\s*\n\s*\(', text)
    if not match:
        raise ValueError('Cannot find ASCII list: ' + str(path))
    return int(match.group(1)), text[match.end():]


def inlet_centers(case):
    mesh = case/'constant/polyMesh'
    npoints, text = foam_list_text(mesh/'points')
    points = [tuple(float(v) for v in p.split()) for p in re.findall(r'\(([^()]*)\)',text)[:npoints]]
    nfaces, text = foam_list_text(mesh/'faces')
    faces = [[int(v) for v in f.split()] for f in re.findall(r'\d+\(([^()]*)\)',text)[:nfaces]]
    boundary = (mesh/'boundary').read_text()
    match = re.search(r'\binlet\s*\{([^}]+)\}',boundary)
    count = int(re.search(r'\bnFaces\s+(\d+)',match.group(1)).group(1))
    start = int(re.search(r'\bstartFace\s+(\d+)',match.group(1)).group(1))
    return [tuple(sum(points[i][a] for i in f)/len(f) for a in range(3)) for f in faces[start:start+count]]


def set_inlet_profile(case):
    centers = inlet_centers(case)
    speeds = [6*UBULK*(p[1]/H)*(1-p[1]/H) for p in centers]
    # Uniform rectangular faces: normalize midpoint samples to the exact Q.
    scale = UBULK / (sum(speeds)/len(speeds))
    values = '\n'.join(f'({u*scale:.16g} 0 0)' for u in speeds)
    write(case/'0/U',header('U','volVectorField') + f'''
dimensions [0 1 -1 0 0 0 0];
internalField uniform ({UBULK} 0 0);
boundaryField
{{
 inlet {{ type fixedValue; value nonuniform List<vector> {len(speeds)} ( {values} ); }}
 outlet {{ type zeroGradient; }}
 walls {{ type noSlip; }}
 frontAndBack {{ type empty; }}
}}
''')
    return {'inlet_faces':len(speeds),'profile_midpoint_normalization':scale,'imposed_Q_m3_s':UBULK*H*W}


def last_function_value(case, function):
    files = sorted((case/'postProcessing'/function).glob('*/surfaceFieldValue.dat'))
    if not files:
        raise ValueError('Missing function output: ' + function)
    rows = [r.split() for r in files[-1].read_text().splitlines() if r.strip() and not r.startswith('#')]
    if not rows:
        raise ValueError('Empty function output: ' + function)
    return {'iteration':float(rows[-1][0]),'value':float(rows[-1][1]),'path':str(files[-1])}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--work-dir',default=str(Path.home()/'nasal_cfd_reference'))
    parser.add_argument('--tag',default='poiseuille_v1912')
    parser.add_argument('--levels',nargs='+',choices=list(LEVELS),default=list(LEVELS))
    parser.add_argument('--export-dir',required=True)
    args=parser.parse_args()
    if Path(args.tag).name!=args.tag or args.tag in ('.','..'):
        raise ValueError('tag must be one directory name')
    run=Path(args.work_dir).resolve()/args.tag
    run.mkdir(parents=True,exist_ok=False)
    environment=os.environ.copy()
    environment.update({'WM_PROJECT_DIR':'/usr/share/openfoam','FOAM_ETC':'/usr/share/openfoam/etc','WM_PROJECT_VERSION':'v1912'})
    manifest={'schema':'plane_poiseuille_reference/v1','patient_data':False,'clinical_validation':False,
              'solver':'simpleFoam','package_version':'1912.200626-1','source_tutorial':str(TUTORIAL),
              'environment_overrides':{k:environment[k] for k in ['WM_PROJECT_DIR','FOAM_ETC','WM_PROJECT_VERSION']},
              'parameters':{'L_m':L,'gap_H_m':H,'empty_width_W_m':W,'rho_kg_m3':RHO,'mu_Pa_s':MU,'nu_m2_s':NU,'bulk_U_m_s':UBULK},
              'numerics':{'SIMPLE_residual_control_p':1e-10,'SIMPLE_residual_control_U':1e-8,
                          'linear_solver_tolerance':1e-12,'inlet_profile':'area-normalized analytic parabolic samples',
                          'pressure':'kinematic m2/s2; multiply by rho to obtain Pa'},
              'analytical':{'Q_m3_s':UBULK*H*W,'max_U_m_s':1.5*UBULK,'delta_p_Pa':12*MU*UBULK*L/H**2,
                            'pressure_gradient_Pa_m':12*MU*UBULK/H**2,'hydraulic_Re_2H':RHO*UBULK*2*H/MU},
              'source_scheme_sha256':hashlib.sha256((TUTORIAL/'system/fvSchemes').read_bytes()).hexdigest(),
              'cases':[]}
    try:
        for level in args.levels:
            nx,ny=LEVELS[level];case=run/level
            print('Preparing '+level,flush=True)
            setup_case(case,nx,ny)
            commands=[execute(['blockMesh'],case,environment,'log.blockMesh')]
            profile=set_inlet_profile(case)
            commands.append(execute(['checkMesh','-allGeometry','-allTopology'],case,environment,'log.checkMesh'))
            commands.append(execute(['simpleFoam'],case,environment,'log.simpleFoam'))
            commands.append(execute(['foamToVTK','-latestTime','-ascii','-fields','(p U)'],case,environment,'log.foamToVTK'))
            log=(case/'log.simpleFoam').read_text()
            record={'level':level,'cells':nx*ny,'nx':nx,'ny':ny,'commands':commands,'profile':profile,
                    'SIMPLE_converged':'SIMPLE solution converged' in log,
                    'function_objects':{n:last_function_value(case,n) for n in ['flowIn','flowOut','pressureIn','pressureOut']},
                    'vtk_files':[str(p.relative_to(run)) for p in case.rglob('*.vt*')]}
            functions=record['function_objects'];qin=functions['flowIn']['value'];qout=functions['flowOut']['value']
            record['mass_imbalance_fraction']=abs(qin+qout)/max(abs(qin),abs(qout))
            record['delta_p_boundary_Pa']=RHO*(functions['pressureIn']['value']-functions['pressureOut']['value'])
            manifest['cases'].append(record)
            (run/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            print(json.dumps({'level':level,'converged':record['SIMPLE_converged'],'mass_imbalance':record['mass_imbalance_fraction'],
                              'delta_p_boundary_Pa':record['delta_p_boundary_Pa']}),flush=True)
        manifest['execution_status']='completed'
    except Exception as exc:
        manifest['execution_status']='failed';manifest['error']=repr(exc)
        raise
    finally:
        (run/'run_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        target=Path(args.export_dir).resolve()/args.tag
        shutil.copytree(run,target,dirs_exist_ok=False)
        print('Exported reference to '+str(target),flush=True)


if __name__=='__main__':
    main()
