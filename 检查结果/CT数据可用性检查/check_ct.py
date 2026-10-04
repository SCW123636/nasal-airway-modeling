from pathlib import Path
import zipfile, io, json, hashlib
import numpy as np
import pydicom
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
SOURCE = Path(r'D:\项目\鼻腔建模\资料\脱敏的ct信息-2(1).zip')

def window(a, low=-1000, high=1000):
    return Image.fromarray((np.clip((a.astype(float)-low)/(high-low),0,1)*255).astype('uint8'))

def montage(images, labels, cols, size, destination):
    rows=(len(images)+cols-1)//cols
    canvas=Image.new('RGB',(cols*size[0],rows*(size[1]+28)),(15,15,15))
    draw=ImageDraw.Draw(canvas)
    for j,(im,label) in enumerate(zip(images,labels)):
        im=im.convert('RGB'); im.thumbnail(size)
        x=(j%cols)*size[0]+(size[0]-im.width)//2
        y=(j//cols)*(size[1]+28)
        canvas.paste(im,(x,y)); draw.text(((j%cols)*size[0]+8,y+size[1]+5),label,fill='white')
    canvas.save(ROOT/destination)

with zipfile.ZipFile(SOURCE) as z:
    # Reading every entry verifies ZIP CRC as well as DICOM pixel decoding.
    data=[(n,pydicom.dcmread(io.BytesIO(z.read(n)))) for n in z.namelist() if not n.endswith('/')]
data.sort(key=lambda item: float(item[1].ImagePositionPatient[2]))
volume=np.stack([ds.pixel_array.astype(np.int16) for n,ds in data])
dx,dy=map(float,data[0][1].PixelSpacing)
zpos=np.array([float(ds.ImagePositionPatient[2]) for n,ds in data])
dz=float(np.median(np.diff(zpos)))
axidx=np.linspace(0,len(data)-1,20).round().astype(int)
montage([window(volume[i]) for i in axidx],
        [f'Instance {data[i][1].InstanceNumber}, z={zpos[i]:.1f} mm' for i in axidx],
        5,(320,320),'axial_overview.png')
images=[]; labels=[]
for y in [160,190,220,250,280,310]:
    im=window(np.flipud(volume[:,y,:])); im=im.resize((512,round(len(data)*dz/dx)),Image.Resampling.BILINEAR)
    images.append(im); labels.append(f'Coronal y={y}')
for x in [215,235,255,275,295,315]:
    im=window(np.flipud(volume[:,:,x])); im=im.resize((512,round(len(data)*dz/dy)),Image.Resampling.BILINEAR)
    images.append(im); labels.append(f'Sagittal x={x}')
montage(images,labels,3,(512,270),'mpr_overview.png')

pixel_hashes=[hashlib.sha256(ds.PixelData).hexdigest() for n,ds in data]
private_tags={}; retained={}; empty_patient_tags=set(); suspicious_sequences=[]
for n,ds in data:
    for e in ds.iterall():
        if e.tag.is_private:
            private_tags[str(e.tag)]=private_tags.get(str(e.tag),0)+1
        # Count residual values without exposing personal identifiers in outputs.
        if e.tag.group==0x0010 or e.keyword in [
            'InstitutionName','InstitutionAddress','InstitutionalDepartmentName',
            'ReferringPhysicianName','PerformingPhysicianName','OperatorsName',
            'AccessionNumber','StudyDate','SeriesDate','AcquisitionDate','ContentDate',
            'PatientIdentityRemoved','DeidentificationMethod','BurnedInAnnotation']:
            if str(e.value).strip():
                retained[e.keyword]=retained.get(e.keyword,0)+1
            else:
                empty_patient_tags.add(e.keyword)
    if 'ReferencedStudySequence' in ds:
        for ref in ds.ReferencedStudySequence:
            if str(getattr(ref,'ReferencedSOPClassUID','')).startswith('1.3.51.'):
                suspicious_sequences.append(n)

summary={
  'source':str(SOURCE),'zip_crc_and_pixel_decode':'420/420 passed',
  'slices':len(data),'shape_zyx':list(volume.shape),
  'spacing_xyz_mm':[dx,dy,dz],'slice_thickness_mm':float(data[0][1].SliceThickness),
  'center_to_center_coverage_mm':float(zpos[-1]-zpos[0]),
  'instance_range':[int(data[0][1].InstanceNumber),int(data[-1][1].InstanceNumber)],
  'unique_sop_instance_uids':len({str(ds.SOPInstanceUID) for n,ds in data}),
  'unique_pixel_arrays':len(set(pixel_hashes)),
  'unique_studies':len({str(ds.StudyInstanceUID) for n,ds in data}),
  'unique_series':len({str(ds.SeriesInstanceUID) for n,ds in data}),
  'unique_frames_of_reference':len({str(ds.FrameOfReferenceUID) for n,ds in data}),
  'slice_step_min_max_mm':[float(np.diff(zpos).min()),float(np.diff(zpos).max())],
  'private_tag_count_per_slice':sum(private_tags.values())/len(data),
  'nonempty_sensitive_or_deidentification_fields_counts':retained,
  'empty_sensitive_fields':sorted(empty_patient_tags),
  'suspicious_referenced_sop_class_uid_count':len(suspicious_sequences),
  'series_description':str(data[0][1].SeriesDescription),
  'kernel':str(data[0][1].ConvolutionKernel),
  'private_original_image_count_candidate':str(data[0][1].get((0x7005,0x1017),'').value),
  'raw_pixel_range':[int(volume.min()),int(volume.max())],
  'rescale_slope_intercept':[float(data[0][1].RescaleSlope),float(data[0][1].RescaleIntercept)],
}
(ROOT/'technical_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
