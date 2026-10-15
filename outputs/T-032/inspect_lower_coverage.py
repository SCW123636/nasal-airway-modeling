"""Read existing CT/labels; produce geometry-labelled lower-field evidence only."""
from pathlib import Path
import os, sys, json, hashlib, datetime
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.SetProcessAffinityMask(ctypes.windll.kernel32.GetCurrentProcess(), 63)
os.environ.setdefault('OMP_NUM_THREADS', '6')
import numpy as np
import SimpleITK as sitk
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

CASES = ('p0','p1','p2','p3','p3t1')
LABELS = ('oropharynx','hypopharynx','soft_palate','submandibular_gland_left','submandibular_gland_right')

def sha(path):
    h = hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def geometry(img):
    return {'size_xyz':list(img.GetSize()),'spacing_xyz':list(img.GetSpacing()),
            'origin_lps_mm':list(img.GetOrigin()),'direction':list(img.GetDirection()),
            'index0_center_lps_mm':list(img.TransformIndexToPhysicalPoint((0,0,0))),
            'last_center_lps_mm':list(img.TransformIndexToPhysicalPoint(tuple(n-1 for n in img.GetSize())))}

def label_info(arr,img):
    zz,yy,xx=np.where(arr>0)
    if not len(zz):return {'voxels':0,'bbox_ijk_xyz':None,'bbox_centers_lps_mm':None}
    lo=(int(xx.min()),int(yy.min()),int(zz.min()))
    hi=(int(xx.max()),int(yy.max()),int(zz.max()))
    return {'voxels':len(zz),'bbox_ijk_xyz':[lo,hi],
            'bbox_centers_lps_mm':[img.TransformIndexToPhysicalPoint(lo),img.TransformIndexToPhysicalPoint(hi)],
            'inferior_face_voxels':int((arr[0]>0).sum())}

def main():
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=False)
    fig,axes=plt.subplots(len(CASES),3,figsize=(15,22),layout='constrained')
    report={'created':datetime.datetime.now().astimezone().isoformat(),'scope':'Engineering CT field audit; no anatomical boundary assigned','cases':{}}
    for i,k in enumerate(CASES):
        base=Path('C:/ts_work')/k
        ctpath=base/'ct.nii.gz';img=sitk.ReadImage(str(ctpath));a=sitk.GetArrayFromImage(img)
        if not np.allclose(img.GetDirection(),np.eye(3).ravel()):raise ValueError('visualizer requires confirmed identity LPS direction')
        row={'ct_sha256':sha(ctpath),'geometry':geometry(img),'labels':{}}
        masks={}
        for label in LABELS:
            p=base/'masks'/(label+'.nii.gz')
            if not p.exists():row['labels'][label]={'missing':True};continue
            mi=sitk.ReadImage(str(p))
            if geometry(mi)!=geometry(img):raise ValueError(k+' grid mismatch '+label)
            ma=sitk.GetArrayFromImage(mi)>0
            row['labels'][label]={**label_info(ma,img),'sha256':sha(p)}
            masks[label]=ma
        oro=masks['oropharynx'];zz,yy,xx=np.where(oro)
        x=int(np.median(xx));y=int(np.median(yy));row['display_indices']={'sagittal_x':x,'coronal_y':y,'axial_z':0}
        o=np.array(img.GetOrigin());s=np.array(img.GetSpacing());n=np.array(img.GetSize())
        bounds=np.stack((o-.5*s,o+(n-.5)*s))
        row['voxel_outer_bounds_lps_mm']=bounds.tolist()
        zmax=min(a.shape[0],int(np.ceil(100/s[2])))
        e_sag=[bounds[0,1],bounds[1,1],bounds[0,2],o[2]+(zmax-.5)*s[2]]
        e_cor=[bounds[0,0],bounds[1,0],bounds[0,2],o[2]+(zmax-.5)*s[2]]
        e_axi=[bounds[0,0],bounds[1,0],bounds[0,1],bounds[1,1]]
        views=[(a[:zmax,:,x],oro[:zmax,:,x],e_sag,'P (mm)','S (mm)',f'Sagittal L={o[0]+x*s[0]:.2f}'),
               (a[:zmax,y,:],oro[:zmax,y,:],e_cor,'L (mm)','S (mm)',f'Coronal P={o[1]+y*s[1]:.2f}'),
               (a[0],oro[0],e_axi,'L (mm)','P (mm)',f'Inferior axial S={o[2]:.2f}')]
        for j,(gray,mask,extent,xlab,ylab,title) in enumerate(views):
            ax=axes[i,j];ax.imshow(gray,cmap='gray',vmin=-1000,vmax=600,origin='lower',extent=extent,interpolation='nearest')
            overlay=np.zeros((*mask.shape,4));overlay[mask]=[0.1,1.,0.4,.32]
            ax.imshow(overlay,origin='lower',extent=extent,interpolation='nearest')
            ax.set(xlabel=xlab,ylabel=ylab,title=f'{k} | {title}')
            for spine in ax.spines.values():spine.set_color('magenta');spine.set_linewidth(2)
            if j<2:ax.axhline(bounds[0,2],color='magenta',linewidth=2)
        report['cases'][k]=row
    fig.suptitle('Existing CT lower field | green=existing oropharynx | magenta=scan boundary\nLPS coordinates in mm; no hypopharynx contour assigned',fontsize=14)
    fig.savefig(out/'five_case_lower_mpr.png',dpi=130);plt.close(fig)
    (out/'coverage.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:{'geometry':v['geometry'],'labels':{l:{a:b for a,b in d.items() if a!='sha256'} for l,d in v['labels'].items()}} for k,v in report['cases'].items()},ensure_ascii=False))

if __name__=='__main__':main()
