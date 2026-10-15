"""Read native original cases and independently recompute all published scalars."""
from pathlib import Path
import hashlib,json,subprocess,re,sys
import numpy as np
import vtk
ROOT=Path(r'D:\项目\鼻腔建模')
OUT=ROOT/'outputs/T-018'
IDS=['s_7dc6eb58cad24de48d3da028','s_970bd197fb3b41d289170ceb']
report={'checks':[],'cases':[],'failures':[]}
def check(name,ok,detail=None):
    r={'name':name,'passed':bool(ok),'detail':detail};report['checks'].append(r)
    if not ok:report['failures'].append(r)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for jid in IDS:
    d=Path(r'C:\ts_work\project_cases\simulation_jobs')/jid
    job=json.loads((d/'job.json').read_text(encoding='utf-8'))
    m=json.loads((d/job['asset_paths']['run_manifest.json']).read_text(encoding='utf-8'))
    expected={}
    for c in m['cases']:
        case=d/'export'/jid/c['level']
        vtu=next((case/'VTK').rglob('internal.vtu'))
        reader=vtk.vtkXMLUnstructuredGridReader();reader.SetFileName(str(vtu));reader.Update()
        check(jid+' '+c['level']+' cells',reader.GetOutput().GetNumberOfCells()==c['cells'],c['cells'])
        monitors={}
        for name in ['flowIn','flowOut','pressureIn','pressureOut']:
            p=next((case/'postProcessing'/name).glob('*/surfaceFieldValue.dat'))
            monitors[name]=np.loadtxt(p,comments='#',ndmin=2)[-1,1]
        rho=m['parameters']['rho_kg_m3']
        dp=float((monitors['pressureIn']-monitors['pressureOut'])*rho)
        mass=float(abs(monitors['flowIn']+monitors['flowOut'])/max(abs(monitors['flowIn']),abs(monitors['flowOut'])))
        published=next(x for x in job['result']['cases'] if x['level']==c['level'])
        check(jid+' '+c['level']+' raw monitor reproduction',abs(dp-published['delta_p_boundary_Pa'])<1e-12 and mass==published['mass_imbalance_fraction'],{'delta_p_Pa':dp,'mass_imbalance_fraction':mass})
        log=(case/'log.simpleFoam').read_text()
        check(jid+' '+c['level']+' raw convergence',bool(re.search(r'SIMPLE solution converged in \d+ iterations',log)) and log.strip().endswith('End'))
        check(jid+' '+c['level']+' raw mesh status','Mesh OK.' in (case/'log.checkMesh').read_text())
        report['cases'].append({'job':jid,'level':c['level'],'cells':c['cells'],'delta_p_Pa':dp,'mass_imbalance_fraction':mass,'vtu_sha256':sha(vtu),'convergence':re.search(r'SIMPLE solution converged in \d+ iterations',log).group()})
        for p in [case/'log.blockMesh',case/'log.checkMesh',case/'log.simpleFoam',case/'log.foamToVTK',vtu]:
            rel=p.relative_to(d/'export'/jid).as_posix()
            expected['/home/lenovo2/nasal_cfd_workspace_jobs/'+jid+'/'+rel]=sha(p)
    code='''import pathlib,json,hashlib,os
paths=EXPECTED
out={"pid":os.getpid(),"cwd":os.getcwd(),"files":[]}
for path in paths:
 p=pathlib.Path(path);s=p.stat()
 out["files"].append({"path":path,"exists":p.is_file(),"bytes":s.st_size,"mtime_ns":s.st_mtime_ns,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()})
print(json.dumps(out))
'''.replace('EXPECTED',repr(list(expected)))
    p=subprocess.run(['wsl.exe','-d','Ubuntu-22.04','--','python3','-c',code],capture_output=True,timeout=20)
    check(jid+' native readback succeeded',p.returncode==0,p.stderr.decode(errors='replace'))
    native=json.loads(p.stdout)
    (OUT/(jid+'_native_readback.json')).write_text(json.dumps(native,indent=2),encoding='utf-8')
    check(jid+' native logs and VTU hashes match exported copies',all(expected[f['path']]==f['sha256'] and f['exists'] for f in native['files']),{'files_compared':len(expected)})
    # Re-create only the read-side manager, without a worker or any solver launch.
    sys.path.insert(0,str(ROOT/'work/lib'))
    from cfd_workspace_jobs import SimulationJobs
    class Cases:
        root=Path(r'C:\ts_work\project_cases')
    restored=SimulationJobs(Cases(),ROOT/'work/06_auto_landmarks')
    restored_job=restored.get(jid)
    check(jid+' fresh manager reads persistent terminal state',restored_job['status']==job['status']=='completed' and restored_job['result']==job['result'] and restored_job['exit_code']==0)
report['scope']='Readback only; no commands create mesh or run CFD. Native SHA confirms exported raw evidence belongs to isolated Linux cases; recorded scalar zeros retain original precision limitation.'
(OUT/'native_multilevel_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(report['checks']),'failures':report['failures'],'cases':report['cases']},ensure_ascii=False))
sys.exit(bool(report['failures']))
