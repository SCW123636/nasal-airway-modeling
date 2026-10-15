"""T-019: read-only inventory and grayscale samples of supplied references.

No segmentation, resampling, inference, meshing, or solving is performed.
All DICOM decoding goes through the project's load_series_sitk reader.
Images stay local and are excluded by this directory's .gitignore.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time
import traceback

PROJECT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = PROJECT / '资料' / '4例演示ct'
CASE_NAMES = {
    'case_a': '（患者a）鼻中隔+鼻甲消融+其他',
    'case_b': '（患者b）鼻甲消融',
    'case_medial': '鼻甲内移',
    'case_lateral': '鼻甲外移',
}
TARGETS = {
    'case_lateral': ['10003-3D_Sinus^_1', '10004-3D_Sinus^_2',
                     '10005-3D_Sinus^_3', '10006-3D_Sinus^_4'],
    'case_medial': ['10002-CH', '10005-CH_4'],
    'case_b': ['1011-MPR 3.0mm'],
    'case_a': ['ISO_Bone_0.35mm_part2/ISO_Bone_0.35mm'],
}

def acceptable(p: Path) -> bool:
    return '__MACOSX' not in p.parts and not p.name.startswith('._')

def digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def dump(name: str, data: object):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def sanitized_error(message: str) -> str:
    message = re.sub(r'\b[A-Za-z]:[\\/][^\n\r]*?\.dcm', '<source_file>', message, flags=re.I)
    message = re.sub(r'\b[A-Za-z]:[\\/](?:[^\n\r\\/]*[\\/])*([^\\/\n\r]+?\.(?:cxx|hxx|cpp|h))(?=:\d)',
                     r'<build>/\1', message)
    message = re.sub(r'ImageSeriesReader\([0-9A-Fa-fx]+\)', 'ImageSeriesReader(<address>)', message)
    return message

def roots():
    result = {}
    for key, name in CASE_NAMES.items():
        matches = [p for p in SOURCE.rglob(name) if p.is_dir() and acceptable(p)]
        if len(matches) != 1:
            raise RuntimeError(f'{key}: expected one source directory, found {len(matches)}')
        result[key] = matches[0]
    return result

def locator(root: Path, directory: Path) -> str:
    """Drop study folder (which can contain sensitive names); retain series labels."""
    parts = directory.relative_to(root).parts
    if parts and parts[0].startswith('ISO_'):
        return '/'.join(parts)
    return parts[-1] if parts else '.'

def inventory(case_roots):
    start = time.perf_counter()
    result = {'schema': 'T019_reference_inventory/v1',
              'started_local': datetime.now().astimezone().isoformat(),
              'source': '资料/4例演示ct',
              'exclusion': '__MACOSX anywhere, filenames beginning ._',
              'cases': [], 'standalone_result_files': []}
    extension_counts = Counter()
    all_files = [p for p in SOURCE.rglob('*') if p.is_file() and acceptable(p)]
    for p in all_files:
        extension_counts[p.suffix.lower() or '<no extension>'] += 1
    for key, root in case_roots.items():
        files = [p for p in root.rglob('*') if p.is_file() and acceptable(p)]
        by_dir = {}
        for p in files:
            if p.suffix.lower() == '.dcm':
                by_dir.setdefault(p.parent, []).append(p)
        series = []
        for directory, dcms in sorted(by_dir.items()):
            series.append({'series': locator(root, directory), 'dicom_files': len(dcms),
                           'bytes': sum(p.stat().st_size for p in dcms)})
        result['cases'].append({'case': key, 'source_case_label': CASE_NAMES[key],
                                'dicom_files': sum(s['dicom_files'] for s in series),
                                'series': series})
    result['all_file_extensions'] = dict(sorted(extension_counts.items()))
    result['dicom_files_total'] = extension_counts['.dcm']
    result['standalone_result_extensions_checked'] = ['.stl','.vtk','.vtp','.vtu','.obj','.ply',
        '.png','.jpg','.jpeg','.bmp','.tif','.tiff','.gif','.mp4','.avi','.mov','.webm','.mkv']
    for p in all_files:
        if p.suffix.lower() in result['standalone_result_extensions_checked']:
            result['standalone_result_files'].append({'extension': p.suffix.lower(), 'bytes': p.stat().st_size})
    result['elapsed_seconds'] = round(time.perf_counter() - start, 3)
    result['dicom_embedded_content_boundary'] = 'External file enumeration does not establish absence of DICOM reconstructions, screenshots, or encapsulated documents.'
    dump('inventory.json', result)
    print(json.dumps({'inventory_written': True, 'dicom_files_total': result['dicom_files_total'],
                      'extensions': result['all_file_extensions'],
                      'case_counts': {c['case']: c['dicom_files'] for c in result['cases']}}, ensure_ascii=False), flush=True)
    return result

def previews(case_roots, only_cases=None):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    sys.path.insert(0, str(PROJECT / 'work' / 'lib'))
    from dicom_sitk import load_series_sitk
    previous = OUT / 'previews.json'
    old_records = json.loads(previous.read_text(encoding='utf-8'))['records'] if previous.exists() else []
    records = [r for r in old_records if only_cases and r['case'] not in only_cases]
    for case, targets in TARGETS.items():
        if only_cases and case not in only_cases:
            continue
        panels = []
        for target in targets:
            root = case_roots[case]
            matches = [p for p in root.rglob('*') if p.is_dir() and acceptable(p)
                       and locator(root, p) == target]
            if len(matches) != 1:
                raise RuntimeError(f'{case}/{target}: expected one directory, got {len(matches)}')
            directory = matches[0]
            begun = time.perf_counter()
            record = {'case': case, 'series': target, 'reader': 'work/lib/dicom_sitk.py::load_series_sitk'}
            try:
                vol, spacing, origin, meta = load_series_sitk(str(directory), verbose=False)
                indexes = sorted(set([0, vol.shape[0] // 2, vol.shape[0] - 1]))
                # Only whitelist geometric and technical metadata; no patient/study identifiers.
                record.update({'shape': list(vol.shape), 'dtype': str(vol.dtype),
                               'spacing_xyz_mm': list(spacing), 'slice_indices_0based': indexes,
                               'value_range': [float(np.min(vol)), float(np.max(vol))],
                               'modality': meta.get('modality'),
                               'series_description': meta.get('series_description'),
                               'source_files': meta.get('n_files')})
                display_8bit = float(np.min(vol)) >= 0 and float(np.max(vol)) <= 255
                low, high = (0.,255.) if display_8bit else (-200.,1800.)
                record['display_window'] = {'low': low, 'high': high,
                    'label': 'grayscale 0..255' if display_8bit else 'WL 800 / WW 2000',
                    'is_diagnostic_window': False}
                for k in indexes:
                    frame = np.asarray(vol[k], dtype=np.float32)
                    if frame.ndim == 3:
                        frame = frame[...,:3].mean(axis=-1)
                    arr = np.clip((frame-low)/(high-low)*255.,0.,255.).astype('uint8')
                    im = Image.fromarray(arr, mode='L').convert('RGB')
                    im.thumbnail((460,460), Image.Resampling.LANCZOS)
                    panel = Image.new('RGB',(480,530),'#222222')
                    panel.paste(im,((480-im.width)//2,52+(460-im.height)//2))
                    d = ImageDraw.Draw(panel)
                    d.text((10,8),f'{case} | {target}', fill='white')
                    d.text((10,26),f'index {k}/{vol.shape[0]-1} | window {low:g}..{high:g}', fill='white')
                    panels.append(panel)
                record['decoded'] = True
                # Fingerprint is over file content hashes, sorted independently of filenames.
                hashes = sorted(digest(p) for p in directory.iterdir() if p.is_file() and acceptable(p) and p.suffix.lower()=='.dcm')
                record['fileset_sha256'] = hashlib.sha256('\n'.join(hashes).encode('ascii')).hexdigest()
                del vol
            except Exception as exc:
                raw = traceback.format_exc()
                (OUT / f'_local_{case}_{target.replace("/", "_")}_error.log').write_text(raw, encoding='utf-8')
                sanitized = sanitized_error(str(exc))
                record.update({'decoded': False, 'error_type': type(exc).__name__,
                               'error': sanitized,
                               'local_raw_error_ignored_by_git': True})
            record['elapsed_seconds'] = round(time.perf_counter() - begun,3)
            records.append(record)
            dump('previews.json', {'schema':'T019_previews/v1','records': records})
            print(json.dumps({'preview': f'{case}/{target}', 'decoded':record['decoded'],
                              'shape':record.get('shape'), 'value_range':record.get('value_range')},ensure_ascii=False), flush=True)
        if panels:
            rows = (len(panels)+2)//3
            sheet = Image.new('RGB',(1440,rows*530),'#111111')
            for i,panel in enumerate(panels):
                sheet.paste(panel,((i%3)*480,(i//3)*530))
            sheet.save(OUT / f'contact_{case}.png')
            print(f'contact_saved: contact_{case}.png', flush=True)
    return records

def heterogeneous_frame_probe(case_roots):
    """Stage only error-identified files; use the same reader on each file directory.

    This does not fix or regroup the production series. The staging is local-only.
    Contact images show a central crop to avoid peripheral burned-in identifiers.
    """
    import numpy as np
    from PIL import Image, ImageDraw
    sys.path.insert(0, str(PROJECT / 'work' / 'lib'))
    from dicom_sitk import load_series_sitk
    records=[]
    panels=[]
    for series in TARGETS['case_medial']:
        raw_path=OUT/f'_local_case_medial_{series}_error.log'
        raw=raw_path.read_text(encoding='utf-8')
        # Only select the two files explicitly named by the failed series reader.
        matches=re.findall(r'\b[A-Za-z]:[\\/][^\n\r]*?\.dcm',raw,flags=re.I)
        paths=[]
        for item in matches:
            pth=Path(item)
            if pth.is_file() and pth not in paths:
                paths.append(pth)
        for i,source in enumerate(paths):
            stage=OUT/'_local_staged'/'case_medial'/series/f'error_file_{i}'
            stage.mkdir(parents=True,exist_ok=True)
            destination=stage/'frame.dcm'
            shutil.copyfile(source,destination)
            record={'case':'case_medial','series':series,'error_file_index':i,
                    'source_file_sha256':digest(source),
                    'source_listing_index_0based':sorted(source.parent.glob('*.dcm')).index(source),
                    'reader':'work/lib/dicom_sitk.py::load_series_sitk',
                    'staging':'Single unchanged DICOM file copied into local-only isolated directory.'}
            try:
                vol,sp,org,meta=load_series_sitk(str(stage),verbose=False)
                record.update({'decoded':True,'shape':list(vol.shape),'dtype':str(vol.dtype),
                               'value_range':[float(vol.min()),float(vol.max())],
                               'display_slice_index_0based':0})
                frame=np.asarray(vol[0],dtype=np.float32)
                if frame.ndim==3:
                    frame=frame[...,:3].mean(axis=-1)
                low,high=(0.,255.) if frame.min()>=0 and frame.max()<=255 else (-200.,1800.)
                im=Image.fromarray(np.clip((frame-low)/(high-low)*255,0,255).astype('uint8'),'L').convert('RGB')
                # Keep the original image local. Do not expose source basenames.
                im.save(OUT/f'_local_{series}_error_file_{i}_full.png')
                w,h=im.size
                crop=(int(w*.1),int(h*.15),int(w*.9),int(h*.9))
                im=im.crop(crop)
                im.thumbnail((620,460),Image.Resampling.LANCZOS)
                panel=Image.new('RGB',(640,530),'#222222')
                panel.paste(im,((640-im.width)//2,52+(460-im.height)//2))
                draw=ImageDraw.Draw(panel)
                draw.text((10,8),f'case_medial | {series} | error file {i}',fill='white')
                draw.text((10,26),f'original {w}x{h} | center display crop | window {low:g}..{high:g}',fill='white')
                panels.append(panel)
                record['display_crop_xyxy_original_pixels']=list(crop)
                record['display_window']={'low':low,'high':high}
            except Exception as exc:
                (OUT/f'_local_{series}_error_file_{i}.log').write_text(traceback.format_exc(),encoding='utf-8')
                record.update({'decoded':False,'error':sanitized_error(str(exc))})
            records.append(record)
            dump('heterogeneous_frames.json',{'schema':'T019_heterogeneous_frames/v1','records':records})
            print(json.dumps({'series':series,'error_file_index':i,'decoded':record['decoded'],
                              'shape':record.get('shape'),'value_range':record.get('value_range')},ensure_ascii=False),flush=True)
    if panels:
        sheet=Image.new('RGB',(1280,((len(panels)+1)//2)*530),'#111111')
        for i,panel in enumerate(panels):
            sheet.paste(panel,((i%2)*640,(i//2)*530))
        sheet.save(OUT/'contact_case_medial_error_frames.png')
        print('contact_saved: contact_case_medial_error_frames.png',flush=True)

def mapping_probe(case_roots):
    """Compare a few complete-file hashes; never infer scan inequality from de-ID."""
    candidates=[('p0','case_a','ISO_Bone_0.35mm',None),
                ('p1','case_lateral','202-1.0 x 0.8 Bone','患者1'),
                ('p2','case_b','4-Sinus  0.75  H40s','患者2'),
                ('p3','case_medial','202-0.6 x 0.6_BONE','患者3')]
    records=[]
    for current,case,series,group in candidates:
        if current=='p0':
            sources=[]
            for part in (1,2,3):
                directory=case_roots[case]/f'{series}_part{part}'/series
                sources.extend(p for p in directory.iterdir() if p.is_file() and acceptable(p) and p.suffix.lower()=='.dcm')
            current_dir=PROJECT/'work'/'00_dicom'/'bone'
        else:
            source_dirs=[p for p in case_roots[case].rglob(series) if p.is_dir() and acceptable(p)]
            current_dirs=[p for p in (PROJECT/'资料'/'脱敏数据_clean'/group).rglob(series) if p.is_dir() and acceptable(p)]
            if len(source_dirs)!=1 or len(current_dirs)!=1:
                records.append({'current_case':current,'source_case':case,'status':'ambiguous_directory_match'})
                continue
            sources=[p for p in source_dirs[0].iterdir() if p.is_file() and acceptable(p) and p.suffix.lower()=='.dcm']
            current_dir=current_dirs[0]
        sources=sorted(sources,key=lambda p:p.name)
        current_files=[p for p in current_dir.iterdir() if p.is_file() and acceptable(p) and p.suffix.lower()=='.dcm']
        shared=[p for p in sources if (current_dir/p.name).is_file()]
        indexes=sorted(set([0,len(shared)//2,len(shared)-1])) if shared else []
        samples=[]
        for i in indexes:
            source=shared[i]
            samples.append({'shared_filename_sort_index_0based':i,
                            'source_sha256':digest(source),'current_sha256':digest(current_dir/source.name)})
            samples[-1]['complete_file_hash_equal']=samples[-1]['source_sha256']==samples[-1]['current_sha256']
        records.append({'current_case':current,'source_case':case,'series':series,
                        'source_dicom_count':len(sources),'current_dicom_count':len(current_files),
                        'shared_filenames_count':len(shared),'samples':samples,
                        'status':'candidate_only_unless_hash_confirmed',
                        'boundary':'An unequal complete-file hash can result from de-identification; it does not establish a different scan.'})
    readmes=[p for p in SOURCE.rglob('*') if p.is_file() and acceptable(p) and p.suffix.lower()=='.txt']
    dump('candidate_mapping.json',{'schema':'T019_candidate_mapping/v1','records':records,
                                 'readme_sha256':[digest(p) for p in readmes],
                                 'p3t1':'No corresponding earlier-timepoint series located in the four supplied case directories.'})
    print(json.dumps({'mapping_written':True,'candidates':[{k:r.get(k) for k in ('current_case','source_case','source_dicom_count','current_dicom_count','shared_filenames_count')} for r in records]},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--inventory-only',action='store_true')
    p.add_argument('--case', action='append', choices=list(CASE_NAMES))
    p.add_argument('--heterogeneous-frame-probe',action='store_true')
    p.add_argument('--mapping-probe',action='store_true')
    args=p.parse_args()
    case_roots=roots()
    if args.mapping_probe:
        mapping_probe(case_roots)
        return
    if args.heterogeneous_frame_probe:
        heterogeneous_frame_probe(case_roots)
        return
    inventory(case_roots)
    if not args.inventory_only:
        previews(case_roots,args.case)

if __name__ == '__main__':
    main()
