"""Evidence-derived extension of existing exploratory finite-plane exterior sides.

The failed run01 and its escape path remain immutable. Point, normal, threshold,
x bounds and all upper bounds remain unchanged. Only anterior/inferior ROI minima
are extended to the exact LPS support bounds of the original scanned image.
"""
import os
for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[n]='1'
import sys,json,ctypes,msvcrt,subprocess,itertools,copy,datetime
from pathlib import Path
ROOT=Path(r'D:\项目\鼻腔建模');sys.path.insert(0,str(ROOT/'work/lib'))
from run_probe import sha,api
OUT=ROOT/'outputs/T-034';RUN=Path(r'C:\ts_work\t034_continuous_air\run02')

def main():
 import numpy as np,SimpleITK as sitk
 from scipy import ndimage
 from continuous_air_candidate import connected_air,face_contacts,index_to_lps
 from anatomy_barrier_seg import plane_keep_mask
 kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
 kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
 if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),63):raise RuntimeError('affinity rejected')
 sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
 active=[x for x in api('/api/cases')['cases']+api('/api/simulation/jobs')['jobs'] if x.get('status') in ('queued','running')]
 uptime=subprocess.run(['wsl','-e','sh','-lc','uptime'],capture_output=True,text=True,check=True).stdout.strip()
 ps=subprocess.run(['wsl','-e','ps','-eo','pid,comm,args'],capture_output=True,text=True,check=True).stdout
 busy=[x for x in ps.splitlines() if any(k in x for k in ('simpleFoam','checkMesh','gmshToFoam','netgen','TotalSegmentator'))]
 if active or busy:raise RuntimeError('CPU lane busy')
 RUN.mkdir(parents=True,exist_ok=False)
 report={'case':'p3','at':datetime.datetime.now().astimezone().isoformat(),'run':'run02','status':'entry',
 'medical_review':'pending','CFD_admitted':False,'oral_exclusion_reviewed':False,'outlet_selected':False,
 'symptom_patient_mapping':'unknown','manual_STL_correspondence':'unknown',
 'cpu_entry':{'active':active,'wsl_uptime':uptime,'busy':busy,'affinity_mask':63,'sitk_threads':1},
 'reason':'run01 actual 70-step six-neighbour air escape bypasses finite nostril ROI anterior edge',
 'scope':'engineering exploration; exterior ROI extension is not a medically reviewed cut'}
 def save():
  (OUT/'probe-run02.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 with Path(r'C:\ts_work\project_cases\pipeline.lock').open('r+b') as lock:
  lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
  try:
   paths={'ct':Path(r'C:\ts_work\p3\ct.nii.gz'),
   'seed':Path(r'C:\ts_work\t034_continuous_air\run01\semantic_air_original.nii.gz'),
   'planes':ROOT/'work/06_auto_landmarks/p3/review_config_proposed.json',
   'run01':OUT/'probe.json','escape':OUT/'escape-path.json',
   'implementation':ROOT/'work/lib/continuous_air_candidate.py','runner':Path(__file__)}
   report['inputs']={k:{'path':str(p),'sha256':sha(p)} for k,p in paths.items()}
   image=sitk.ReadImage(str(paths['ct']));ct=sitk.GetArrayFromImage(image)
   seed_im=sitk.ReadImage(str(paths['seed']));seed=sitk.GetArrayFromImage(seed_im)>0
   from continuous_air_candidate import same_grid
   if not same_grid(image,seed_im):raise RuntimeError('seed grid mismatch')
   corners=np.array(list(itertools.product(*[(-.5,n-.5)for n in image.GetSize()])))
   world=index_to_lps(corners,image);lo=world.min(0);hi=world.max(0)
   report['CT_grid']={'size_xyz':list(image.GetSize()),'spacing_xyz_mm':list(image.GetSpacing()),'origin_LPS_mm':list(image.GetOrigin()),'direction_row_major':list(image.GetDirection())}
   report['CT_support_LPS_bounds_mm']=[lo.tolist(),hi.tolist()]
   report['CT_support_LPS_corners_mm']=world.tolist()
   config=json.loads(paths['planes'].read_text(encoding='utf-8'));allowed=np.ones(ct.shape,bool)
   report['barriers']={}
   for name in ('nostril_L','nostril_R'):
    original=config['planes_lps'][name];p=copy.deepcopy(original)
    p['roi_lps_mm']['min'][1]=float(lo[1]);p['roi_lps_mm']['min'][2]=float(lo[2])
    keep=plane_keep_mask(image,p,ct.shape);allowed &=keep
    report['barriers'][name]={'original':original,'exploratory':p,'parameter_delta':{'roi_min_y_mm':[original['roi_lps_mm']['min'][1],p['roi_lps_mm']['min'][1]],'roi_min_z_mm':[original['roi_lps_mm']['min'][2],p['roi_lps_mm']['min'][2]]},'all_other_parameters_unchanged':all(p[k]==original[k] for k in original if k!='roi_lps_mm')}
   removed=seed&~allowed;coords=np.argwhere(removed);world_removed=index_to_lps(coords[:,::-1],image)
   report['removed_seed']={'count':int(removed.sum()),'LPS_center_bounds_mm':[world_removed.min(0).tolist(),world_removed.max(0).tolist()] if len(coords) else None}
   (RUN/'removed_seed_voxels_zyx.json').write_text(json.dumps(coords.tolist()),encoding='utf-8')
   report['removed_seed']['exact_zyx_path']=str(RUN/'removed_seed_voxels_zyx.json')
   report['removed_seed']['exact_zyx_sha256']=sha(RUN/'removed_seed_voxels_zyx.json')
   report['status']='inputs_frozen';save()
   ext=np.zeros(ct.shape,bool);ext[:,:,0]=True;ext[:,:,-1]=True;ext[:,0,:]=True;ext[:,-1,:]=True
   candidate,facts=connected_air(ct,seed,allowed,ext,reject_leak=False)
   facts['face_contacts']=face_contacts(candidate);facts['removed_vs_original_seed_voxels']=int((seed&~candidate).sum())
   facts['added_vs_original_seed_voxels']=int((candidate&~seed).sum());report['candidate']=facts
   report['engineering_screen_pass']=not facts['exterior_leak_detected']
   report['exterior_screen_limit']='No component reaches lateral scan faces is necessary, not proof all external air excluded. New ROI cuts and MPR must be inspected; oral anatomy unreviewed.'
   report['new_cut_contact']={}
   for name,pair in report['barriers'].items():
    keep=plane_keep_mask(image,pair['exploratory'],ct.shape)
    contact=candidate&ndimage.binary_dilation(~keep,structure=ndimage.generate_binary_structure(3,1))
    points=np.argwhere(contact)
    report['new_cut_contact'][name]={'candidate_voxels_adjacent_to_excluded_halfspace':int(contact.sum()),'bounds_LPS_mm':[index_to_lps(points[:,::-1],image).min(0).tolist(),index_to_lps(points[:,::-1],image).max(0).tolist()] if len(points)else None}
   for name,a in [('semantic_air_original',seed),('semantic_air_after_barriers',seed&allowed),('connected_air_candidate',candidate),('added_air_candidate',candidate&~seed),('removed_semantic_air',removed)]:
    im=sitk.GetImageFromArray(a.astype(np.uint8));im.CopyInformation(image);sitk.WriteImage(im,str(RUN/(name+'.nii.gz')),True)
   added=candidate&~seed;coords=np.argwhere(added)
   report['added_extent']={'LPS_center_bounds_mm':[index_to_lps(coords[:,::-1],image).min(0).tolist(),index_to_lps(coords[:,::-1],image).max(0).tolist()] if len(coords) else None}
   report['outputs']={p.name:{'path':str(p),'sha256':sha(p)}for p in RUN.glob('*.nii.gz')}
   report['inputs_unchanged']={k:sha(p)==report['inputs'][k]['sha256']for k,p in paths.items()}
   if not all(report['inputs_unchanged'].values()):raise RuntimeError('frozen input changed')
   report['status']='engineering_probe_completed';save()
   # Hand-inspect maximum-added slices and regular intermediate slices; no anatomical labels.
   import matplotlib;matplotlib.use('Agg')
   import matplotlib.pyplot as plt
   fig,axs=plt.subplots(3,4,figsize=(17,13))
   spacing=image.GetSpacing();selection=[]
   for axis in range(3):
    scores=added.sum(axis=tuple(i for i in range(3)if i!=axis));occupied=np.flatnonzero(scores)
    picks=sorted(set([int(np.argmax(scores))]+[int(occupied[round(q*(len(occupied)-1))])for q in (.2,.5,.8)]))
    while len(picks)<4:picks.append(picks[-1])
    for col,index in enumerate(picks[:4]):
     c=np.take(ct,index,axis=axis);s=np.take(seed&allowed,index,axis=axis);a=np.take(added,index,axis=axis)
     remaining=[i for i in range(3)if i!=axis];sp=[spacing[2-i]for i in remaining]
     extent=[0,c.shape[1]*sp[1],0,c.shape[0]*sp[0]];ax=axs[axis,col]
     ax.imshow(c,cmap='gray',vmin=-1000,vmax=500,origin='lower',extent=extent)
     rgba=np.zeros(c.shape+(4,));rgba[a]=[1,.4,.1,.8];rgba[s]=[0,.9,1,.8]
     ax.imshow(rgba,origin='lower',extent=extent);ax.set_title(f'{"zyx"[axis]}={index}; added {int(a.sum())} vox');ax.set_xlabel('mm');ax.set_ylabel('mm')
     selection.append({'axis_zyx':axis,'index':index,'added_voxels':int(a.sum())})
   fig.suptitle('p3 real CT continuous-air ENGINEERING EXPLORATION\nCyan: original semantic air after recorded barriers; orange: newly connected CT < -300 air\nNo anatomy assignment, oral separation unreviewed, no CFD admission',fontsize=13)
   fig.tight_layout(rect=(0,0,1,.94));fig.savefig(OUT/'ct-run02-mpr.png',dpi=130);plt.close(fig)
   report['MPR_selection']=selection;report['MPR_path']=str(OUT/'ct-run02-mpr.png');report['MPR_sha256']=sha(OUT/'ct-run02-mpr.png');save()
   print(json.dumps({k:v for k,v in report.items() if k in ('engineering_screen_pass','candidate','new_cut_contact','removed_seed','added_extent','MPR_path')},ensure_ascii=False,indent=2))
  finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__':main()
