from pathlib import Path
import zipfile, io, json, hashlib
import numpy as np
import pydicom
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent
SOURCE = Path(r'D:\项目\鼻腔建模\资料\脱敏的ct信息-1(1).zip')
PREVIOUS = SOURCE.with_name('脱敏的ct信息-2(1).zip')
ROOT.mkdir(parents=True, exist_ok=True)

def window(a, low=-1000, high=1000):
    return Image.fromarray((np.clip((a.astype(float)-low)/(high-low),0,1)*255).astype('uint8'))

def montage(images, labels, cols, size, destination):
    canvas=Image.new('RGB',(cols*size[0],((len(images)+cols-1)//cols)*(size[1]+28)),(15,15,15))
    draw=ImageDraw.Draw(canvas)
    for j,(im,label) in enumerate(zip(images,labels)):
        im=im.convert('RGB'); im.thumbnail(size)
        x=(j%cols)*size[0]+(size[0]-im.width)//2
        y=(j//cols)*(size[1]+28)+(size[1]-im.height)//2
        canvas.paste(im,(x,y)); draw.text(((j%cols)*size[0]+8,(j//cols)*(size[1]+28)+size[1]+5),label,fill='white')
    canvas.save(ROOT/destination)

with zipfile.ZipFile(SOURCE) as z:
    names=[n for n in z.namelist() if not n.endswith('/')]
    data=[(n,pydicom.dcmread(io.BytesIO(z.read(n)))) for n in names]
data.sort(key=lambda item: float(item[1].ImagePositionPatient[2]))
volume=np.stack([d.pixel_array.astype(np.float32)*float(d.RescaleSlope)+float(d.RescaleIntercept) for n,d in data])
row_spacing,col_spacing=map(float,data[0][1].PixelSpacing)
zpos=np.array([float(d.ImagePositionPatient[2]) for n,d in data])
dz=float(np.median(np.diff(zpos)))
indices=np.linspace(0,len(data)-1,20).round().astype(int)
montage([window(volume[i]) for i in indices],
        [f'Instance {data[i][1].InstanceNumber}, z={zpos[i]:.1f} mm' for i in indices],
        5,(320,320),'axial_overview.png')
images=[];labels=[]
for y in [130,160,190,220,250,280]:
    im=window(np.flipud(volume[:,y,:])); im=im.resize((512,round(len(data)*dz/col_spacing)),Image.Resampling.BILINEAR)
    images.append(im); labels.append(f'Coronal y={y}')
for x in [205,225,245,265,285,305]:
    im=window(np.flipud(volume[:,:,x])); im=im.resize((512,round(len(data)*dz/row_spacing)),Image.Resampling.BILINEAR)
    images.append(im); labels.append(f'Sagittal x={x}')
montage(images,labels,3,(512,270),'mpr_overview.png')

hashes=[hashlib.sha256(d.pixel_array.tobytes()).hexdigest() for n,d in data]
previous_hashes=set();previous_first=None
with zipfile.ZipFile(PREVIOUS) as z:
    for n in z.namelist():
        if n.endswith('/'): continue
        d=pydicom.dcmread(io.BytesIO(z.read(n)))
        if previous_first is None: previous_first=d
        previous_hashes.add(hashlib.sha256(d.pixel_array.tobytes()).hexdigest())

first=data[0][1]
instances=sorted(int(d.InstanceNumber) for n,d in data)
keys=['Rows','Columns','PixelSpacing','SliceThickness','SpacingBetweenSlices','ImageOrientationPatient',
      'RescaleSlope','RescaleIntercept','BitsAllocated','BitsStored','PixelRepresentation','ConvolutionKernel',
      'Modality','SOPClassUID','PhotometricInterpretation']
summary={
 'source':str(SOURCE),'archive_entries':len(names),'zip_crc_and_pixel_decode_pass':len(data),
 'shape_zyx':list(volume.shape),'spacing_xyz_mm':[col_spacing,row_spacing,dz],
 'slice_step_min_max_mm':[float(np.diff(zpos).min()),float(np.diff(zpos).max())],
 'coverage_center_to_center_mm':float(zpos[-1]-zpos[0]),
 'instance_range':[instances[0],instances[-1]],
 'missing_instances_within_range':sorted(set(range(instances[0],instances[-1]+1))-set(instances)),
 'unique_sop_instances':len({str(d.SOPInstanceUID) for n,d in data}),
 'unique_pixel_arrays':len(set(hashes)),
 'unique_geometry_positions':len({tuple(map(float,d.ImagePositionPatient)) for n,d in data}),
 'unique_studies':len({str(d.StudyInstanceUID) for n,d in data}),
 'unique_series':len({str(d.SeriesInstanceUID) for n,d in data}),
 'unique_frames_of_reference':len({str(getattr(d,'FrameOfReferenceUID','missing')) for n,d in data}),
 'metadata_unique_values':{k:sorted({str(getattr(d,k,None)) for n,d in data}) for k in keys},
 'missing_metadata_counts':{k:sum(k not in d for n,d in data) for k in ['Modality','SOPClassUID','SOPInstanceUID','ImageType','FrameOfReferenceUID']},
 'file_meta_sop_classes':sorted({str(d.file_meta.MediaStorageSOPClassUID) for n,d in data}),
 'file_meta_and_dataset_sop_instance_match':all(str(d.SOPInstanceUID)==str(d.file_meta.MediaStorageSOPInstanceUID) for n,d in data),
 'file_meta_transfer_syntaxes':sorted({str(d.file_meta.TransferSyntaxUID) for n,d in data}),
 'mapped_intensity_range':[float(volume.min()),float(volume.max())],
 'slices_hu_min_max_mean':[[int(d.InstanceNumber),float(volume[i].min()),float(volume[i].max()),float(volume[i].mean())] for i,(n,d) in enumerate(data)],
 'same_fields_as_previous':{k:str(getattr(first,k,None))==str(getattr(previous_first,k,None)) for k in ['PatientID','StudyInstanceUID','SeriesInstanceUID','FrameOfReferenceUID']},
 'exact_pixel_matches_with_previous':len(set(hashes)&previous_hashes),
 'annotation_files_in_archive':[],
}
(ROOT/'technical_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in ['source','slices_hu_min_max_mean']},ensure_ascii=False,indent=2))
