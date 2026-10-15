"""T-011 A.0 根因探针：nasopharynx_outlet 的 clip_failed 真实触发点。

只读探针：不导入即修改任何生产文件，不写 work/lib 下任何文件。做法：
  1. 用生产函数 load_planes(--proposals 语义) 读 p0 landmarks，读 p0 source_surface.vtp
  2. monkeypatch auto_opening_pipeline.clip_and_cap（仅运行时属性替换，不改文件），
     跑**真正的生产 process()**，记录每一次 clip_and_cap 调用收到的 selectors：
     键集合、每个 mask 是否 None / dtype / shape / True 计数，并在抛错时抓 traceback
  3. 用逐行复刻的 clip_and_cap（含插桩）重放同一批输入，读出第 198-201 行判定时
     mask_is_none / outside_plane / outside_roi 的真值，以及出盒/出面的量化明细
  4. 对照实验：单独只裁 outlet（全新表面）vs 生产顺序（先两鼻孔后 outlet）vs 纯 ROI 盒语义

用法：
  C:/Users/lenovo/AppData/Local/Programs/Python/Python310/python.exe \
      "D:/项目/鼻腔建模/outputs/T-011/a0_clip_root_cause_probe.py"
"""
from __future__ import annotations

import json
import sys
import traceback
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')

import numpy as np  # noqa: E402

ROOT = Path(r'D:\项目\鼻腔建模')
LIB = ROOT / 'work' / 'lib'
sys.path.insert(0, str(LIB))

from auto_opening_pipeline import (  # noqa: E402
    OPENINGS, build_placed, load_planes, place, plane_basis,
)
from connectivity_opened_surface import flood_mask  # noqa: E402
from export_candidate_preview import triangle_arrays  # noqa: E402
from partitioned_surface import boundary_loops, clip_and_cap as REAL_CLIP, topology  # noqa: E402
from planar_cap import triangulate_cap  # noqa: E402

import auto_opening_pipeline as A  # noqa: E402

CASE = 'p0'
SURFACE = Path('C:/ts_work/batch27_surfaces') / CASE / 'source_surface.vtp'
TOL = 1e-7
OUT_JSON = ROOT / 'outputs' / 'T-011' / 'a0_clip_root_cause.json'
OUT_DIR = ROOT / 'outputs' / 'T-011' / '_probe_run'   # process() 只在成功时写；本例必失败

result: dict = {'case': CASE, 'tolerance_mm': TOL}


# --------------------------------------------------------------------------
# 1. 数据装载（与生产 --proposals 路径完全一致）
# --------------------------------------------------------------------------
def load_surface_bare(path):
    import vtk
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    return triangle_arrays(reader.GetOutput())


def load_surface():
    return load_surface_bare(SURFACE)


# --------------------------------------------------------------------------
# 2. monkeypatch：记录生产 clip_and_cap 的每一次调用
# --------------------------------------------------------------------------
CALLS: list = []


def mask_stats(selectors, name):
    """(is_none, dtype, len, true_count) for selectors.get(name)."""
    if selectors is None:
        return {'selectors_is_none': True}
    m = selectors.get(name, '<KEY_MISSING>')
    if isinstance(m, str):
        return {'key_present': False}
    if m is None:
        return {'key_present': True, 'mask_is_none': True}
    arr = np.asarray(m)
    return {'key_present': True, 'mask_is_none': False, 'dtype': str(arr.dtype),
            'len': int(arr.size), 'true_count': int(np.count_nonzero(arr))}


def spy_clip_and_cap(vertices, triangles, planes, *, tolerance_mm=1e-7, selectors=None):
    caller = traceback.extract_stack()[-2]
    rec = {
        'caller_file': Path(caller.filename).name,
        'caller_line': caller.lineno,
        'caller_func': caller.name,
        'n_vertices': int(len(vertices)),
        'n_triangles': int(len(triangles)),
        'planes_keys': list(planes.keys()),
        'selectors_is_none': selectors is None,
        'selectors_keys': None if selectors is None else list(selectors.keys()),
        'per_opening': {k: mask_stats(selectors, k) for k in OPENINGS},
    }
    try:
        out = REAL_CLIP(vertices, triangles, planes, tolerance_mm=tolerance_mm,
                        selectors=selectors)
        rec['raised'] = None
        rec['ok'] = True
        CALLS.append(rec)
        return out
    except BaseException as exc:  # noqa: BLE001
        rec['ok'] = False
        rec['raised_type'] = type(exc).__name__
        rec['raised_msg'] = str(exc)
        tb = traceback.format_exc().splitlines()
        rec['traceback_tail'] = tb[-8:]
        # 抛出点在 partitioned_surface.py 的哪一行？
        frames = traceback.extract_tb(exc.__traceback__)
        rec['raise_frames'] = [{'file': Path(f.filename).name, 'line': f.lineno,
                                'func': f.name} for f in frames]
        CALLS.append(rec)
        raise


# --------------------------------------------------------------------------
# 3. 逐行复刻 clip_and_cap（含第 198-201 行判定的插桩）
# --------------------------------------------------------------------------
def replica_clip(vertices, triangles, planes, *, tolerance_mm=TOL, selectors=None,
                 order=None, tag='', recompute_mask=False):
    selectors = selectors or {}
    points = np.asarray(vertices, dtype=float)
    faces = np.asarray(triangles).astype(np.int64, copy=True)
    n_original = len(points)
    patches = np.full(len(faces), 'wall', dtype=object)
    trace = []
    for name, spec in [(k, planes[k]) for k in (order or list(planes))]:
        origin = np.asarray(spec.get('point_lps_mm'), dtype=float)
        normal = np.asarray(spec.get('normal_lps'), dtype=float)
        roi = spec.get('roi_lps_mm', {})
        low = np.asarray(roi.get('min'), dtype=float)
        high = np.asarray(roi.get('max'), dtype=float)
        normal = normal / np.linalg.norm(normal)
        kept_normal = normal if spec['keep_positive'] else -normal
        signed = (points - origin) @ kept_normal
        signed[np.abs(signed) <= tolerance_mm] = 0
        xyz = points[faces]
        n_pts_in, n_fcs_in = len(points), len(faces)
        mask = selectors.get(name)
        mask_is_none = mask is None
        mask_len = None
        mask_true = None
        mask_origin = 'selectors（原始表面构建，可能已过期）'
        if mask is not None:
            mask = np.asarray(mask, dtype=bool)
            mask_len = int(len(mask))
            if len(mask) > len(points):
                raise ValueError(name + ': selector mask is longer than the vertex array')
            if len(mask) < len(points):
                mask = np.concatenate((mask, np.zeros(len(points) - len(mask), dtype=bool)))
            mask_true = int(mask[:n_original].sum())
        if recompute_mask and not mask_is_none:
            # 只读诊断分支：在当前（已被前面平面改写过的）网格上重算同一个连通性掩码
            try:
                m2, _note2 = flood_mask(points, faces, spec, seed_mode='roi')
            except ValueError as exc:
                return {'tag': tag, 'plane': name,
                        'replica_raised': f'recompute flood_mask: {type(exc).__name__}: {exc}',
                        'trace': trace}
            mask = np.asarray(m2, dtype=bool)
            mask_len = int(len(mask))
            mask_true = int(mask.sum())
            mask_origin = 'recomputed_on_current_mesh'
        if mask is not None:
            inside = np.any(mask[faces], axis=1)
        else:
            overlap = ((xyz.max(axis=1) >= low) & (xyz.min(axis=1) <= high)).all(axis=1)
            inside = ((xyz >= low) & (xyz <= high)).all(axis=(1, 2))
            negative = np.any(signed[faces] < 0, axis=1)
            conflicts = overlap & ~inside & negative
            if np.any(conflicts):
                return {'tag': tag, 'plane': name, 'replica_raised':
                        f'SurfaceClipError: {name}: deleted wall crosses the configured ROI boundary',
                        'n_conflicting_triangles': int(conflicts.sum()), 'trace': trace}
        faces_before = faces.copy()
        patches_before = patches.copy()
        affected = inside & np.any(signed[faces] < 0, axis=1)
        if not affected.any():
            return {'tag': tag, 'plane': name,
                    'replica_raised': f'ValueError: {name}: plane does not cut the selected surface',
                    'trace': trace}
        if np.any(patches[affected] != 'wall'):
            return {'tag': tag, 'plane': name,
                    'replica_raised': f'SurfaceClipError: {name}: cutting plane intersects an earlier cap',
                    'trace': trace}
        new_points = points.tolist()
        cache = {}

        def intersection(a, b):
            if signed[a] == 0:
                return a
            if signed[b] == 0:
                return b
            edge = tuple(sorted((a, b)))
            if edge not in cache:
                start, stop = edge
                fraction = signed[start] / (signed[start] - signed[stop])
                cache[edge] = len(new_points)
                new_points.append((points[start] + fraction * (points[stop] - points[start])).tolist())
            return cache[edge]

        output = faces[~affected].tolist()
        labels = patches[~affected].tolist()
        n_dropped_polygon = 0
        n_tri_out = 0
        for face in faces[affected]:
            polygon = []
            for a, b in zip(face.tolist(), np.roll(face, -1).tolist()):
                if signed[a] >= 0:
                    polygon.append(a)
                if (signed[a] >= 0) != (signed[b] >= 0):
                    polygon.append(intersection(a, b))
            clean = []
            for index in polygon:
                if not clean or index != clean[-1]:
                    clean.append(index)
            if len(clean) > 1 and clean[0] == clean[-1]:
                clean.pop()
            if len(clean) < 3:
                n_dropped_polygon += 1
            for i in range(1, len(clean) - 1):
                output.append([clean[0], clean[i], clean[i + 1]])
                labels.append('wall')
                n_tri_out += 1
        points = np.asarray(new_points, dtype=float)
        faces = np.asarray(output, dtype=np.int64).reshape(-1, 3)
        patches = np.asarray(labels, dtype=object)
        if not len(faces):
            return {'tag': tag, 'plane': name,
                    'replica_raised': f'ValueError: {name}: clip removes the entire surface',
                    'trace': trace}
        interim, edges = topology(points, faces)
        try:
            loops = boundary_loops(edges)
            loops_err = None
        except ValueError as exc:
            loops = []
            loops_err = str(exc)
        used = np.unique(edges)
        # 生产第195行就是拿**裁剪后**的 points 直接投影，这里逐字复刻（含新增交点顶点）
        sid_full = (points - origin) @ kept_normal
        dev = sid_full[used] if len(used) else np.zeros(0)
        absdev = np.abs(dev)
        outside_plane = bool(absdev.max() > tolerance_mm) if len(used) else False
        outside_roi = bool(not ((points[used] >= low - tolerance_mm) &
                                (points[used] <= high + tolerance_mm)).all()) if len(used) else False
        rec = {
            'tag': tag, 'plane': name,
            'n_pts_in': n_pts_in, 'n_fcs_in': n_fcs_in,
            'n_pts_appended_by_this_plane': int(len(points) - n_pts_in),
            'mask_is_none': mask_is_none, 'mask_len': mask_len, 'mask_true_count': mask_true,
            'mask_origin': mask_origin,
            'n_inside_faces': int(inside.sum()), 'n_affected_faces': int(affected.sum()),
            'n_affected_faces_yielding_no_triangle': int(n_dropped_polygon),
            'n_triangles_written_from_affected': int(n_tri_out),
            'interim_boundary_edges': int(interim['boundary_edges']),
            'n_boundary_verts': int(len(used)),
            'boundary_loops': len(loops), 'boundary_loops_error': loops_err,
            'outside_plane': outside_plane,
            'outside_roi': outside_roi,
            'boundary_max_abs_dev_mm': float(absdev.max()) if len(used) else 0.0,
            'production_line198_raises': bool(outside_plane or (outside_roi and mask_is_none)),
            'roi_min': low.tolist(), 'roi_max': high.tolist(),
        }
        if rec['production_line198_raises'] or (len(used) and absdev.max() > 0):
            # 出盒/出面的量化明细（Q2）
            bpts = points[used]
            rec['boundary_coord_min'] = bpts.min(axis=0).tolist()
            rec['boundary_coord_max'] = bpts.max(axis=0).tolist()
            rec['roi_overflow_mm'] = {
                'low_side': np.maximum(0.0, low - bpts.min(axis=0)).tolist(),
                'high_side': np.maximum(0.0, bpts.max(axis=0) - high).tolist()}
            off = absdev > tolerance_mm
            off_v = used[off]
            rec['n_boundary_verts_off_plane'] = int(off.sum())
            rec['n_offplane_positive_side'] = int((dev[off] > 0).sum())
            rec['n_offplane_negative_side'] = int((dev[off] < 0).sum())
            rec['offplane_signed_mm_sorted'] = sorted(dev[off].round(6).tolist())
            worst = np.argsort(-absdev)[:10]
            mask_full = mask
            if mask_full is not None and len(mask_full) < len(points):
                mask_full = np.concatenate((mask_full,
                                            np.zeros(len(points) - len(mask_full), dtype=bool)))
            rec['worst_boundary_verts'] = []
            for i in worst:
                idx = int(used[i])
                coords = points[idx].tolist()
                fwith = np.where((faces_before == idx).any(axis=1))[0]
                kept = fwith[~affected[fwith]]
                rec['worst_boundary_verts'].append({
                    'vertex_index': idx,
                    'is_appended_intersection_vertex': bool(idx >= n_original),
                    'signed_mm': float(sid_full[idx]),
                    'coord_lps_mm': [round(c, 4) for c in coords],
                    'faces_before_containing': int(len(fwith)),
                    'of_those_affected': int(affected[fwith].sum()),
                    'of_those_kept': int(len(kept)),
                    'kept_faces_that_are_earlier_caps': int(sum(
                        patches_before[f] != 'wall' for f in kept)),
                    'mask_true_at_vertex': (None if mask_full is None else bool(mask_full[idx])),
                })
            # 集合级统计：出面的边界顶点/边来自哪里、粘贴在谁身上
            offv = used[absdev > tolerance_mm]
            rec['n_offplane_verts_from_source_surface'] = int((offv < n_original).sum())
            rec['n_offplane_verts_appended_by_earlier_planes'] = int((offv >= n_original).sum())
            rec['n_offplane_verts_appended_by_this_plane'] = int((offv >= n_pts_in).sum())
            rec['n_boundary_edges_total'] = int(len(edges))
            keeplab = []
            for idx in offv:
                fw = np.where((faces_before == int(idx)).any(axis=1))[0]
                keeplab.extend([str(patches_before[f]) for f in fw[~affected[fw]]])
            rec['offplane_vert_kept_face_patch_counts'] = dict(Counter(keeplab))
            # 出面的边界边：两端 signed 与是否新增顶点
            off_edges = []
            for e in edges:
                a, b = int(e[0]), int(e[1])
                if abs(sid_full[a]) > tolerance_mm or abs(sid_full[b]) > tolerance_mm:
                    off_edges.append({'v': [a, b],
                                      'signed_mm': [round(float(sid_full[a]), 5),
                                                    round(float(sid_full[b]), 5)],
                                      'kinds': [('appended' if a >= n_pts_in else 'original'),
                                                ('appended' if b >= n_pts_in else 'original')]})
            rec['n_offplane_boundary_edges'] = len(off_edges)
            rec['offplane_boundary_edges_head'] = off_edges[:12]
        trace.append(rec)
        if rec['production_line198_raises']:
            return {'tag': tag, 'plane': name,
                    'replica_raised': f'ValueError: {name}: unexpected boundary outside cutting '
                                      f'plane or ROI (outside_plane={outside_plane}, '
                                      f'outside_roi={outside_roi}, mask_is_none={mask_is_none})',
                    'detail': rec, 'trace': trace}
        if loops_err:
            return {'tag': tag, 'plane': name,
                    'replica_raised': f'ValueError: {loops_err}', 'detail': rec, 'trace': trace}
        # 生产第202-213行：加盖 + 拓扑/体积校验，并把 points/faces/patches 推进到下一平面
        try:
            caps, cap_report = triangulate_cap(points, loops, -kept_normal,
                                               tolerance_mm=tolerance_mm)
        except ValueError as exc:
            rec['replica_raised'] = f'triangulate_cap: {type(exc).__name__}: {exc}'
            return {'tag': tag, 'plane': name, 'replica_raised': rec['replica_raised'],
                    'detail': rec, 'trace': trace}
        faces = np.vstack((faces, caps))
        patches = np.concatenate((patches, np.full(len(caps), name, dtype=object)))
        rec['n_cap_triangles'] = int(len(caps))
        final, _ = topology(points, faces)
        rec['final_boundary_edges'] = int(final['boundary_edges'])
        rec['final_nonmanifold_edges'] = int(final['nonmanifold_edges'])
        rec['final_signed_volume_mm3'] = float(final['signed_volume_mm3'])
        if any(final[key] for key in ('boundary_edges', 'nonmanifold_edges',
                                      'inconsistent_winding_edges', 'degenerate_triangles',
                                      'duplicate_triangles')):
            return {'tag': tag, 'plane': name,
                    'replica_raised': f'ValueError: {name}: capped surface fails topology',
                    'detail': rec, 'trace': trace}
        trace.append(rec)
        # 第198行判定通过：按生产语义继续处理下一个面（points/faces/patches 已被改写）
    xyz = points[faces]
    areas = {}
    for nm in OPENINGS:
        t = xyz[patches == nm]
        if len(t):
            areas[nm] = round(float(np.linalg.norm(
                np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum() * .5), 2)
    return {'tag': tag, 'plane': None, 'replica_raised': None,
            'note': '所有平面均通过第198行判定（未复现报错）',
            'patch_areas_mm2': areas, 'trace': trace}


# --------------------------------------------------------------------------
def main() -> int:
    print('=== 装载 ===')
    planes, provenance, plane_sha, admitted = load_planes(
        ROOT / 'work' / '06_auto_landmarks', None, CASE, allow_needs_review=False)
    pts, fcs = load_surface()
    pts = np.asarray(pts, dtype=float)
    fcs = np.asarray(fcs, dtype=np.int64)
    qc, _ = topology(pts, fcs)
    print(f'surface {SURFACE}: {len(pts)} verts / {len(fcs)} tris  boundary_edges={qc["boundary_edges"]}'
          f'  signed_volume={qc["signed_volume_mm3"]:.3f}')
    print(f'plane provenance={provenance} sha={plane_sha}')
    result['surface'] = {'path': str(SURFACE), 'sha_note': 'see a0_p0_run.json',
                         'n_vertices': int(len(pts)), 'n_triangles': int(len(fcs)),
                         'source_qc': {k: qc[k] for k in
                                       ('boundary_edges', 'nonmanifold_edges',
                                        'inconsistent_winding_edges', 'duplicate_triangles',
                                        'degenerate_triangles', 'signed_volume_mm3')}}
    result['plane_provenance'] = provenance
    result['planes'] = planes

    norms = {k: plane_basis(planes[k]['normal_lps'])[0] for k in OPENINGS}
    placed = build_placed(planes, norms, {k: 0.0 for k in OPENINGS},
                          {k: 0.0 for k in OPENINGS})
    result['placed_at_offset_0'] = placed

    # ---- Q1-a: 生产 clip_areas 里 selectors 的构造（逐开口） ----
    print('\n=== selectors（复刻 clip_areas 第124行：flood_mask(seed_mode=roi)） ===')
    sel = {}
    sel_stats = {}
    for k in OPENINGS:
        try:
            m, note = flood_mask(pts, fcs, placed[k], seed_mode='roi')
            sel[k] = m
            sel_stats[k] = {'returned_type': type(m).__name__, 'is_none': m is None,
                            'dtype': str(np.asarray(m).dtype), 'len': int(len(m)),
                            'true_count': int(np.count_nonzero(m)), 'note': note}
            print(f'  {k}: type={type(m).__name__} is_none={m is None} '
                  f'dtype={np.asarray(m).dtype} len={len(m)} true={int(np.count_nonzero(m))}')
        except ValueError as exc:
            sel_stats[k] = {'raised': f'{type(exc).__name__}: {exc}'}
            print(f'  {k}: RAISED {type(exc).__name__}: {exc}')
    result['selectors_from_clip_areas_replication'] = sel_stats

    # ---- Q1-b: 真·生产 process()，spy 记录每一次 clip_and_cap 的 selectors ----
    print('\n=== 跑真·生产 process()（spy 记录每次 clip_and_cap） ===')
    A.clip_and_cap = spy_clip_and_cap
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = A.process(CASE, pts, fcs, {'planes_lps': planes}, OUT_DIR,
                       seed_mode='roi', origin='reviewed', allow_onset_outlier=False)
    A.clip_and_cap = REAL_CLIP
    print(f'process decision = {report.get("decision")}')
    print(f'process escalations = {report.get("escalations")}')
    result['production_process'] = {
        'decision': report.get('decision'),
        'escalations': report.get('escalations'),
        'selection_notes': report.get('selection_notes'),
        'offset_from_reviewed_mm': report.get('offset_from_reviewed_mm'),
        'placement_evidence': report.get('placement_evidence'),
        'n_clip_and_cap_calls': len(CALLS),
        'clip_and_cap_calls': CALLS,
    }
    print(f'clip_and_cap 调用次数 = {len(CALLS)}')
    for i, c in enumerate(CALLS):
        print(f'  [{i}] {c["caller_file"]}:{c["caller_line"]} {c["caller_func"]}  '
              f'selectors_is_none={c["selectors_is_none"]} keys={c["selectors_keys"]}  '
              f'outlet_mask={c["per_opening"]["nasopharynx_outlet"]}  '
              f'raised={c.get("raised_type")}')
    raise_recs = [c for c in CALLS if not c['ok']]
    if raise_recs:
        r = raise_recs[0]
        print(f'  抛出点帧: {r["raise_frames"][-1]}')
        result['production_raise_call'] = r

    # ---- Q1-c / Q2: 复刻插桩重放 ----
    print('\n=== 复刻 clip_and_cap 插桩重放（生产顺序 + 对照） ===')
    runs = {
        'production_order_all_three_with_masks':
            dict(selectors=sel, order=list(OPENINGS), tag='prod_all3'),
        'outlet_alone_with_mask':
            dict(selectors=sel, order=['nasopharynx_outlet'], tag='outlet_only'),
        'nostril_L_then_outlet_with_masks':
            dict(selectors=sel, order=['nostril_L', 'nasopharynx_outlet'], tag='L_then_outlet'),
        'nostril_R_then_outlet_with_masks':
            dict(selectors=sel, order=['nostril_R', 'nasopharynx_outlet'], tag='R_then_outlet'),
        'production_order_pure_roi_box_no_selector':
            dict(selectors={}, order=list(OPENINGS), tag='roi_box_all3'),
        'production_order_recompute_mask_on_current_mesh':
            dict(selectors=sel, order=list(OPENINGS), tag='recompute_all3',
                 recompute_mask=True),
        'outlet_alone_recompute_mask':
            dict(selectors=sel, order=['nasopharynx_outlet'], tag='recompute_outlet_only',
                 recompute_mask=True),
        'outlet_alone_pure_roi_box_no_selector':
            dict(selectors={}, order=['nasopharynx_outlet'], tag='roi_box_outlet_only'),
    }
    replay = {}
    for title, kw in runs.items():
        try:
            out = replica_clip(pts, fcs, placed, tolerance_mm=TOL, **kw)
        except BaseException as exc:  # noqa: BLE001
            out = {'replica_exception': f'{type(exc).__name__}: {exc}',
                   'trace': traceback.format_exc().splitlines()[-6:]}
        replay[title] = out
        print(f'\n--- {title} ---')
        if out.get('replica_exception'):
            print(f'  replica_exception: {out["replica_exception"]}')
            print(f'  trace: {out.get("trace")}')
        print(f'  replica_raised: {out.get("replica_raised")}')
        if out.get('patch_areas_mm2') is not None:
            print(f'  patch_areas_mm2: {out["patch_areas_mm2"]}')
        if out.get('n_conflicting_triangles') is not None:
            print(f'  n_conflicting_triangles: {out["n_conflicting_triangles"]}')
        d = out.get('detail')
        if out.get('replica_exception') is None and out.get('trace'):
            print('  --- 逐平面 trace ---')
            for t in out['trace']:
                if not isinstance(t, dict):
                    print(f'    (non-dict trace entry: {t})')
                    continue
                print(f'    plane={t.get("plane")} mask_is_none={t.get("mask_is_none")} '
                      f'n_pts_in={t.get("n_pts_in")} '
                      f'pts_appended={t.get("n_pts_appended_by_this_plane")} '
                      f'affected={t.get("n_affected_faces")} '
                      f'dropped_poly={t.get("n_affected_faces_yielding_no_triangle")} '
                      f'bd_edges={t.get("interim_boundary_edges")} '
                      f'bd_verts={t.get("n_boundary_verts")} loops={t.get("boundary_loops")} '
                      f'out_plane={t.get("outside_plane")} out_roi={t.get("outside_roi")} '
                      f'maxdev={t.get("boundary_max_abs_dev_mm")} '
                      f'caps={t.get("n_cap_triangles")} '
                      f'final_bd_edges={t.get("final_boundary_edges")} '
                      f'raise198={t.get("production_line198_raises")}')
                if t.get('roi_overflow_mm'):
                    print(f'      roi_min={np.round(t["roi_min"],3).tolist()} '
                          f'roi_max={np.round(t["roi_max"],3).tolist()}')
                    print(f'      bd_min ={np.round(t["boundary_coord_min"],3).tolist()} '
                          f'bd_max ={np.round(t["boundary_coord_max"],3).tolist()}')
                    print(f'      overflow_low ={np.round(t["roi_overflow_mm"]["low_side"],3).tolist()} '
                          f'overflow_high={np.round(t["roi_overflow_mm"]["high_side"],3).tolist()}')
                    print(f'      n_offplane={t.get("n_boundary_verts_off_plane")} '
                          f'(+side {t.get("n_offplane_positive_side")}, '
                          f'-side {t.get("n_offplane_negative_side")}) '
                          f'offplane_edges={t.get("n_offplane_boundary_edges")}')
                    so = t.get('offplane_signed_mm_sorted') or []
                    print(f'      offplane_signed_mm_sorted: n={len(so)} '
                          f'min={so[0] if so else None} max={so[-1] if so else None} '
                          f'head={so[:5]}')
                    for w in (t.get('worst_boundary_verts') or [])[:5]:
                        print(f'      worst: {w}')
                    print(f'      n_offplane_from_source={t.get("n_offplane_verts_from_source_surface")} '
                          f'appended_by_earlier={t.get("n_offplane_verts_appended_by_earlier_planes")} '
                          f'appended_by_this={t.get("n_offplane_verts_appended_by_this_plane")} '
                          f'bd_edges_total={t.get("n_boundary_edges_total")}')
                    print(f'      offplane_kept_face_patches={t.get("offplane_vert_kept_face_patch_counts")}')
                    for w in (t.get('offplane_boundary_edges_head') or [])[:5]:
                        print(f'      offedge: {w}')
    result['replica_replay'] = replay

    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str),
                        encoding='utf-8')
    print(f'\nwrote {OUT_JSON}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
