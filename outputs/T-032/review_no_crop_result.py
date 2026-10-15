"""Read actual frozen no-crop result; create a lower-field comparison and refusal record."""
from pathlib import Path
import json,hashlib,datetime,shutil,os
import numpy as np
import SimpleITK as sitk
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent
RUN=Path(r'C:\ts_work\t032_hypopharynx\01_p2_no_crop')
OUT=ROOT/'runs/02_p2_no_crop_result'

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir(parents=True,exist_ok=False)
    cti=sitk.ReadImage('C:/ts_work/p2/ct.nii.gz');ct=sitk.GetArrayFromImage(cti)
    segi=sitk.ReadImage(str(RUN/'semantic_775_nocrop.nii.gz'));seg=sitk.GetArrayFromImage(segi)
    old=sitk.GetArrayFromImage(sitk.ReadImage('C:/ts_work/p2/masks/oropharynx.nii.gz'))>0
    oldhyp=sitk.GetArrayFromImage(sitk.ReadImage('C:/ts_work/p2/masks/hypopharynx.nii.gz'))>0
    def geom(i):return {'size':i.GetSize(),'spacing':i.GetSpacing(),'origin_lps_mm':i.GetOrigin(),'direction':i.GetDirection()}
    if geom(cti)!=geom(segi):raise ValueError('geometry mismatch')
    if not np.allclose(cti.GetDirection(),np.eye(3).ravel()):raise ValueError('identity LPS needed for direct planes')
    xyz=np.array(cti.GetSize());o=np.array(cti.GetOrigin());s=np.array(cti.GetSpacing())
    low=o-.5*s;high=o+(xyz-.5)*s
    z,y,x=np.where(old);x=int(np.median(x));y=int(np.median(y))
    zmax=min(ct.shape[0],int(np.ceil(100/s[2])))
    fig,axes=plt.subplots(2,3,figsize=(16,10),layout='constrained')
    labels=(old,seg==12)
    for row,mask in enumerate(labels):
        name=('Existing model with skull crop','New full-field no-crop inference')[row]
        extents=([low[1],high[1],low[2],o[2]+(zmax-.5)*s[2]],
                 [low[0],high[0],low[2],o[2]+(zmax-.5)*s[2]],
                 [low[0],high[0],low[1],high[1]])
        views=((ct[:zmax,:,x],mask[:zmax,:,x],'P (mm)','S (mm)',f'Sagittal L={o[0]+x*s[0]:.2f}'),
               (ct[:zmax,y,:],mask[:zmax,y,:],'L (mm)','S (mm)',f'Coronal P={o[1]+y*s[1]:.2f}'),
               (ct[0],mask[0],'L (mm)','P (mm)',f'Inferior axial S={o[2]:.2f}'))
        for col,(a,m,xlabel,ylabel,title) in enumerate(views):
            ax=axes[row,col];ax.imshow(a,cmap='gray',vmin=-1000,vmax=600,origin='lower',extent=extents[col],interpolation='nearest')
            overlay=np.zeros((*m.shape,4));overlay[m]=[0.1,1,0.4,.35]
            ax.imshow(overlay,origin='lower',extent=extents[col],interpolation='nearest')
            ax.set(xlabel=xlabel,ylabel=ylabel,title=f'{name}\n{title}')
            for spine in ax.spines.values():spine.set_color('magenta');spine.set_linewidth(2)
    fig.suptitle('p2 | real full-field semantic control\nGreen=oropharynx class12; hypopharynx class13 remains empty in both; magenta=scan boundary',fontsize=15)
    fig.savefig(OUT/'p2_real_no_crop_comparison.png',dpi=130);plt.close(fig)
    raw=sitk.GetArrayFromImage(sitk.ReadImage(str(RUN/'hypopharynx_semantic.nii.gz')))>0
    air=sitk.GetArrayFromImage(sitk.ReadImage(str(RUN/'hypopharynx_air_candidate.nii.gz')))>0
    expected=(seg==13)&(ct < -300)
    report={'created':datetime.datetime.now().astimezone().isoformat(),'case':'p2','symptom_patient_mapping':'unknown',
            'geometry':geom(cti),'display_indices_xyz':{'sagittal_x':x,'coronal_y':y,'inferior_axial_z':0},
            'image_outer_bounds_lps_mm':[low.tolist(),high.tolist()],
            'raw_hypopharynx_exact_semantic_class13':bool(np.array_equal(raw,seg==13)),
            'air_exact_class13_and_CT_lt_minus300':bool(np.array_equal(air,expected)),
            'old_hypopharynx_voxels':int(oldhyp.sum()),'new_hypopharynx_voxels':int(raw.sum()),'new_hypopharynx_air_voxels':int(air.sum()),
            'new_oropharynx_voxels':int((seg==12).sum()),'new_oropharynx_inferior_face_voxels':int((seg[0]==12).sum()),
            'hypopharynx_display_admission':False,'hypopharynx_display_refusal':'empty_semantic_label_after_real_no_crop_inference',
            'medical_review':'pending','cfd_admission':False,
            'no_anatomical_absence_inference':'Empty semantic output does not alone establish absence of scanned anatomy',
            'raw_outputs':{p.name:{'path':str(p),'sha256':sha(p)} for p in RUN.glob('*.nii.gz')},
            'ct_sha256':sha(Path('C:/ts_work/p2/ct.nii.gz')),
            'preview_sha256':sha(OUT/'p2_real_no_crop_comparison.png')}
    (OUT/'exact_result_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for name in ('run_status.json',):shutil.copyfile(RUN/name,OUT/name)
    shutil.copyfile(ROOT/'p2_no_crop_inference.log',OUT/'p2_no_crop_inference.log')
    print(json.dumps({k:v for k,v in report.items() if k not in ('raw_outputs','geometry')},ensure_ascii=False))

if __name__=='__main__':main()
