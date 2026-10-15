"""Real p3 continuous-air probe. Writes only T034 output and isolated pixel data."""
import os
for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '1'
import sys, json, hashlib, subprocess, datetime, urllib.request, ctypes, msvcrt
from pathlib import Path
ROOT=Path(r'D:\项目\鼻腔建模'); OUT=ROOT/'outputs/T-034'; DATA=Path(r'C:\ts_work\t034_continuous_air')
sys.path.insert(0,str(ROOT/'work/lib'))

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def save(name, data):
    path=OUT/name; path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def api(path):
    with urllib.request.urlopen('http://127.0.0.1:8769'+path,timeout=5) as r:return json.load(r)

def main():
    import numpy as np, SimpleITK as sitk
    from continuous_air_candidate import connected_air, same_grid, face_contacts
    from anatomy_barrier_seg import plane_keep_mask
    sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
    kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
    if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),63):raise RuntimeError('affinity rejected')
    run=DATA/'run01';run.mkdir(parents=True,exist_ok=False)
    report={'case':'p3','at':datetime.datetime.now().astimezone().isoformat(),'stage':'entry',
      'medical_review':'pending','CFD_admitted':False,'manual_STL_identity':'not_located',
      'symptom_patient_mapping':'unknown','logical_core_cap':6,'SimpleITK_threads':1,
      'purpose':'real CT engineering connectivity contrast; no anatomical region naming'}
    save('entry.json',report)
    jobs=api('/api/simulation/jobs')['jobs'];cases=api('/api/cases')['cases']
    active=[{'id':v.get('id'),'status':v.get('status')} for v in jobs+cases if v.get('status') in ('queued','running')]
    uptime=subprocess.run(['wsl','-e','sh','-lc','uptime'],capture_output=True,text=True,check=True).stdout.strip()
    ps=subprocess.run(['wsl','-e','ps','-eo','pid,comm,args'],capture_output=True,text=True,check=True).stdout
    busy=[line for line in ps.splitlines() if any(s in line for s in ('simpleFoam','checkMesh','gmshToFoam','netgen','TotalSegmentator'))]
    report['cpu_entry']={'active_jobs':active,'wsl_uptime':uptime,'wsl_compute_processes':busy}
    save('entry.json',report)
    if active or busy:raise RuntimeError('CPU lane busy')
    with Path(r'C:\ts_work\project_cases\pipeline.lock').open('r+b') as lock:
      lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
      try:
        source=Path(r'C:\ts_work\p3');names=('nasal_cavity_left','nasal_cavity_right','nasopharynx','oropharynx')
        paths={'ct':source/'ct.nii.gz',**{n:source/'masks'/(n+'.nii.gz') for n in names},
          'planes':ROOT/'work/06_auto_landmarks/p3/review_config_proposed.json',
          'references':ROOT/'work/06_auto_landmarks/reference_library.json',
          'implementation':ROOT/'work/lib/continuous_air_candidate.py','runner':Path(__file__)}
        report['inputs']={k:{'path':str(p),'sha256':sha(p)} for k,p in paths.items()}
        report['repo_HEAD']=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
        image=sitk.ReadImage(str(paths['ct']));ct=sitk.GetArrayFromImage(image);seed=np.zeros(ct.shape,bool)
        report['grid']={'size_xyz':list(image.GetSize()),'spacing_xyz_mm':list(image.GetSpacing()),'origin_LPS_mm':list(image.GetOrigin()),'direction_row_major':list(image.GetDirection())}
        report['source_labels']={}
        for n in names:
          im=sitk.ReadImage(str(paths[n]));
          if not same_grid(image,im):raise ValueError('grid mismatch '+n)
          a=sitk.GetArrayFromImage(im)>0;report['source_labels'][n]={'semantic_voxels':int(a.sum()),'strict_air_voxels':int((a&(ct < -300)).sum())};seed|=a&(ct < -300)
        exterior=np.zeros(ct.shape,bool);exterior[:,:,0]=True;exterior[:,:,-1]=True;exterior[:,0,:]=True;exterior[:,-1,:]=True
        report['exterior_screen']='Any 6-connected seed air reaching one of four lateral CT faces x/y; inferior/superior CT faces separately reported, not automatically named external air.'
        report['stage']='entry_checked';save('entry.json',report)
        raw,raw_report=connected_air(ct,seed,exterior_seed=exterior,reject_leak=False)
        raw_report['face_contacts']=face_contacts(raw);report['raw']=raw_report;report['stage']='raw_diagnostic_saved';save('probe.json',report)
        config=json.loads(paths['planes'].read_text(encoding='utf-8'));allowed=np.ones(ct.shape,bool)
        used={}
        for n in ('nostril_L','nostril_R'):
          p=config['planes_lps'][n];allowed &= plane_keep_mask(image,p,ct.shape);used[n]=p
        report['barriers']={'scope':'engineering_exploration_only; existing proposed plane parameters unchanged; human accepted reference points are coarse_localization_only','source':str(paths['planes']),'planes':used}
        del raw
        candidate,blocked_report=connected_air(ct,seed,allowed,exterior,reject_leak=False)
        blocked_report['face_contacts']=face_contacts(candidate);blocked_report['removed_vs_original_seed_voxels']=int((seed&~candidate).sum())
        blocked_report['added_vs_original_seed_voxels']=int((candidate&~seed).sum());report['blocked']=blocked_report
        report['candidate_accepted_for_engineering_view']=not blocked_report['exterior_leak_detected']
        for n,a in [('semantic_air_original',seed),('semantic_air_after_barriers',seed&allowed),('connected_air_after_barriers',candidate),('added_air_after_barriers',candidate&~seed)]:
          im=sitk.GetImageFromArray(a.astype(np.uint8));im.CopyInformation(image);sitk.WriteImage(im,str(run/(n+'.nii.gz')),True)
        report['outputs']={p.name:{'path':str(p),'sha256':sha(p)} for p in run.glob('*.nii.gz')}
        report['input_fingerprints_unchanged']={k:sha(p)==report['inputs'][k]['sha256'] for k,p in paths.items()}
        if not all(report['input_fingerprints_unchanged'].values()):raise RuntimeError('frozen input changed')
        report['stage']='probe_completed';save('probe.json',report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
      finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__':main()
