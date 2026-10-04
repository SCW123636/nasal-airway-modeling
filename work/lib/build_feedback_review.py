"""Compare informal feedback with immutable proposals and real CT.

Produces diagnostic views only; never selects replacement positions or approves
anatomy. Local sampled areas do not represent the full CFD opening.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import SimpleITK as sitk
from scipy.spatial import cKDTree
from auto_anatomy_landmarks import NAMES, affine, geometry_matches, indices, physical, sample, unit

ROOT = Path(__file__).resolve().parents[1]
CASES = ('p0', 'p1', 'p2', 'p3', 'p3t1')
OFFSETS = [-2., -1., 0., 1., 2.]
HALF_WIDTH_MM, PIXEL_MM, METRIC_RADIUS_MM = 20., .5, 10.
COLORS = {'nasal_cavity_left': (1., .55, .12), 'nasal_cavity_right': (.12, .75, .86),
          'nasopharynx': (.9, .31, .39), 'oropharynx': (.51, .35, .92),
          'hard_palate': (.95, .82, .18), 'soft_palate': (.35, .78, .39)}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2,
                                    allow_nan=False)+'\n', encoding='utf-8')


def resolve_feedback(feedback, reports):
    """Only a known case, justified label alias and rounded coordinates bind."""
    out = []
    for observation in feedback['observations']:
        item = dict(observation)
        case = reports.get(item['reported_case'])
        key = item['reported_landmark']
        alias_used = False
        if key == 'posterior_choana_1' and item.get('reported_label_zh') == '左后鼻孔候选':
            key, alias_used = 'posterior_choana_L', True
        point = np.asarray(item['reported_point_lps_mm'], float)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError('Feedback coordinates must be finite LPS triplets')
        proposal = case['landmarks'].get(key) if case else None
        item['bound_to_current_proposal'] = False
        item['alias_from_explicit_chinese_label'] = alias_used
        if proposal and proposal.get('point_lps_mm') is not None:
            current = np.asarray(proposal['point_lps_mm'])
            delta = point-current
            matched = np.linalg.norm(delta) <= feedback['matching_tolerance_mm']
            item.update(current_case=case['case'], current_landmark=key,
                        current_point_lps_mm=current.tolist(), reported_minus_current_mm=delta.tolist(),
                        discrepancy_mm=float(np.linalg.norm(delta)),
                        match_status='rounded_match' if matched else 'coordinate_mismatch',
                        bound_to_current_proposal=bool(matched))
        else:
            item['match_status'] = 'unknown_case_or_landmark'
            ranked = []
            for cid, data in reports.items():
                for lid, candidate in data['landmarks'].items():
                    if lid != key or candidate.get('point_lps_mm') is None:
                        continue
                    p = np.asarray(candidate['point_lps_mm'])
                    ranked.append((float(np.linalg.norm(p-point)), cid, lid, p.tolist()))
            if ranked:
                distance, cid, lid, p = min(ranked)
                item['nearest_numeric_reference_only'] = {
                    'case': cid, 'landmark': lid, 'point_lps_mm': p,
                    'distance_mm': distance, 'is_identity_confirmation': False}
        out.append(item)
    return out


def plane_basis(normal):
    n = unit(normal)
    seed = np.eye(3)[int(np.argmin(np.abs(n)))]
    u = unit(seed-np.dot(seed, n)*n)
    v = unit(np.cross(n, u))
    return u, v, n


def plane_points(point, u, v, half_width=HALF_WIDTH_MM, step=PIXEL_MM):
    axis = np.arange(-half_width, half_width+step/2, step)
    xx, yy = np.meshgrid(axis, axis)
    return np.asarray(point)+xx[..., None]*u+yy[..., None]*v, xx, yy


def sample_tile(ct, masks, a, point, u, v):
    points, xx, yy = plane_points(point, np.asarray(u), np.asarray(v))
    hu = sample(ct, points, a)
    labels = {key: sample(value, points, a, order=0, outside=0) > 0 for key, value in masks.items()}
    return hu, labels, xx, yy


def tile_metrics(tile, target_names):
    hu, labels, xx, yy = tile
    disk = xx**2+yy**2 <= METRIC_RADIUS_MM**2
    valid = disk & np.isfinite(hu)
    target = np.logical_or.reduce([labels[name] for name in target_names])
    return {'window_radius_mm': METRIC_RADIUS_MM, 'sampling_step_mm': PIXEL_MM,
            'valid_fov_fraction': float(valid.sum()/disk.sum()),
            'target_label_air_area_mm2': float(np.count_nonzero(target & valid & (hu < -300))*PIXEL_MM**2),
            'hard_palate_label_area_mm2': float(np.count_nonzero(labels['hard_palate'] & valid)*PIXEL_MM**2),
            'soft_palate_label_area_mm2': float(np.count_nonzero(labels['soft_palate'] & valid)*PIXEL_MM**2),
            'target_labels': target_names,
            'interpretation': 'Local sampled areas, not whole opening areas or anatomical pass/fail.'}


def draw_tile(ax, tile, title, font, overlay=True, line_normal=None):
    hu, labels, xx, yy = tile
    extent = [-HALF_WIDTH_MM-PIXEL_MM/2, HALF_WIDTH_MM+PIXEL_MM/2]*2
    cmap = __import__('matplotlib').colormaps['gray'].copy(); cmap.set_bad('#777777')
    ax.imshow(hu, cmap=cmap, vmin=-1000, vmax=800, origin='lower', extent=extent)
    if overlay:
        rgba = np.zeros(hu.shape+(4,), float)
        for key in NAMES:
            valid = labels[key] & np.isfinite(hu)
            rgba[valid, :3] = COLORS[key]; rgba[valid, 3] = .30
        ax.imshow(rgba, origin='lower', extent=extent)
    ax.plot(0, 0, '+', color='#32ff62', ms=13, mew=1.4)
    if line_normal is not None and np.linalg.norm(line_normal) > 1e-9:
        d = unit(np.array([-line_normal[1], line_normal[0]]))*HALF_WIDTH_MM*2
        ax.plot([-d[0], d[0]], [-d[1], d[1]], '--', color='#32ff62', lw=1)
    ax.set(xlim=(-HALF_WIDTH_MM, HALF_WIDTH_MM), ylim=(-HALF_WIDTH_MM, HALF_WIDTH_MM))
    ax.set_title(title, fontproperties=font, fontsize=10)
    ax.set_xticks([-20, -10, 0, 10, 20]); ax.set_yticks([-20, -10, 0, 10, 20])
    ax.tick_params(labelsize=8)


def load_case(report):
    ct_path = Path(report['source_ct'])
    paths = [ct_path]+[ct_path.parent/'masks'/(name+'.nii.gz') for name in NAMES]
    hashes = {str(p): sha256(p) for p in paths}
    image = sitk.ReadImage(str(ct_path)); a_full = affine(image)
    if (list(image.GetSize()) != report['source_geometry']['size_xyz'] or
        not np.allclose(a_full, report['source_geometry']['affine_4x4_LPS'], rtol=0, atol=1e-5)):
        raise ValueError(report['case']+': CT header differs from proposal source geometry')
    candidates = np.array([lm['point_lps_mm'] for lm in report['landmarks'].values() if lm.get('point_lps_mm') is not None])
    q = indices(candidates, a_full); shape = np.asarray(image.GetSize())[::-1]
    if not np.all((q >= 0) & (q <= shape-1)):
        raise ValueError(report['case']+': a candidate lies outside the CT')
    margin = np.ceil(35/np.asarray(image.GetSpacing())[::-1]).astype(int)
    lo = np.maximum(0, np.floor(q.min(0)).astype(int)-margin)
    hi = np.minimum(shape, np.ceil(q.max(0)).astype(int)+margin+1)
    region = tuple(slice(int(x), int(y)) for x, y in zip(lo, hi))
    ct = sitk.GetArrayFromImage(image)[region].astype(np.float32)
    masks = {}; palate_tree = None
    for name, path in zip(NAMES, paths[1:]):
        mi = sitk.ReadImage(str(path))
        if not geometry_matches(image, mi):
            raise ValueError(report['case']+'/'+name+': label/CT geometry mismatch')
        arr = sitk.GetArrayFromImage(mi) > 0
        if name == 'hard_palate':
            centers = physical(np.argwhere(arr), a_full)
            if not len(centers): raise ValueError('Missing hard palate reference')
            palate_tree = cKDTree(centers)
        masks[name] = arr[region].astype(np.uint8)
        del arr, mi
    a = a_full.copy(); a[:3, 3] = physical(lo, a_full)
    return ct, masks, a, a_full, palate_tree, hashes


def audit_case(report, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
    ct, masks, a, a_full, palate, hashes = load_case(report)
    target_dir = out/report['case']; target_dir.mkdir(exist_ok=True)
    frame = report['anatomy_frame']; origin = np.asarray(frame['origin_lps_mm'])
    basis = np.array([frame[k] for k in ('left_lps', 'posterior_lps', 'superior_lps')])
    result = []
    for key, lm in report['landmarks'].items():
        point = np.asarray(lm['point_lps_mm']); normal = unit(lm['normal_lps'])
        hu = float(sample(ct, point, a))
        local_labels = [name for name, arr in masks.items() if float(sample(arr, point, a, order=0, outside=0)) > 0]
        dist, _ = palate.query(point); idx = indices(point, a_full)
        entry = {'id': key, 'label_zh': lm['label_zh'], 'point_lps_mm': point.tolist(),
                 'normal_lps': normal.tolist(), 'original_status': lm['status'], 'index_xyz': idx[::-1].tolist(),
                 'roundtrip_error_mm': float(np.linalg.norm(physical(idx, a_full)-point)),
                 'local_frame_lps_mm': (basis @ (point-origin)).tolist(),
                 'signed_distance_to_fitted_palate_plane_mm': float(np.dot(point-origin, basis[2])),
                 'nearest_hard_palate_voxel_center_mm': float(dist),
                 'ct_hu_trilinear': hu if np.isfinite(hu) else None,
                 'nearest_voxel_labels': local_labels, 'clinical_acceptance': False, 'proposed_adjustment': None}
        views = [(np.array([1., 0, 0]), np.array([0., 1, 0]), '轴向：右→患者左 L；上→后 P'),
                 (np.array([1., 0, 0]), np.array([0., 0, 1]), '冠状：右→患者左 L；上→头 S'),
                 (np.array([0., 1, 0]), np.array([0., 0, 1]), '矢状：右→后 P；上→头 S')]
        tiles = [sample_tile(ct, masks, a, point, u, v) for u, v, _ in views]
        for overlay, tag in [(False, 'raw'), (True, 'labels')]:
            fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.1))
            for ax, tile, (u, v, title) in zip(axes, tiles, views):
                draw_tile(ax, tile, title, font, overlay, [normal @ u, normal @ v])
                ax.set_xlabel('距候选点 mm', fontproperties=font, fontsize=9)
            fig.suptitle(report['case']+' · '+lm['label_zh']+' · 原始 CT 插值重采样', fontproperties=font)
            fig.tight_layout()
            filename = key+'_'+tag+'.png'; fig.savefig(target_dir/filename, dpi=150); plt.close(fig)
            entry[tag+'_image'] = report['case']+'/'+filename
        u, v, n = plane_basis(normal)
        targets = (['nasal_cavity_left' if key.endswith('_L') else 'nasal_cavity_right']
                   if key.startswith(('nostril_', 'posterior_choana_')) else ['nasopharynx', 'oropharynx'])
        if key.startswith('posterior_choana_'): targets.append('nasopharynx')
        sweeps = []; fig, axes = plt.subplots(1, len(OFFSETS), figsize=(16, 4.1))
        for ax, offset in zip(axes, OFFSETS):
            center = point+offset*n; tile = sample_tile(ct, masks, a, center, u, v)
            metrics = tile_metrics(tile, targets)
            metrics.update(offset_along_normal_mm=offset, point_lps_mm=center.tolist()); sweeps.append(metrics)
            draw_tile(ax, tile, '法向位移 '+format(offset, '+.0f')+' mm', font)
            ax.set_xlabel('局部平面 u / mm', fontsize=9, fontproperties=font)
        fig.suptitle(report['case']+' · '+lm['label_zh']+' · 仅作局部敏感性对照，不是调整建议', fontproperties=font)
        fig.tight_layout(); filename = key+'_normal_sweep.png'
        fig.savefig(target_dir/filename, dpi=150); plt.close(fig)
        entry.update(sweep_image=report['case']+'/'+filename, normal_sweep=sweeps,
                     plane_u_lps=u.tolist(), plane_v_lps=v.tolist()); result.append(entry)
        print(report['case']+'/'+key+' inspected', flush=True)
    for path, digest in hashes.items():
        if sha256(path) != digest: raise RuntimeError('Input changed while inspecting: '+path)
    return {'case': report['case'], 'image_origin_lps_mm': a_full[:3, 3].tolist(),
            'anatomy_frame': frame, 'input_sha256': hashes, 'landmarks': result}


def render_report(payload, path):
    lines = ['# 人工意见核对与局部切面对照', '', '日期：2026-10-02（北京时间）。', '',
             '本轮将医学生转述作为待验证线索；未提供对应原图和精确参考标点。', '',
             '| 意见 | 转述对象 | 当前对应 | 数值差异 mm | 处理 |', '|---|---|---|---:|---|']
    for f in payload['feedback']:
        nearest = f.get('nearest_numeric_reference_only', {})
        current = f.get('current_case', nearest.get('case', '未找到'))+'/'+f.get('current_landmark', nearest.get('landmark', ''))
        delta = f.get('discrepancy_mm', nearest.get('distance_mm'))
        state = {'rounded_match': '舍入匹配，纳入该点复核', 'coordinate_mismatch': '坐标不符，只保留该对象的核查问题',
                 'unknown_case_or_landmark': '对象未识别，最接近项不代表身份确认'}[f['match_status']]
        lines.append('| '+f['id']+' | '+f['reported_case']+'/'+f['reported_landmark']+' | '+current+' | '+(format(delta,'.3f') if delta is not None else '—')+' | '+state+' |')
    lines += ['', '## 本轮实际产物', '',
              '- 五扫描、25 点核对 CT 几何，每点生成原 CT 三视图、语义标签叠加图、五档法向位移对照。',
              '- 三视图经过候选精确物理位置；显示轴方向明确，不能把所有视图的屏幕向上都解释为 z 增加。',
              '- 法向 −2/−1/0/+1/+2 mm 是敏感性试探，不是已建议或已应用的调整；未改变法向角度。',
              '- 测量包括 CT 插值 HU、局部解剖坐标、至硬腭标签体素中心的最近距离及半径 10 mm 窗口的标签面积。',
              '- 最近体素中心距离不是组织边界距离；拟合硬腭平面的距离不是硬腭厚度或临床安全距离。',
              '- 窗口面积不是完整开口面积。平面窗口含硬腭标签不能单独证明 CFD 切错结构；标签仍待验证。',
              '- CT、六类标签与原候选保留哈希核验。反馈未写入 accept/adjust 决定，候选未自动成为 confirmed。', '',
              '## 选择性采纳', '',
              '采纳鼻孔深度、后鼻孔周围结构、点位与法向分别检查三个问题。转述存在反复和数值冲突，暂不支持定量移点。', '',
              '不采用跨病例通用标准 XYZ、按绝对 z 大小判断解剖位置、统一下调 z、或要求每个十字贴彩色边缘。当前点是拟合样本中心，颜色来自参考语义标签，两者都不等同于独立医学真值。', '',
              '虚线来自候选拟合平面与显示切面的交线；定位脚本以 SVD 拟合平面，并未测得解剖表面切线。原索引切片取整时，投影十字与交线可能不相交；新物理重采样三视图经过同一候选点。', '',
              '## 完成范围', '', '本轮完成数据核对与可复现对照，解剖接受及患者 CFD 仍未完成。工程检查不能替代参考标注。', '',
              '详见 feedback_review/index.html 与 feedback_review/audit.json。']
    path.write_text('\n'.join(lines)+'\n', encoding='utf-8')


def render_html(payload, out):
    template = Path(__file__).with_name('feedback_review_template.html').read_text(encoding='utf-8')
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    (out/'index.html').write_text(template.replace('__AUDIT_DATA__', encoded), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-dir', type=Path, default=ROOT/'06_auto_landmarks')
    parser.add_argument('--feedback', type=Path, default=None)
    parser.add_argument('--html-only', action='store_true', help='Rebuild the page from the existing audit without resampling CT or changing the audit')
    args = parser.parse_args(); base = args.base_dir.resolve()
    out = base/'feedback_review'; out.mkdir(exist_ok=True)
    if args.html_only:
        payload = json.loads((out/'audit.json').read_text(encoding='utf-8'))
        if payload.get('schema') != 'landmark_feedback_audit/v1':
            raise ValueError('Existing feedback audit schema is invalid')
        render_html(payload, out)
        print('Rebuilt HTML from existing audit', flush=True)
        return
    feedback_path = args.feedback or base/'feedback_20261002.json'
    feedback = json.loads(feedback_path.read_text(encoding='utf-8'))
    reports = {cid: json.loads((base/cid/'landmarks.json').read_text(encoding='utf-8')) for cid in CASES}
    before = {cid: sha256(base/cid/'landmarks.json') for cid in CASES}
    payload = {'schema': 'landmark_feedback_audit/v1', 'coordinate_system': 'LPS', 'unit': 'mm',
               'generated_at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
               'feedback_source_sha256': sha256(feedback_path), 'generator_sha256': sha256(__file__),
               'scope': 'Diagnostic measurements and hypothesis review only; no approval or applied adjustment.',
               'feedback': resolve_feedback(feedback, reports), 'cases': [], 'original_proposal_sha256': before,
               'sampling': {'half_width_mm': HALF_WIDTH_MM, 'step_mm': PIXEL_MM,
                            'metric_radius_mm': METRIC_RADIUS_MM, 'normal_offsets_mm': OFFSETS}}
    for report in reports.values(): payload['cases'].append(audit_case(report, out))
    after = {cid: sha256(base/cid/'landmarks.json') for cid in CASES}
    if before != after: raise RuntimeError('Original proposals changed during audit')
    payload['input_integrity_verified'] = True; write_json(out/'audit.json', payload)
    render_html(payload, out)
    render_report(payload, base/'人工意见采纳与复核结果-20261002.md')
    print(json.dumps({'cases': len(payload['cases']), 'points': sum(len(c['landmarks']) for c in payload['cases']),
                      'matched_feedback': sum(f['bound_to_current_proposal'] for f in payload['feedback']),
                      'original_proposals_unchanged': before == after}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
