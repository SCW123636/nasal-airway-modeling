"""Independent, sanitized T-019 reference check. Never modify source inputs."""
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / '资料' / '4例演示ct'
OUT = Path(__file__).resolve().parent
DELIVERY = OUT.parent
CASE_NAMES = {
    'case_a': '（患者a）鼻中隔+鼻甲消融+其他',
    'case_b': '（患者b）鼻甲消融',
    'case_medial': '鼻甲内移',
    'case_lateral': '鼻甲外移',
}

def eligible(path):
    return '__MACOSX' not in path.parts and not path.name.startswith('._')

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def safe_series(root, directory):
    rel = directory.relative_to(root).parts
    return '/'.join(rel) if rel and rel[0].startswith('ISO_') else directory.name

def note_facts(path):
    content = None
    encoding = None
    for enc in ('utf-8-sig', 'gb18030', 'utf-16'):
        try:
            content = path.read_text(encoding=enc)
            encoding = enc
            break
        except UnicodeError:
            continue
    if content is None:
        return {'decoded': False, 'sha256': sha256(path)}
    # Whitelist technical statements and unit-bearing values; never emit names.
    facts = []
    for line_no, line in enumerate(content.splitlines(), 1):
        units = re.findall(r'(?<![\d.])\d+(?:\.\d+)?\s*(?:mm|毫米)', line, re.I)
        flags = {term: term in line for term in ('重采样', '插值', '原始', '层厚', '间距', '分辨率')}
        if units or any(flags.values()):
            facts.append({'line_1based': line_no, 'unit_values': units, 'technical_terms': [k for k,v in flags.items() if v], 'line_sha256': hashlib.sha256(line.encode('utf-8')).hexdigest()})
    return {'decoded': True, 'encoding': encoding, 'sha256': sha256(path), 'technical_facts': facts}

def main():
    started = datetime.now().astimezone().isoformat()
    t = time.perf_counter()
    all_paths = [p for p in SOURCE.rglob('*') if p.is_file()]
    files = [p for p in all_paths if eligible(p)]
    case_roots = {}
    for alias, name in CASE_NAMES.items():
        matches = [p for p in SOURCE.rglob('*') if p.is_dir() and eligible(p) and p.name == name]
        if len(matches) != 1:
            raise RuntimeError(f'{alias}: source directory count {len(matches)}')
        case_roots[alias] = matches[0]
    rows = []
    header_counts = Counter()
    for alias, root in case_roots.items():
        dirs = defaultdict(list)
        for path in files:
            if root in path.parents and path.suffix.lower() == '.dcm':
                dirs[path.parent].append(path)
                with path.open('rb') as stream:
                    header_counts['DICM' if stream.read(132)[128:132] == b'DICM' else 'no_DICM_preamble'] += 1
        series = [{'series': safe_series(root, d), 'files': len(ps), 'bytes': sum(p.stat().st_size for p in ps)} for d,ps in sorted(dirs.items())]
        rows.append({'case': alias, 'dicom_files': sum(s['files'] for s in series), 'series_count': len(series), 'series': series})
    ext = Counter(p.suffix.lower() or '<no extension>' for p in files)
    result_ext = {'.stl','.vtk','.vtp','.vtu','.obj','.ply','.png','.jpg','.jpeg','.bmp','.tif','.tiff','.gif','.mp4','.avi','.mov','.webm','.mkv','.mha','.mhd','.vti','.foam','.case','.ensight','.pdf'}
    found_results = Counter(p.suffix.lower() for p in files if p.suffix.lower() in result_ext)
    inventory = json.loads((DELIVERY / 'inventory.json').read_text(encoding='utf-8'))
    expected = {c['case']: {'dicom_files': c['dicom_files'], 'series': {s['series']: (s['dicom_files'],s['bytes']) for s in c['series']}} for c in inventory['cases']}
    count_match = all(r['dicom_files'] == expected[r['case']]['dicom_files'] and {s['series']: (s['files'],s['bytes']) for s in r['series']} == expected[r['case']]['series'] for r in rows)
    notes = [note_facts(p) for p in files if p.suffix.lower() == '.txt']
    noext_headers = Counter()
    for p in files:
        if not p.suffix:
            with p.open('rb') as stream:
                magic = stream.read(132)
            kind = 'DICM' if magic[128:132] == b'DICM' else 'other_not_classified'
            noext_headers[kind] += 1
    fingerprints = {name: sha256(DELIVERY/name) for name in ('inventory.json','previews.json','heterogeneous_frames.json','audit_reference.py')}
    preview = json.loads((DELIVERY / 'previews.json').read_text(encoding='utf-8'))['records']
    pixel_checks = []
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(ROOT/'work'/'lib'))
    from dicom_sitk import load_series_sitk
    representative = [('case_a','ISO_Bone_0.35mm_part2/ISO_Bone_0.35mm'),('case_b','1011-MPR 3.0mm'),('case_lateral','10003-3D_Sinus^_1')]
    for alias, series in representative:
        record = next(r for r in preview if r['case']==alias and r['series']==series)
        dirs = [p for p in case_roots[alias].rglob('*') if p.is_dir() and eligible(p) and safe_series(case_roots[alias],p)==series]
        if len(dirs)!=1:
            raise RuntimeError(f'{alias}/{series}: ambiguous source')
        volume, spacing, _, meta = load_series_sitk(str(dirs[0]), verbose=False)
        image = Image.open(DELIVERY/f'contact_{alias}.png').convert('RGB')
        low, high = record['display_window']['low'], record['display_window']['high']
        checks=[]
        for panel_idx, slice_idx in enumerate(record['slice_indices_0based']):
            frame = np.asarray(volume[slice_idx], dtype=np.float32)
            rendered = Image.fromarray(np.clip((frame-low)/(high-low)*255.,0.,255.).astype('uint8')).convert('RGB')
            rendered.thumbnail((460,460),Image.Resampling.LANCZOS)
            x=panel_idx*480+(480-rendered.width)//2
            y=52+(460-rendered.height)//2
            saved=np.asarray(image.crop((x,y,x+rendered.width,y+rendered.height)))
            checks.append({'slice_index_0based': slice_idx,'pixels_exact_match': bool(np.array_equal(saved,np.asarray(rendered)))})
        source_files=[p for p in dirs[0].iterdir() if p.is_file() and eligible(p) and p.suffix.lower()=='.dcm']
        fs_hash=hashlib.sha256('\n'.join(sorted(sha256(p) for p in source_files)).encode('ascii')).hexdigest()
        pixel_checks.append({'case':alias,'series':series,'shape_matches':list(volume.shape)==record['shape'],'spacing_matches':bool(np.allclose(spacing,record['spacing_xyz_mm'])),'fileset_sha256_matches':fs_hash==record['fileset_sha256'],'samples':checks})
        del volume
    hetero=json.loads((DELIVERY/'heterogeneous_frames.json').read_text(encoding='utf-8'))['records']
    single_checks=[]
    for record in hetero:
        series=record['series']
        dirs=[p for p in case_roots['case_medial'].rglob('*') if p.is_dir() and eligible(p) and safe_series(case_roots['case_medial'],p)==series]
        source_files=sorted(p for p in dirs[0].iterdir() if p.is_file() and eligible(p) and p.suffix.lower()=='.dcm')
        source_file=source_files[record['source_listing_index_0based']]
        staged=DELIVERY/'_local_staged'/'case_medial'/series/f"error_file_{record['error_file_index']}"/'frame.dcm'
        source_hash=sha256(source_file)
        staged_hash=sha256(staged)
        vol, _, _, _=load_series_sitk(str(staged.parent),verbose=False)
        low,high=record['display_window']['low'],record['display_window']['high']
        frame=np.asarray(vol[0],dtype=np.float32)
        expected_pixels=np.clip((frame-low)/(high-low)*255.,0.,255.).astype('uint8')
        saved=np.asarray(Image.open(DELIVERY/f"_local_{series}_error_file_{record['error_file_index']}_full.png").convert('L'))
        single_checks.append({'series':series,'error_file_index':record['error_file_index'],'source_listing_index_0based':record['source_listing_index_0based'],'source_sha256_matches':source_hash==record['source_file_sha256'],'staged_unchanged':source_hash==staged_hash,'shape_matches':list(vol.shape)==record['shape'],'pixel_values_range_matches': [float(vol.min()),float(vol.max())]==record['value_range'],'full_frame_pixels_exact_match':bool(np.array_equal(saved,expected_pixels))})
        del vol
    result={'schema':'T019_independent_source_check/v1','started_local':started,'elapsed_seconds':round(time.perf_counter()-t,3),'cases':rows,'case_count':len(rows),'series_count':sum(r['series_count'] for r in rows),'extensions':dict(sorted(ext.items())),'excluded_apple_files':len(all_paths)-len(files),'dicom_preamble_counts':dict(header_counts),'no_extension_header_counts':dict(noext_headers),'external_result_extension_hits':dict(found_results),'inventory_exact_case_series_count_byte_match':count_match,'inventory_extensions_match':dict(ext)==inventory['all_file_extensions'],'input_evidence_sha256':fingerprints,'source_notes_technical_facts':notes,'representative_raw_source_pixel_checks':pixel_checks,'heterogeneous_original_file_checks':single_checks,'boundaries':['No anatomical or clinical inference.','No segmentation, resampling, model, mesh or CFD execution.','DICOM pixel decoding exclusively via load_series_sitk.','External enumeration does not rule out DICOM embedded reconstructions or documents.','Only three complete homogeneous preview series independently decoded; remaining successful series visually inspected, not independently pixel-redecoded.']}
    (OUT/'source_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'case_count':result['case_count'],'series_count':result['series_count'],'dicom_files':ext['.dcm'],'case_counts':{r['case']:r['dicom_files'] for r in rows},'inventory_matches':count_match,'external_results':dict(found_results),'source_note_facts':notes,'pixel_checks':pixel_checks,'heterogeneous_checks':single_checks,'elapsed_seconds':result['elapsed_seconds']},ensure_ascii=False))

if __name__=='__main__':
    main()
