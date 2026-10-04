"""Isolated local CT imports and a persistent, serial CPU candidate pipeline.

Raw uploads stay private. Only generated review/preview artifacts are served.
The worker stops for real human review; it never authorizes or runs patient CFD.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
import copy

from boundary_review import EVIDENCE, OPENINGS, load_boundary_review, write_boundary_review

LIB = Path(__file__).resolve().parent
DEFAULT_ROOT = Path('C:/ts_work/project_cases')
MAX_BYTES = 8 * 1024**3
MAX_FILES = 30000
CASE_RE = re.compile(r'u_[0-9a-f]{16}')
STAGES = ('import', 'segmentation', 'candidates', 'review', 'geometry', 'mesh', 'solver', 'results')
LABELS = {
    'import': '检查并导入 CT', 'segmentation': '自动解剖分割',
    'candidates': '粗定位、精标定与复核图像', 'review': '人工切片复核',
    'geometry': '边界与几何确认', 'mesh': '体网格检查',
    'solver': '流场计算', 'results': '结果检验',
}


def now():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    return h.hexdigest()


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def execution_lock(root):
    """Keep one worker active even when the web service is restarted."""
    with (root / 'pipeline.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0');stream.flush()
        if os.name == 'nt':
            import msvcrt
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(.5)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def case_dir(root, case):
    if not isinstance(case, str) or not CASE_RE.fullmatch(case):
        raise ValueError('病例编号无效')
    return Path(root) / case


def update(directory, **fields):
    data = read_json(directory / 'case.json')
    data.update(fields, updated_at=now())
    write_json(directory / 'case.json', data)
    return data


def stage(directory, name, state, message):
    data = read_json(directory / 'case.json')
    data['stages'][name] = state
    return update(directory, stages=data['stages'], active_stage=name, message=message)


def unpack_archive(source, target):
    """Flatten archive members into generated filenames, with bounded extraction."""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if not members or len(members) > MAX_FILES or sum(m.file_size for m in members) > MAX_BYTES:
            raise ValueError('ZIP 内容为空或超过容量限制')
        for item in members:
            name = item.filename.replace('\\', '/')
            parts = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (parts.is_absolute() or '..' in parts.parts or ':' in name or '\x00' in name
                    or mode & 0o170000 == 0o120000 or item.flag_bits & 1
                    or item.file_size > 2 * 1024**3
                    or item.file_size > max(item.compress_size, 1) * 1000):
                raise ValueError('ZIP 包含不支持或不安全的文件项')
        for index, item in enumerate(members):
            suffix = '.nii.gz' if item.filename.lower().endswith('.nii.gz') else Path(item.filename).suffix.lower()
            if suffix not in ('.nii', '.nii.gz'):
                suffix = '.dcm'
            with archive.open(item) as src, (target / f'{index:06d}{suffix}').open('wb') as dst:
                shutil.copyfileobj(src, dst, length=1024**2)
    return sorted(target.iterdir())


def discover_dicom(paths):
    """Group actual CT series and validate physical slice geometry before decoding."""
    import numpy as np
    import pydicom
    groups = {}
    for path in paths:
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True)
        except Exception:
            continue
        if getattr(ds, 'Modality', '') != 'CT':
            continue
        uid = str(getattr(ds, 'SeriesInstanceUID', ''))
        if uid:
            groups.setdefault(uid, []).append((path, ds))
    records = []
    for index, (uid, slices) in enumerate(sorted(groups.items())):
        record = {'id': f's{index + 1}', 'slice_count': len(slices), 'valid': False,
                  'label': f'CT 序列 {index + 1}', 'files': [], 'reason': ''}
        try:
            if len(slices) < 3:
                raise ValueError('不足 3 张切片')
            ref = slices[0][1]
            orientation = np.asarray(ref.ImageOrientationPatient, dtype=float)
            spacing = np.asarray(ref.PixelSpacing, dtype=float)
            if (orientation.shape != (6,) or spacing.shape != (2,)
                    or not np.isfinite(orientation).all() or not np.isfinite(spacing).all()
                    or (spacing <= 0).any()):
                raise ValueError('切片方向或像素间距无效')
            row, col = orientation[:3], orientation[3:]
            if abs(np.dot(row, col)) > 1e-4 or not np.allclose([np.linalg.norm(row), np.linalg.norm(col)], 1, atol=1e-4):
                raise ValueError('切片方向不是正交单位向量')
            normal = np.cross(row, col)
            ordered, seen = [], {}
            for path, ds in slices:
                if int(getattr(ds, 'NumberOfFrames', 1)) != 1:
                    raise ValueError('暂不支持增强多帧 CT，请导出单帧序列')
                if 'LOCALIZER' in [str(v).upper() for v in getattr(ds, 'ImageType', [])]:
                    raise ValueError('定位像不能用于三维建模')
                if (str(getattr(ds, 'StudyInstanceUID', '')) != str(getattr(ref, 'StudyInstanceUID', ''))
                        or str(getattr(ds, 'FrameOfReferenceUID', '')) != str(getattr(ref, 'FrameOfReferenceUID', ''))
                        or (int(ds.Rows), int(ds.Columns)) != (int(ref.Rows), int(ref.Columns))
                        or not np.allclose(ds.ImageOrientationPatient, orientation, atol=1e-5)
                        or not np.allclose(ds.PixelSpacing, spacing, atol=1e-5)):
                    raise ValueError('同一序列含不一致的坐标系或图像网格')
                if str(getattr(ds, 'RescaleType', 'HU')).upper() not in ('HU', ''):
                    raise ValueError('CT 强度单位不是 HU')
                position = np.asarray(ds.ImagePositionPatient, dtype=float)
                if position.shape != (3,) or not np.isfinite(position).all():
                    raise ValueError('缺少有效切片位置')
                sop = str(ds.SOPInstanceUID)
                if sop in seen:
                    if sha256(path) != sha256(seen[sop]):
                        raise ValueError('重复实例的内容不一致')
                    continue
                seen[sop] = path
                ordered.append((float(position @ normal), position, path))
            ordered.sort(key=lambda entry: entry[0])
            distances = np.diff([entry[0] for entry in ordered])
            if len(ordered) < 3 or (distances <= 1e-4).any():
                raise ValueError('切片位置重复或数量不足')
            dz = float(np.median(distances))
            if not np.allclose(distances, dz, rtol=.05, atol=.05):
                raise ValueError('切片间距不均匀或存在缺片，请重新导出连续序列')
            start = ordered[0][1]
            if any(np.linalg.norm((pos - start) - normal * ((pos - start) @ normal)) > .1 for _, pos, _ in ordered):
                raise ValueError('存在机架倾斜或切片漂移，需要先进行专门的几何校正')
            record.update(valid=True, slice_count=len(ordered), spacing_xyz_mm=[float(spacing[1]), float(spacing[0]), dz],
                          size_xyz=[int(ref.Columns), int(ref.Rows), len(ordered)],
                          files=[str(path) for _, _, path in ordered], series_sha256=hashlib.sha256(uid.encode()).hexdigest())
        except Exception as exc:
            record['reason'] = str(exc) if isinstance(exc, ValueError) else '缺少必要的 DICOM 几何字段'
        records.append(record)
    return records


def validate_ct(image):
    import numpy as np
    import SimpleITK as sitk
    if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1 or min(image.GetSize()) < 3:
        raise ValueError('需要三维单通道 CT 体数据')
    direction = np.asarray(image.GetDirection()).reshape(3, 3)
    if (not np.isfinite([*image.GetSpacing(), *image.GetOrigin(), *image.GetDirection()]).all()
            or min(image.GetSpacing()) <= 0 or not np.allclose(direction.T @ direction, np.eye(3), atol=1e-4)):
        raise ValueError('CT 坐标或间距无效')
    values = sitk.GetArrayViewFromImage(image)
    if not np.isfinite(values).all() or float(values.min()) >= -300 or float(values.max()) <= 100:
        raise ValueError('强度范围不像保留 HU 的 CT，请检查导出方式')
    return {'size_xyz': list(image.GetSize()), 'spacing_xyz_mm': list(image.GetSpacing()),
            'origin_xyz_mm': list(image.GetOrigin()), 'direction': list(image.GetDirection()),
            'hu_range': [float(values.min()), float(values.max())]}


def import_ct(directory):
    import numpy as np
    import SimpleITK as sitk
    data = read_json(directory / 'case.json')
    raw = directory / 'raw'
    paths = [raw / entry['stored_name'] for entry in data['files']]
    if data['kind'] == 'zip':
        paths = unpack_archive(paths[0], directory / 'extracted')
    niftis = [p for p in paths if p.name.endswith(('.nii', '.nii.gz'))]
    if niftis:
        if len(niftis) != 1 or len(paths) != 1:
            raise ValueError('请单独上传一份 NIfTI，或上传纯 DICOM 序列')
        if not data.get('hu_confirmed'):
            raise ValueError('导入 NIfTI 前请确认强度单位保留为 HU')
        image = sitk.ReadImage(str(niftis[0]))
    else:
        series = discover_dicom(paths)
        write_json(directory / 'series.json', series)
        public_series = [{k: v for k, v in record.items() if k != 'files'} for record in series]
        valid = [s for s in series if s['valid']]
        if not valid:
            update(directory, series=public_series)
            reasons = '；'.join(s['label'] + '：' + s['reason'] for s in series[:5])
            raise ValueError('未找到可用于建模的连续 CT 序列' + ('。' + reasons if reasons else '，请检查文件类型'))
        selected = data.get('selected_series')
        if selected is None and len(valid) > 1:
            stage(directory, 'import', 'waiting', '检测到多套 CT，请选择一套序列继续')
            update(directory, status='awaiting_series', series=public_series)
            return False
        chosen = next((s for s in valid if s['id'] == selected), None) if selected else valid[0]
        if chosen is None:
            raise ValueError('所选序列不存在或检查未通过')
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(chosen['files'])
        image = reader.Execute()
        update(directory, series=public_series, selected_series=chosen['id'])
        if list(image.GetSize()) != chosen['size_xyz']:
            raise ValueError('解码后的 CT 尺寸与切片序列不一致')
    geometry = validate_ct(image)
    target = directory / 'ct.nii.gz'
    sitk.WriteImage(image, str(target))
    # Verify the actual saved image rather than trusting the conversion call.
    recovered = validate_ct(sitk.ReadImage(str(target)))
    if recovered['size_xyz'] != geometry['size_xyz'] or any(
            not np.allclose(recovered[key], geometry[key], rtol=1e-6, atol=1e-5)
            for key in ('spacing_xyz_mm', 'origin_xyz_mm', 'direction', 'hu_range')):
        raise ValueError('CT 转换后的几何或强度发生变化')
    update(directory, geometry=geometry, ct_sha256=sha256(target))
    stage(directory, 'import', 'done', 'CT 已导入，等待自动分割')
    return True


def run_command(directory, name, command, timeout=7200, extra_env=None):
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', HF_HUB_DISABLE_TELEMETRY='1')
    if extra_env:
        env.update({str(key): str(value) for key, value in extra_env.items()})
    logs = directory / 'logs'
    logs.mkdir(exist_ok=True)
    with (logs / (name + '.log')).open('w', encoding='utf-8') as stream:
        result = subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{name} exited {result.returncode}')


def run_segmentation(directory, executable):
    """Run TotalSegmentator with a case-local temp area and one safe retry.

    On Windows nnUNet can finish writing masks while a scanner still holds one
    temporary NIfTI during tempfile cleanup. Retrying from a clean mask folder
    avoids treating that transient cleanup failure as a permanent case failure.
    """
    mask_dir = directory / 'masks'
    temp_root = directory / 'tmp'
    temp_root.mkdir(exist_ok=True)
    command = [sys.executable, LIB / 'ct_seg_worker.py', '--input', directory / 'ct.nii.gz',
               '--output', mask_dir, '--task', 'head_glands_cavities', '--device', 'cpu',
               '--temp', temp_root / 'nnunet']
    errors = []
    for attempt in (1, 2):
        if mask_dir.exists():
            shutil.rmtree(mask_dir, ignore_errors=True)
        mask_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = temp_root / f'segmentation_{attempt}'
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            run_command(directory, f'segmentation_attempt_{attempt}', command,
                        timeout=7200, extra_env={'TMP': temp_dir, 'TEMP': temp_dir, 'TMPDIR': temp_dir})
            return
        except Exception as exc:
            errors.append(str(exc))
            if attempt == 1:
                time.sleep(2)
    raise RuntimeError('；'.join(errors))


def build_case_artifacts(directory):
    """Real QC, landmarks and preview; useful separately for fixture verification."""
    from run_auto_anatomy import input_identity
    from build_auto_landmark_review import build_review
    from export_candidate_preview import export_case
    from coarse_localization_summary import summarize_localization
    case = directory.name
    public = directory / 'public'
    qc = directory / 'qc'
    proposals = public / 'review'
    run_command(directory, 'quality', [sys.executable, LIB / 'ts_quality_gate.py', case, '--data-dir', directory, '--out-dir', qc])
    if read_json(qc / f'gate_{case}.json')['data_integrity_status'] != 'pass':
        raise ValueError('分割与 CT 数据一致性检查未通过')
    run_command(directory, 'landmarks', [sys.executable, LIB / 'auto_anatomy_landmarks.py', case,
                                       '--data-base', directory.parent, '--out-base', proposals])
    report_path = proposals / case / 'landmarks.json'
    report = read_json(report_path)
    report['input_provenance'] = input_identity(directory)
    report['notes'] = [note for note in report.get('notes', []) if 'Four patients' not in note]
    write_json(report_path, report)
    build_review(proposals, cases=[case])
    html_path = proposals / 'index.html'
    html_path.write_text(html_path.read_text(encoding='utf-8').replace('</head>',
                        '<script src="/workspace/embed.js" defer></script></head>'), encoding='utf-8')
    run_command(directory, 'anatomy', [sys.executable, LIB / 'anatomy_barrier_seg.py', case, '--data-dir', directory,
                                     '--out-dir', directory / 'anatomy'])
    export_case(case, directory.parent, public / 'preview')
    prefix = f'/case-assets/{case}'
    viewer = {'schema': 'nasal_workspace/v1', 'patient_scan_count': 1, 'patient_cfd_results': 0,
              'cases': [{'id': case, 'label': '上传 CT · ' + case[-6:], 'type': 'patient_preview',
                         'mesh_url': f'{prefix}/preview/{case}/viewer_mesh.json',
                         'note': '本例自动候选，等待切片及边界检查。',
                         'localization_summary': summarize_localization(report),
                         'coarse_localization': report.get('coarse_localization'),
                         'coarse_adjustment': report.get('coarse_adjustment'),
                         'landmarks': [{'id': key, **lm} for key, lm in report['landmarks'].items() if lm.get('point_lps_mm')],
                         'qc': read_json(qc / f'gate_{case}.json'),
                         'result': {'schema': 'nasal_cfd_result/v1', 'type': 'patient_preview',
                                    'geometry': {'kind': 'patient', 'case_id': case, 'review_status': 'pending'},
                                    'clinical_validation': 'not_validated', 'provenance': {'method': 'segmentation_surface_preview'},
                                    'fields': {'velocity': None, 'pressure': None, 'turbulence_intensity': None}}}]}
    write_json(public / 'viewer.json', viewer)
    hashes = {str(p.relative_to(public)).replace('\\', '/'): sha256(p) for p in public.rglob('*') if p.is_file()}
    write_json(directory / 'receipt.json', {'schema': 'ct_case_receipt/v1', 'case': case,
                                         'identity': report['input_provenance'], 'output_sha256': hashes,
                                         'pipeline_code_sha256': {name: sha256(LIB / name) for name in
                                         ('ct_case_pipeline.py', 'build_auto_landmark_review.py',
                                          'coarse_localization_summary.py',
                                          'anatomy_barrier_seg.py', 'export_candidate_preview.py')}})
    update(directory, localization_summary=summarize_localization(report),
           landmark_count=len(viewer['cases'][0]['landmarks']), artifacts={'viewer': '/viewer/index.html?manifest=' + prefix + '/viewer.json',
                                 'review': prefix + '/review/index.html'})


def current_artifacts(directory, data):
    """Resolve an internally published version; legacy cases retain their paths."""
    revision = data.get('current_revision')
    if revision:
        if not re.fullmatch(r'v_[0-9a-f]{16}', revision):
            raise ValueError('候选版本编号无效')
        return directory / 'public' / 'versions' / revision, directory / 'runs' / revision
    return directory / 'public', directory


def verify_case_artifacts(directory, data):
    public, private = current_artifacts(directory, data)
    receipt = read_json(private / 'receipt.json')
    for relative, expected in receipt['output_sha256'].items():
        target = public / str(relative).replace('\\', '/')
        if not target.is_file() or sha256(target) != expected:
            raise ValueError('复核材料已变化，请重新生成候选后审核')
    for relative, expected in receipt['identity']['input_sha256'].items():
        target = directory / str(relative).replace('\\', '/')
        if not target.is_file() or sha256(target) != expected:
            raise ValueError('CT 或分割已变化，请重新执行自动处理')
    return public, private, receipt


def _boundary_identity(directory, data):
    """Resolve the current point-review identity from on-disk inputs."""
    public, private, receipt = verify_case_artifacts(directory, data)
    review_path = private / 'review_config_confirmed.json'
    confirmed = read_json(review_path)
    if (confirmed.get('case') != directory.name or confirmed.get('pending')
            or confirmed.get('undecided') or confirmed.get('rejected')
            or not set(OPENINGS).issubset(confirmed.get('confirmed_boundaries', []))):
        raise ValueError('三处边界点位尚未完成审核')
    # Receipts created on Windows may contain backslash relative paths.  The
    # binding format is platform-neutral so old and new receipts resolve to
    # the same label identity.
    inputs = {str(key).replace('\\', '/'): value
              for key, value in receipt['identity']['input_sha256'].items()}
    labels = {key: value for key, value in inputs.items() if key.startswith('masks/')}
    if 'ct.nii.gz' not in inputs or not labels:
        raise ValueError('边界审核需要完整 CT 和标签来源')
    from confirm_landmark_review import load_proposal_bundle
    bundle = load_proposal_bundle(public / 'review' / 'index.html')
    proposals = [item for item in bundle.get('cases', []) if item.get('case') == directory.name]
    if (confirmed.get('schema') != 'anatomy_barrier_review/v2'
            or confirmed.get('coordinate_system') != 'LPS' or confirmed.get('unit') != 'mm'
            or len(proposals) != 1 or confirmed.get('source_sha256') != proposals[0].get('source_sha256')
            or any(confirmed.get('planes_lps', {}).get(key, {}).get('status') != 'confirmed' for key in OPENINGS)):
        raise ValueError('点位确认件与当前候选来源不一致')
    identity = {
        'case': directory.name, 'patient_id': receipt['identity'].get('coarse_reference', {}).get('patient_id') or directory.name,
        'revision': data.get('current_revision', 'original'), 'ct_sha256': inputs['ct.nii.gz'],
        'label_sha256': labels, 'candidate_sha256': bundle.get('proposal_bundle_sha256'),
        'landmark_review_sha256': sha256(review_path),
    }
    return identity, public, private, confirmed


def boundary_context(directory, data, draft_id):
    """Resolve current inputs and a generated draft; submitted hashes are never trusted."""
    if not isinstance(draft_id, str) or not re.fullmatch(r'd_[0-9a-f]{16}', draft_id):
        raise ValueError('边界草稿编号无效')
    identity, public, private, _ = _boundary_identity(directory, data)
    draft_root = private / 'draft_previews' / draft_id
    manifest_path = draft_root / 'manifest.json'
    manifest = read_json(manifest_path)
    if (manifest.get('schema') != 'boundary_draft_preview/v1' or manifest.get('status') != 'generated'
            or manifest.get('binding') != identity):
        raise ValueError('边界预览不属于当前病例、输入及点位审核版本')
    outputs = manifest.get('outputs')
    if not isinstance(outputs, dict) or not set(EVIDENCE + ('sinus_exclusion_mask',)).issubset(outputs):
        raise ValueError('缺少边界 CT 叠加或鼻窦排除掩膜证据')
    for item in outputs.values():
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('边界预览产物记录无效')
        target = (draft_root / item['path']).resolve()
        if (not target.is_relative_to(draft_root.resolve()) or not target.is_file()
                or sha256(target) != item.get('sha256')):
            raise ValueError('边界预览产物已缺失或变化')
    source_hashes = manifest.get('source_sha256')
    source_paths = {
        'ct': directory / 'ct.nii.gz',
        'airway': private / 'boundary_inputs' / 'airway_T300_provisional.nii.gz',
        'sinus_exclusion': private / 'boundary_inputs' / 'sinus_exclusion_mask.nii.gz',
    }
    if not isinstance(source_hashes, dict) or any(
            not source_paths[key].is_file() or source_hashes.get(key) != sha256(source_paths[key])
            for key in source_paths):
        raise ValueError('边界预览源文件已变化，请重新生成草稿')
    return identity | {
        'draft_preview_sha256': sha256(manifest_path), 'parameters_sha256': manifest.get('parameters_sha256'),
        'evidence_sha256': {key: outputs[key]['sha256'] for key in EVIDENCE},
        'sinus_mask_sha256': outputs['sinus_exclusion_mask']['sha256'],
    }


def invalidate_boundary_review(data):
    previous = data.get('boundary_review')
    return (previous | {'status': 'stale'}) if previous else {'status': 'pending'}


def invalidate_boundary_preview(data):
    previous = data.get('boundary_preview')
    return (previous | {'status': 'stale'}) if previous else {'status': 'pending'}


def boundary_controls_from_confirmed(confirmed, supplied=None):
    """Build preview controls while keeping point and normal bound to review."""
    planes = confirmed.get('planes_lps', {})
    if (not isinstance(planes, dict) or any(key not in planes or not isinstance(planes[key], dict)
                                            for key in OPENINGS)):
        raise ValueError('点位确认件缺少三处可用边界平面')
    controls = {
        'openings': {key: copy.deepcopy(planes[key]) for key in OPENINGS},
        'oral_exclusion': {
            'confirmed': True, 'mode': 'same_as_nasopharynx_outlet',
            'boundary_ref': 'nasopharynx_outlet',
        },
        'sinus_policy': {
            'confirmed': True, 'policy': 'exclude_sinuses',
            'regions': ['maxillary', 'frontal', 'ethmoid', 'sphenoid'],
        },
    }
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError('边界预览控制必须是 JSON 对象')
        controls = copy.deepcopy(supplied)
        for key in OPENINGS:
            expected = planes[key]
            actual = controls.get('openings', {}).get(key, {})
            for field in ('point_lps_mm', 'normal_lps'):
                if actual.get(field) != expected.get(field):
                    raise ValueError('边界预览不能修改已确认点位或法向，请重新进行点位审核')
    from boundary_review import validate_cutting_planes
    validate_cutting_planes(controls.get('openings'), controls.get('oral_exclusion'))
    sinus = controls.get('sinus_policy', {})
    if sinus.get('confirmed') is not True or sinus.get('policy') != 'exclude_sinuses':
        raise ValueError('生成可审核草稿前必须明确确认鼻窦排除策略')
    if set(sinus.get('regions', [])) != {'maxillary', 'frontal', 'ethmoid', 'sphenoid'}:
        raise ValueError('鼻窦排除策略必须覆盖四类鼻窦区域')
    oral = controls.get('oral_exclusion', {})
    if oral.get('confirmed') is not True:
        raise ValueError('生成可审核草稿前必须明确确认口腔排除策略')
    return controls


def regenerate_artifacts(directory):
    """Publish a new landmark version atomically; preserve old outputs and reviews."""
    from run_auto_anatomy import input_identity
    from build_auto_landmark_review import build_review
    from coarse_localization_summary import summarize_localization
    previous = read_json(directory / 'case.json')
    previous_status = (previous['status'] if previous['status'] not in ('queued', 'running')
                       else previous.get('regenerate_previous_status', 'awaiting_review'))
    revision = 'v_' + uuid.uuid4().hex[:16]
    private = directory / 'runs' / revision
    public = directory / 'public' / 'versions' / revision
    try:
        source, _, receipt = verify_case_artifacts(directory, previous)
        private.mkdir(parents=True)
        reference = private / 'reference_library.json'
        shutil.copy2(LIB.parent / '06_auto_landmarks/reference_library.json', reference)
        before = input_identity(directory, reference_library=reference)
        stage(directory, 'candidates', 'running', '正在按当前粗标定方案生成新版候选')
        update(directory, status='running', error=None)
        proposals = public / 'review'
        run_command(directory, f'landmarks_{revision}', [sys.executable, LIB / 'auto_anatomy_landmarks.py',
                    directory.name, '--data-base', directory.parent, '--out-base', proposals,
                    '--reference-library', reference])
        report_path = proposals / directory.name / 'landmarks.json'
        report = read_json(report_path)
        after = input_identity(directory, reference_library=reference)
        if before != after:
            raise ValueError('生成期间 CT、分割或算法发生变化，请重新生成')
        report['input_provenance'] = after
        report['notes'] = [note for note in report.get('notes', []) if 'Four patients' not in note]
        write_json(report_path, report)
        build_review(proposals, cases=[directory.name])
        html = proposals / 'index.html'
        if '/workspace/embed.js' not in html.read_text(encoding='utf-8'):
            html.write_text(html.read_text(encoding='utf-8').replace('</head>',
                           '<script src="/workspace/embed.js" defer></script></head>'), encoding='utf-8')
        # The CT and segmentation are identical, so the verified surface can be
        # reused. New point overlays come solely from the new proposal report.
        shutil.copytree(source / 'preview', public / 'preview')
        viewer = read_json(source / 'viewer.json')
        prefix = f'/case-assets/{directory.name}/versions/{revision}'
        viewer['cases'][0]['mesh_url'] = prefix + f'/preview/{directory.name}/viewer_mesh.json'
        viewer['cases'][0]['localization_summary'] = summarize_localization(report)
        viewer['cases'][0]['coarse_localization'] = report.get('coarse_localization')
        viewer['cases'][0]['coarse_adjustment'] = report.get('coarse_adjustment')
        viewer['cases'][0]['landmarks'] = [{'id': key, **lm} for key, lm in report['landmarks'].items() if lm.get('point_lps_mm')]
        write_json(public / 'viewer.json', viewer)
        verify_case_artifacts(directory, previous)
        hashes = {str(p.relative_to(public)).replace('\\', '/'): sha256(p) for p in public.rglob('*') if p.is_file()}
        write_json(private / 'receipt.json', {'schema':'ct_case_receipt/v1', 'case':directory.name,
                   'revision':revision, 'identity':after, 'output_sha256':hashes,
                   'reused_surface_from_revision':previous.get('current_revision', 'original'),
                   'pipeline_code_sha256':{name:sha256(LIB/name) for name in
                   ('ct_case_pipeline.py', 'build_auto_landmark_review.py')}})
        versions = list(previous.get('versions', []))
        versions.append({'id':revision, 'created_at':now(), 'previous_revision':previous.get('current_revision', 'original'),
                         'proposal_hash':report['proposal_hash'], 'reference_library_sha256':sha256(reference)})
        update(directory, current_revision=revision, versions=versions, status='awaiting_review', error=None,
               boundary_review=invalidate_boundary_review(previous),
               localization_summary=summarize_localization(report),
               active_stage='review', message='新版粗标定已生成，等待切片复核',
               artifacts={'viewer':'/viewer/index.html?manifest=' + prefix + '/viewer.json', 'review':prefix+'/review/index.html'},
               landmark_count=len(viewer['cases'][0]['landmarks']),
               stages={'import':'done','segmentation':'done','candidates':'done','review':'waiting',
                       'geometry':'pending','mesh':'pending','solver':'pending','results':'pending'})
        return 0
    except Exception:
        import traceback
        logs = directory / 'logs'; logs.mkdir(exist_ok=True)
        (logs / 'regenerate_failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        update(directory, status=previous_status,
               active_stage='review', stages=previous['stages'] | {'candidates':'done'},
               message='新版未生成，仍保留上一版候选', error='生成新版失败，请查看本机日志后重试')
        return 1


def worker(directory, regenerate=False):
    update(directory, worker_pid=os.getpid())
    with execution_lock(directory.parent):
        return regenerate_artifacts(directory) if regenerate else _worker(directory)


def _worker(directory):
    try:
        update(directory, status='running', error=None, artifacts={})
        stage(directory, 'import', 'running', '正在检查 CT 文件与物理坐标')
        if not import_ct(directory):
            return 0
        stage(directory, 'segmentation', 'running', '正在进行 CPU 自动分割，可离开页面后再回来查看')
        executable = Path(sys.executable).parent / 'TotalSegmentator.exe'
        if not executable.is_file():
            raise RuntimeError('TotalSegmentator executable missing')
        run_segmentation(directory, executable)
        stage(directory, 'segmentation', 'done', '自动分割已完成')
        stage(directory, 'candidates', 'running', '正在检查分割，进行 UAS 粗定位与本例 CT 精标定，生成复核材料')
        build_case_artifacts(directory)
        stage(directory, 'candidates', 'done', '三维候选与切片复核材料已生成')
        stage(directory, 'review', 'waiting', '请检验候选位置并记录审核决定')
        update(directory, status='awaiting_review')
        return 0
    except Exception:
        import traceback
        logs = directory / 'logs'
        logs.mkdir(exist_ok=True)
        (logs / 'failure.log').write_text(traceback.format_exc(), encoding='utf-8')
        data = read_json(directory / 'case.json')
        active = data['active_stage']
        stage(directory, active, 'failed', LABELS[active] + '未完成')
        # Data errors generated by the importer are safe to show without raw names.
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, ValueError) else LABELS[active] + '失败，请查看本机病例日志后重试'
        update(directory, status='failed', error=message)
        return 1


class CaseManager:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ct-pipeline')
        self.pending = set()
        for path in self.root.glob('u_*/case.json'):
            data = read_json(path)
            if data.get('status') in ('queued', 'running') and not process_alive(data.get('worker_pid')):
                update(path.parent, status='interrupted', message='上次服务已中断，可重新处理', error=None)

    def get(self, case):
        directory = case_dir(self.root, case)
        if not (directory / 'case.json').is_file():
            raise FileNotFoundError('未找到病例')
        return read_json(directory / 'case.json')

    def public(self, data):
        return {key: value for key, value in data.items() if key != 'files'} | {
            'file_count': len(data['files']), 'uploaded_files': sum('sha256' in f for f in data['files']),
            'uploaded_bytes': sum(f['size'] for f in data['files'] if 'sha256' in f),
        }

    def list(self):
        return sorted([self.public(read_json(p)) for p in self.root.glob('u_*/case.json')], key=lambda d: d['created_at'], reverse=True)

    def create(self, payload):
        entries = payload.get('files')
        kind = payload.get('kind')
        if kind not in ('dicom', 'zip', 'nifti') or not isinstance(entries, list) or not 1 <= len(entries) <= MAX_FILES:
            raise ValueError('请选择 DICOM 文件夹、ZIP 或单份 NIfTI')
        if kind in ('zip', 'nifti') and len(entries) != 1:
            raise ValueError('ZIP 或 NIfTI 每次只上传一份')
        files = []
        for i, entry in enumerate(entries):
            size = entry.get('size')
            if type(size) is not int or not 0 < size <= 2 * 1024**3:
                raise ValueError('文件为空或单文件超过 2 GB')
            suffix = '.zip' if kind == 'zip' else '.dcm'
            if kind == 'nifti':
                suffix = '.nii.gz' if str(entry.get('name', '')).lower().endswith('.nii.gz') else '.nii'
            files.append({'id': i, 'stored_name': f'{i:06d}{suffix}', 'size': size})
        total = sum(f['size'] for f in files)
        if total > MAX_BYTES:
            raise ValueError('每次导入最多 8 GB')
        case = 'u_' + uuid.uuid4().hex[:16]
        directory = case_dir(self.root, case)
        (directory / 'raw').mkdir(parents=True)
        data = {'schema': 'ct_case_pipeline/v1', 'id': case, 'created_at': now(), 'updated_at': now(),
                'kind': kind, 'hu_confirmed': payload.get('hu_confirmed') is True,
                'files': files, 'total_bytes': total, 'status': 'uploading', 'active_stage': 'import',
                'stages': {name: 'pending' for name in STAGES}, 'message': '等待上传 CT',
                'artifacts': {}, 'series': [], 'error': None, 'patient_cfd_results': 0}
        write_json(directory / 'case.json', data)
        return self.public(data)

    def upload(self, case, index, stream, length):
        with self.lock:
            data = self.get(case)
            if data['status'] != 'uploading' or not 0 <= index < len(data['files']):
                raise ValueError('病例不在上传阶段或文件编号无效')
            entry = data['files'][index]
            if length != entry['size']:
                raise ValueError('文件长度与所选文件不符')
            target = case_dir(self.root, case) / 'raw' / entry['stored_name']
            temp = target.with_suffix(target.suffix + '.part')
            h = hashlib.sha256()
            try:
                with temp.open('wb') as dst:
                    remaining = length
                    while remaining:
                        block = stream.read(min(remaining, 1024**2))
                        if not block:
                            raise ValueError('上传中断，请重新上传此文件')
                        dst.write(block)
                        h.update(block)
                        remaining -= len(block)
                os.replace(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            entry['sha256'] = h.hexdigest()
            return self.public(update(target.parents[1], files=data['files'], message='正在上传 CT'))

    def start(self, case, selected=None):
        with self.lock:
            data = self.get(case)
            if data['status'] not in ('uploading', 'awaiting_series', 'failed', 'interrupted') or case in self.pending:
                raise ValueError('当前病例不能重复启动')
            if process_alive(data.get('worker_pid')):
                raise ValueError('本例处理进程仍在运行，请等待结束')
            if not all('sha256' in f for f in data['files']):
                raise ValueError('CT 文件尚未全部上传')
            if selected is not None:
                valid = [s['id'] for s in data['series'] if s['valid']]
                if selected not in valid:
                    raise ValueError('请选择检查通过的 CT 序列')
            elif data['status'] == 'awaiting_series':
                raise ValueError('需要先选择 CT 序列')
            directory = case_dir(self.root, case)
            data = update(directory, status='queued', selected_series=selected or data.get('selected_series'),
                          boundary_review=invalidate_boundary_review(data),
                          boundary_preview=invalidate_boundary_preview(data),
                          message='已进入处理队列', error=None, artifacts={}, stages={s: 'pending' for s in STAGES})
            self.pending.add(case)
            self.pool.submit(self._run, case)
            return self.public(data)

    def regenerate(self, case):
        with self.lock:
            data = self.get(case)
            if data['status'] not in ('awaiting_review', 'review_recorded') or case in self.pending:
                raise ValueError('请等待本例候选生成完成再重新生成')
            if process_alive(data.get('worker_pid')):
                raise ValueError('本例处理进程仍在运行')
            directory = case_dir(self.root, case)
            verify_case_artifacts(directory, data)
            data = update(directory, status='queued', regenerate_previous_status=data['status'],
                          message='新版粗标定已进入生成队列', error=None,
                          boundary_review=invalidate_boundary_review(data),
                          boundary_preview=invalidate_boundary_preview(data))
            self.pending.add(case)
            self.pool.submit(self._run, case, True)
            return self.public(data)

    def _run(self, case, regenerate=False):
        directory = case_dir(self.root, case)
        try:
            command = [sys.executable, LIB / 'ct_case_pipeline.py', '--worker', directory]
            if regenerate: command.append('--regenerate')
            run_command(directory, 'worker', command, timeout=18000)
        except Exception:
            data = self.get(case)
            if data['status'] in ('queued', 'running'):
                update(directory, status='failed', error='处理进程中断，可重试', message='自动处理未完成')
        finally:
            with self.lock:
                self.pending.discard(case)

    def save_review(self, case, decisions):
        from confirm_landmark_review import load_proposal_bundle, validate, build_confirmed
        with self.lock:
            data = self.get(case)
            if data['status'] not in ('awaiting_review', 'review_recorded'):
                raise ValueError('本例尚未生成可复核候选')
            directory = case_dir(self.root, case)
            public, private, _ = verify_case_artifacts(directory, data)
            bundle = load_proposal_bundle(public / 'review/index.html')
            if decisions.get('proposal_bundle_sha256') != bundle['proposal_bundle_sha256']:
                raise ValueError('审核不属于当前候选版本')
            records, problems, reviewer = validate(decisions, bundle)
            if problems or len(records) != 1 or records[0]['case'] != case:
                raise ValueError('审核记录与当前病例不一致')
            if not reviewer or not str(reviewer).strip():
                raise ValueError('请先填写复核人')
            write_json(private / 'review_decisions.json', decisions)
            confirmed = build_confirmed(records, reviewer, None, None, False, False, decisions.get('exported_at') or now())
            write_json(private / 'review_config_confirmed.json', confirmed[case])
            complete = (not confirmed[case]['undecided'] and not confirmed[case]['pending']
                        and not confirmed[case]['rejected'])
            stage(directory, 'review', 'done' if complete else 'waiting', '审核决定已保存到本例')
            stage(directory, 'geometry', 'waiting' if complete else 'pending', '还需检验口腔排除、鼻窦范围及入口出口边界')
            return self.public(update(directory, status='review_recorded' if complete else 'awaiting_review',
                                      boundary_review=invalidate_boundary_review(data),
                                      boundary_preview=invalidate_boundary_preview(data),
                                      message='审核已保存；几何检查完成后才能进入网格与计算'))

    def upload_boundary_mask(self, case, stream, length):
        """Store an explicit sinus exclusion mask under the current revision."""
        with self.lock:
            data = self.get(case)
            if data['status'] != 'review_recorded' or case in self.pending:
                raise ValueError('请先完成本例三处点位审核')
            if type(length) is not int or not 0 < length <= 2 * 1024**3:
                raise ValueError('鼻窦掩膜文件大小无效')
            directory = case_dir(self.root, case)
            _, private, _ = verify_case_artifacts(directory, data)
            target = private / 'boundary_inputs' / 'sinus_exclusion_mask.nii.gz'
            temporary = target.with_name(target.name + '.' + uuid.uuid4().hex + '.part')
            digest = hashlib.sha256()
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with temporary.open('wb') as output:
                    remaining = length
                    while remaining:
                        block = stream.read(min(remaining, 1024**2))
                        if not block:
                            raise ValueError('鼻窦掩膜上传中断，请重试')
                        output.write(block)
                        digest.update(block)
                        remaining -= len(block)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            relative = target.relative_to(directory).as_posix()
            state = update(directory, boundary_inputs={
                'sinus_exclusion_mask': {'path': relative, 'sha256': digest.hexdigest()}
            }, message='鼻窦排除掩膜已上传，等待生成边界草稿')
            return self.public(state)

    def generate_boundary_preview(self, case, payload=None):
        """Generate one immutable, runner-bound review draft."""
        from boundary_preview import generate_preview
        with self.lock:
            data = self.get(case)
            if data['status'] != 'review_recorded' or case in self.pending:
                raise ValueError('请先完成本例三处点位审核')
            directory = case_dir(self.root, case)
            identity, _, private, confirmed = _boundary_identity(directory, data)
            mask_path = private / 'boundary_inputs' / 'sinus_exclusion_mask.nii.gz'
            if not mask_path.is_file():
                raise FileNotFoundError('尚未上传显式鼻窦排除掩膜')
            payload = payload if isinstance(payload, dict) else {}
            if payload.get('oral_exclusion_confirmed') is not True:
                raise ValueError('请明确确认口腔排除策略')
            if payload.get('sinus_policy_confirmed') is not True:
                raise ValueError('请明确确认鼻窦排除策略')
            controls = boundary_controls_from_confirmed(
                confirmed, payload.get('controls'))
            source_airway = directory / 'anatomy' / 'main_nasal_airway_T300_provisional.nii.gz'
            if not source_airway.is_file():
                raise FileNotFoundError('缺少当前病例的候选气道掩膜')
            airway = private / 'boundary_inputs' / 'airway_T300_provisional.nii.gz'
            airway.parent.mkdir(parents=True, exist_ok=True)
            if not airway.is_file():
                temporary = airway.with_name(airway.name + '.' + uuid.uuid4().hex + '.part')
                try:
                    shutil.copyfile(source_airway, temporary)
                    os.replace(temporary, airway)
                finally:
                    temporary.unlink(missing_ok=True)
            draft_id = 'd_' + uuid.uuid4().hex[:16]
            output = private / 'draft_previews' / draft_id
            manifest = generate_preview(
                directory / 'ct.nii.gz', airway, controls, output,
                sinus_path=mask_path, binding=identity,
                pixels=payload.get('pixels', 513), field_mm=payload.get('field_mm', 80.0))
            manifest_path = output / 'manifest.json'
            reference = {
                'status': 'generated', 'revision': identity['revision'], 'draft_id': draft_id,
                'manifest_path': manifest_path.relative_to(directory).as_posix(),
                'sha256': sha256(manifest_path),
            }
            state = update(directory, boundary_preview=reference,
                           boundary_review=invalidate_boundary_review(data),
                           stages=data['stages'] | {'geometry': 'waiting', 'mesh': 'pending',
                                                    'solver': 'pending', 'results': 'pending'},
                           message='边界草稿已生成，等待 CT 叠加与边界策略审核', patient_cfd_results=0)
            return self.public(state) | {'boundary_preview_manifest': manifest}

    def load_boundary_preview_manifest(self, case, draft_id):
        with self.lock:
            data = self.get(case)
            directory = case_dir(self.root, case)
            boundary_context(directory, data, draft_id)
            _, private = current_artifacts(directory, data)
            path = private / 'draft_previews' / draft_id / 'manifest.json'
            manifest = read_json(path)
            return manifest | {'draft_id': draft_id}

    def boundary_preview_asset(self, case, draft_id, name):
        """Serve only a hash-checked generated preview output."""
        with self.lock:
            data = self.get(case)
            directory = case_dir(self.root, case)
            boundary_context(directory, data, draft_id)
            if name == 'manifest.json':
                relative = 'manifest.json'
            else:
                _, private = current_artifacts(directory, data)
                manifest = read_json(private / 'draft_previews' / draft_id / 'manifest.json')
                output = manifest.get('outputs', {}).get(name)
                if not isinstance(output, dict):
                    output = next((item for item in manifest.get('outputs', {}).values()
                                   if isinstance(item, dict) and item.get('path') == name), None)
                if not isinstance(output, dict):
                    raise FileNotFoundError('未找到边界预览产物')
                relative = output.get('path')
            target = (private / 'draft_previews' / draft_id / relative).resolve()
            root = (private / 'draft_previews' / draft_id).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise FileNotFoundError('未找到边界预览产物')
            return target

    def save_boundary_review(self, case, draft_id, record):
        with self.lock:
            data = self.get(case)
            if data['status'] != 'review_recorded' or case in self.pending:
                raise ValueError('请先完成本例点位审核')
            directory = case_dir(self.root, case)
            expected = boundary_context(directory, data, draft_id)
            _, private = current_artifacts(directory, data)
            target = private / 'boundary_reviews' / ('b_' + uuid.uuid4().hex[:16]) / 'boundary_review.json'
            write_boundary_review(target, record, expected)
            # Recheck after writing before publishing a pointer to this audit record.
            current = self.get(case)
            if (current['status'] != 'review_recorded' or case in self.pending
                    or boundary_context(directory, current, draft_id) != expected):
                raise ValueError('保存期间输入或边界草稿发生变化')
            reference = {'status': 'recorded', 'revision': expected['revision'], 'draft_id': draft_id,
                         'record_path': target.relative_to(directory).as_posix(), 'sha256': sha256(target)}
            return self.public(update(directory, boundary_review=reference,
                                      stages=current['stages'] | {'geometry': 'waiting', 'mesh': 'pending',
                                                               'solver': 'pending', 'results': 'pending'},
                                      message='边界判断已记录，等待生成及审核最终表面', patient_cfd_results=0))

    def load_boundary_review(self, case):
        with self.lock:
            data = self.get(case)
            reference = data.get('boundary_review', {})
            if reference.get('status') != 'recorded':
                raise ValueError('边界审核缺失或已过期')
            directory = case_dir(self.root, case)
            target = (directory / reference['record_path']).resolve()
            if (not target.is_relative_to(directory.resolve()) or not target.is_file()
                    or sha256(target) != reference.get('sha256')):
                raise ValueError('边界审核记录已缺失或变化')
            expected = boundary_context(directory, data, reference['draft_id'])
            return load_boundary_review(target, expected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path, required=True)
    parser.add_argument('--regenerate', action='store_true')
    args = parser.parse_args()
    raise SystemExit(worker(args.worker.resolve(), args.regenerate))
