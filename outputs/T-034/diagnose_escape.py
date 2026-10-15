"""Trace a real six-neighbour escape path; no image or barrier mutation."""
import os
for n in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[n]='1'
import sys,json,heapq,time,msvcrt,ctypes,urllib.request,subprocess
from pathlib import Path
ROOT=Path(r'D:\项目\鼻腔建模');sys.path.insert(0,str(ROOT/'work/lib'))
OUT=ROOT/'outputs/T-034'
import numpy as np,SimpleITK as sitk
from anatomy_barrier_seg import plane_keep_mask
from continuous_air_candidate import index_to_lps

def main():
  kernel=ctypes.windll.kernel32;kernel.GetCurrentProcess.restype=ctypes.c_void_p
  kernel.SetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_size_t];kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(),63)
  sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
  with urllib.request.urlopen('http://127.0.0.1:8769/api/simulation/jobs') as f:
    if any(j['status'] in ('queued','running') for j in json.load(f)['jobs']):raise RuntimeError('CPU busy')
  with urllib.request.urlopen('http://127.0.0.1:8769/api/cases') as f:
    if any(j['status'] in ('queued','running') for j in json.load(f)['cases']):raise RuntimeError('CPU busy')
  uptime=subprocess.run(['wsl','-e','sh','-lc','uptime'],capture_output=True,text=True,check=True).stdout.strip()
  with Path(r'C:\ts_work\project_cases\pipeline.lock').open('r+b') as lock:
    lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
      image=sitk.ReadImage(r'C:\ts_work\p3\ct.nii.gz');ct=sitk.GetArrayFromImage(image)
      seed=sitk.GetArrayFromImage(sitk.ReadImage(r'C:\ts_work\t034_continuous_air\run01\semantic_air_after_barriers.nii.gz'))>0
      config=json.loads((ROOT/'work/06_auto_landmarks/p3/review_config_proposed.json').read_text(encoding='utf-8'))
      allowed=np.ones(ct.shape,bool)
      for n in ('nostril_L','nostril_R'):allowed &= plane_keep_mask(image,config['planes_lps'][n],ct.shape)
      air=(ct < -300)&allowed; del allowed
      coords=np.argwhere(seed);start=tuple(map(int,coords[np.argmin(coords[:,1])]))
      # A* to any lateral CT face, with admissible Manhattan heuristic.
      shape=air.shape
      def h(p):z,y,x=p;return min(y,shape[1]-1-y,x,shape[2]-1-x)
      q=[(h(start),0,start)];best={start:0};prev={};visited=set();target=None;t0=time.monotonic()
      while q:
        _,g,p=heapq.heappop(q)
        if p in visited:continue
        visited.add(p)
        if h(p)==0:target=p;break
        if len(visited)>1000000 or time.monotonic()-t0>40:break
        for axis in range(3):
          for delta in (-1,1):
            v=list(p);v[axis]+=delta
            if v[axis]<0 or v[axis]>=shape[axis]:continue
            v=tuple(v)
            if not air[v] or v in visited or g+1>=best.get(v,10**12):continue
            best[v]=g+1;prev[v]=p;heapq.heappush(q,(g+1+h(v),g+1,v))
      report={'case':'p3','wsl_uptime':uptime,'visited':len(visited),'seconds':time.monotonic()-t0,'start_zyx':start,'found_escape':target is not None,'path_zyx':[]}
      if target:
        path=[target]
        while path[-1]!=start:path.append(prev[path[-1]])
        path=path[::-1];report['path_zyx']=path;report['path_LPS_mm']=index_to_lps(np.array(path)[:,::-1],image).tolist()
        report['path_all_strict_air']=all(ct[p] < -300 for p in path)
        report['path_6_neighbour']=all(sum(abs(a-b) for a,b in zip(path[i],path[i+1]))==1 for i in range(len(path)-1))
        report['path_n']=len(path)
      (OUT/'escape-path.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
      # CT comparison is a diagnostic, the leaked domain is not a candidate.
      import matplotlib;matplotlib.use('Agg')
      import matplotlib.pyplot as plt
      leak=sitk.GetArrayFromImage(sitk.ReadImage(r'C:\ts_work\t034_continuous_air\run01\connected_air_after_barriers.nii.gz'))>0
      z,y,x=start
      fig,axs=plt.subplots(1,3,figsize=(15,6))
      arrays=[(ct[z],seed[z],leak[z],(image.GetSpacing()[0],image.GetSpacing()[1]),f'Axial z={z}'),
        (ct[:,y,:],seed[:,y,:],leak[:,y,:],(image.GetSpacing()[0],image.GetSpacing()[2]),f'Coronal y={y}'),
        (ct[:,:,x],seed[:,:,x],leak[:,:,x],(image.GetSpacing()[1],image.GetSpacing()[2]),f'Sagittal x={x}')]
      for ax,(c,s,l,sp,title) in zip(axs,arrays):
        extent=[0,c.shape[1]*sp[0],0,c.shape[0]*sp[1]]
        ax.imshow(c,cmap='gray',vmin=-1000,vmax=500,origin='lower',extent=extent)
        rgba=np.zeros(c.shape+(4,));rgba[l]=[1,.35,.1,.25];rgba[s]=[0,.9,1,.9]
        ax.imshow(rgba,origin='lower',extent=extent);ax.set_title(title);ax.set_xlabel('mm');ax.set_ylabel('mm')
      fig.suptitle('p3 REAL CT: cyan semantic seed; orange leaked connected air (REJECTED)\nCT < -300 HU, unchanged proposed nostril finite barriers; not anatomy/CFD admitted')
      fig.tight_layout();fig.savefig(OUT/'ct-leak-diagnostic.png',dpi=140);plt.close(fig)
      print(json.dumps({k:v for k,v in report.items() if not k.startswith('path_')},ensure_ascii=False));print('CT: '+str(OUT/'ct-leak-diagnostic.png'))
    finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

if __name__=='__main__':main()
