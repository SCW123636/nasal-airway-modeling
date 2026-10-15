"""One controlled real TS775 inference, using installed cached weights, without skull crop.

This is a diagnostic contrast, not a new anatomical rule or production entry.
The shared workbench CPU lock is held without changing its content.
"""
import os, sys, json, time, hashlib, datetime, argparse, urllib.request, subprocess
from pathlib import Path
for var in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[var]='6'

ROOT=Path(r'D:\项目\鼻腔建模')
WORK_ROOT=Path(r'C:\ts_work\t032_hypopharynx')
LOCK=Path(r'C:\ts_work\project_cases\pipeline.lock')

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def timestamp():return datetime.datetime.now().astimezone().isoformat()

def get_api(path):
    with urllib.request.urlopen('http://127.0.0.1:8769'+path,timeout=5) as response:
        return json.load(response)

def preflight():
    jobs=get_api('/api/simulation/jobs')['jobs'];cases=get_api('/api/cases')['cases']
    summary={'at':timestamp(),'jobs':[{'id':j.get('id'),'status':j.get('status'),'stage':j.get('stage')} for j in jobs],
             'cases':[{'id':c.get('id'),'status':c.get('status')} for c in cases]}
    active=[x for xs in (summary['jobs'],summary['cases']) for x in xs if x['status'] in ('queued','running')]
    if active:raise RuntimeError('CPU lane API has active jobs: '+repr(active))
    snap=subprocess.run(['wsl','-e','sh','-lc','uptime'],capture_output=True,text=True,check=True)
    ps=subprocess.run(['wsl','-e','ps','-eo','pid,comm,args'],capture_output=True,text=True,check=True)
    active=[l for l in ps.stdout.splitlines() if any(x in l for x in ('simpleFoam','checkMesh','gmshToFoam','netgen','TotalSegmentator'))]
    summary['wsl_uptime']=snap.stdout.strip();summary['wsl_compute_processes']=active
    if active:raise RuntimeError('CPU lane WSL process active: '+repr(active))
    return summary

def semantic_air(ct,labels,label_id=13,threshold=-300.):
    if ct.shape!=labels.shape:raise ValueError('shape mismatch')
    return (labels==label_id)&(ct<threshold)

def known_answers():
    import numpy as np
    ct=np.array([[[-1000,-300,-301,0,-1000]]]);labels=np.array([[[13,13,13,13,12]]])
    assert semantic_air(ct,labels).tolist()==[[[True,False,True,False,False]]]
    assert not semantic_air(ct,np.zeros_like(labels)).any()
    try:semantic_air(ct,np.zeros((1,1,1)))
    except ValueError:pass
    else:raise AssertionError('shape mismatch not rejected')
    return {'strict_HU_threshold_known_answer':'pass','class13_not_class12':'pass','empty_is_empty':'pass','shape_rejected':'pass'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--case',choices=['p0','p1','p2','p3','p3t1'],default='p2');ap.add_argument('--out',required=True);ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    out=Path(args.out).resolve()
    if not out.is_relative_to(WORK_ROOT.resolve()):raise ValueError('output outside isolated root')
    out.mkdir(parents=True,exist_ok=False)
    report={'task':'T-032','created':timestamp(),'status':'preflight','case':args.case,
            'purpose':'Controlled no-skull-crop context contrast, not a production/anatomical claim',
            'symptom_patient_mapping':'unknown','threshold_hu':-300.,'medical_review':'pending','cfd_admission':False}
    def save():
        (out/'run_status.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'status':report['status'],'at':timestamp()},ensure_ascii=False),flush=True)
    save()
    try:
        import ctypes
        kernel=ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype=ctypes.c_void_p
        kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
        if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),63):raise RuntimeError('cannot set 6-core affinity')
        report['affinity_mask']=63;report['logical_core_cap']=6
        report['known_answers']=known_answers()
        if not args.execute:
            report['status']='known_answers_only';save();return
        report['preflight']=preflight();save()
        import msvcrt
        if not LOCK.is_file():raise RuntimeError('missing production shared CPU lock')
        with LOCK.open('r+b') as lock:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            try:
                report['lock_acquired_at']=timestamp();report['status']='fingerprinting';save()
                import importlib.metadata, multiprocessing
                from totalsegmentator.config import setup_nnunet
                setup_nnunet()
                import totalsegmentator.nnunet as nn
                from totalsegmentator.python_api import get_task_config
                cfg=get_task_config('head_glands_cavities')
                if cfg['task_id']!=775 or cfg['trainer']!='nnUNetTrainer_DASegOrd0_NoMirroring':raise RuntimeError('unexpected installed config')
                base=Path(r'C:\Users\lenovo\.totalsegmentator\nnunet\results\Dataset775_head_glands_cavities_492subj\nnUNetTrainer_DASegOrd0_NoMirroring__nnUNetPlans__3d_fullres_high')
                ct=Path('C:/ts_work')/args.case/'ct.nii.gz'
                paths={'ct':ct,'installed_nnunet':Path(nn.__file__),'dataset':base/'dataset.json','plans':base/'plans.json','weights':base/'fold_0/checkpoint_final.pth','runner':Path(__file__)}
                report['inputs']={k:{'path':str(p),'sha256':sha(p)} for k,p in paths.items()}
                report['installed_version']=importlib.metadata.version('TotalSegmentator')
                report['installed_task_config']=cfg
                report['inference_parameters']={'task_id':775,'trainer':cfg['trainer'],'model':cfg['model'],'folds':[0],'resample':cfg['resample'],'crop':None,'tta':False,'resampling_order':1,'roi_subset':None,'device':'cpu','nr_threads_resampling':1,'nr_threads_saving':1,'multilabel_image':True}
                report['thread_cap_method']='6 logical core process affinity inherited by child processes; isolated multiprocessing.cpu_count returns 6 so TS torch.set_num_threads requests 6; BLAS environment 6'
                report['status']='inference';report['inference_started']=timestamp();save()
                old_count=multiprocessing.cpu_count;multiprocessing.cpu_count=lambda:6
                try:
                    result=nn.nnUNet_predict_image(ct,out/'semantic_775_nocrop.nii.gz',775,model=cfg['model'],folds=[0],trainer=cfg['trainer'],resample=cfg['resample'],crop=None,task_name='head_glands_cavities',multilabel_image=True,nr_threads_resampling=1,nr_threads_saving=1,device='cpu',verbose=True,output_task_name='head_glands_cavities')
                finally:multiprocessing.cpu_count=old_count
                report['inference_ended']=timestamp();report['status']='postprocess';save()
                import SimpleITK as sitk, numpy as np
                cti=sitk.ReadImage(str(ct));labels_i=sitk.ReadImage(str(out/'semantic_775_nocrop.nii.gz'))
                def geom(im):return (im.GetSize(),im.GetSpacing(),im.GetOrigin(),im.GetDirection())
                if geom(cti)!=geom(labels_i):raise RuntimeError('semantic output grid mismatch')
                ca=sitk.GetArrayFromImage(cti);la=sitk.GetArrayFromImage(labels_i)
                hypo=semantic_air(ca,la);semantic=la==13
                report['label_counts']={str(int(k)):int(v) for k,v in zip(*np.unique(la,return_counts=True))}
                report['hypopharynx_semantic_voxels']=int(semantic.sum());report['hypopharynx_air_voxels']=int(hypo.sum())
                for name,arr in [('hypopharynx_semantic',semantic),('hypopharynx_air_candidate',hypo)]:
                    im=sitk.GetImageFromArray(arr.astype(np.uint8));im.CopyInformation(cti);sitk.WriteImage(im,str(out/(name+'.nii.gz')))
                for name,arr in [('oropharynx',la==12),('hypopharynx',semantic)]:
                    old=sitk.GetArrayFromImage(sitk.ReadImage(str(ct.parent/'masks'/(name+'.nii.gz'))))>0
                    report[name+'_old_new_comparison']={'old_voxels':int(old.sum()),'new_voxels':int(arr.sum()),'symmetric_difference':int((old^arr).sum()),'intersection':int((old&arr).sum())}
                report['output_sha256']={p.name:sha(p) for p in out.glob('*.nii.gz')}
                report['input_fingerprints_unchanged']={k:sha(p)==report['inputs'][k]['sha256'] for k,p in paths.items()}
                if not all(report['input_fingerprints_unchanged'].values()):raise RuntimeError('frozen input changed')
                report['status']='diagnostic_completed';save()
            finally:
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    except Exception as exc:
        import traceback
        report['status']='failed';report['error']=repr(exc);report['traceback']=traceback.format_exc();save();raise

if __name__=='__main__':main()
