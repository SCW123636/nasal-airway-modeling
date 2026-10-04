# -*- coding: utf-8 -*-
"""
鼻腔气道自动分割 v6 — 形态学判据（基于实测解剖，最终版）
==============================================================
核心判据（来自 z=160 层实测 + 放大图视觉确认）：

  | 结构     | 形态特征           | 填充率    | 位置   |
  |---------|-------------------|----------|--------|
  | 鼻腔     | 细长、弯曲、纵向延伸 | 低 0.2-0.4 | 中央   |
  | 上颌窦   | 饱满、圆/椭圆       | 高 0.6-0.8 | 外侧   |
  | 筛窦/额窦| 蜂窝/分叶           | 中        | 上方   |
  | 外部空气 | 接触图像边缘        | -         | 四周   |

关键判据 = 中央性(cx 接近中线) + 低填充率(细长) + 不接触边缘

左右鼻腔是两个独立连通域，各自处理，最后合并。
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series


def find_nasal_candidates(mask2d, cfg):
    """
    单层：找出"鼻腔形态"的连通域
    返回候选列表（可能 2 个 → 左右鼻腔）
    """
    ny, nx = mask2d.shape
    XC = cfg["x_center"]
    lbl, n = ndimage.label(mask2d, structure=np.ones((3, 3)))

    out = []
    for lab in range(1, n + 1):
        m = lbl == lab
        size = int(m.sum())
        if size < cfg["min_size"] or size > cfg["max_size"]:
            continue

        ys, xs = np.where(m)
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())

        # 判据0：不接触图像边缘
        if y0 == 0 or y1 == ny - 1 or x0 == 0 or x1 == nx - 1:
            continue

        cx = float(xs.mean())
        cy = float(ys.mean())

        # 判据1：中央性（鼻腔在中线附近）
        if abs(cx - XC) > cfg["x_tol"]:
            continue

        # 判据2：填充率（鼻腔细长 → 低填充率）
        bbox_area = (y1 - y0 + 1) * (x1 - x0 + 1)
        fill = size / bbox_area
        if fill > cfg["max_fill"]:
            continue

        # 判据3：形状细长度（bbox 的宽高比，鼻腔在一个方向明显更长）
        w = x1 - x0 + 1
        h = y1 - y0 + 1
        aspect = max(w, h) / max(1, min(w, h))
        if aspect < cfg["min_aspect"]:
            continue

        out.append({
            "lab": lab, "mask": m, "size": size,
            "cx": cx, "cy": cy,
            "y": (y0, y1), "x": (x0, x1),
            "fill": float(fill), "aspect": float(aspect),
            "w": w, "h": h,
        })

    out.sort(key=lambda c: -c["size"])
    return out


def track_side(cands_by_z, z_anchor, side, cfg):
    """
    沿 z 方向追踪单侧鼻腔
    side: -1 = 中线左侧(cx < XC), +1 = 右侧
    返回 z -> candidate
    """
    XC = cfg["x_center"]
    selected = {}

    def pick(z, prev):
        best, best_score = None, 1e18
        for c in cands_by_z.get(z, []):
            # 只取对应侧
            if side < 0 and c["cx"] >= XC:
                continue
            if side > 0 and c["cx"] <= XC:
                continue
            if prev is None:
                score = abs(c["cx"] - XC) + abs(c["size"] - cfg["anchor_size"]) * 0.01
            else:
                d = np.hypot(c["cx"] - prev["cx"], c["cy"] - prev["cy"])
                if d > cfg["max_jump"]:
                    continue
                ratio = max(c["size"], prev["size"]) / max(1, min(c["size"], prev["size"]))
                if ratio > cfg["max_area_ratio"]:
                    continue
                score = d
            if score < best_score:
                best, best_score = c, score
        return best

    # 锚点层
    anc = pick(z_anchor, None)
    if anc is None:
        return selected
    selected[z_anchor] = anc

    nz = cfg["nz"]
    prev = anc
    for z in range(z_anchor + 1, nz):
        c = pick(z, prev)
        if c is not None:
            selected[z] = c
            prev = c
        # 允许 gap：不清零 prev（容忍 1-2 层缺失）
        else:
            if z - max(selected) > cfg["gap_tolerance"]:
                prev = None
                break

    prev = anc
    for z in range(z_anchor - 1, -1, -1):
        c = pick(z, prev)
        if c is not None:
            selected[z] = c
            prev = c
        else:
            if min(selected) - z > cfg["gap_tolerance"]:
                prev = None
                break

    return selected


def segment_nasal_v6(vol, cfg=None, verbose=True):
    nz, ny, nx = vol.shape
    C = {
        "hu_air_max": -300,
        "x_center": nx // 2,
        "x_tol": 55,              # 中央性：鼻腔 cx 距中线
        "min_size": 120,
        "max_size": 9000,
        "max_fill": 0.50,         # 填充率上限（排除饱满的鼻窦）
        "min_aspect": 1.3,        # 最小长宽比
        "anchor_size": 2000,
        "max_jump": 22,
        "max_area_ratio": 2.2,
        "gap_tolerance": 3,
        "nz": nz,
    }
    if cfg:
        C.update(cfg)

    air = vol < C["hu_air_max"]

    # 阶段1：逐层候选
    cands_by_z = {}
    for z in range(nz):
        cands_by_z[z] = find_nasal_candidates(air[z], C)

    # 阶段2：选锚点层（候选包含左右两侧且尺寸合适的层）
    def anchor_score(z):
        cs = cands_by_z[z]
        left = [c for c in cs if c["cx"] < C["x_center"]]
        right = [c for c in cs if c["cx"] >= C["x_center"]]
        if not left or not right:
            return -1
        return min(max(c["size"] for c in left), max(c["size"] for c in right))

    z_anchor = max(range(nz), key=anchor_score)
    C["anchor_size"] = anchor_score(z_anchor)
    if verbose:
        print(f"=== v6 诊断 ===")
        print(f"锚点层 z={z_anchor}, 锚点尺寸={C['anchor_size']}")
        print(f"锚点层候选:")
        for c in cands_by_z[z_anchor]:
            print(f"   lab={c['lab']} size={c['size']:,} cx={c['cx']:.1f} "
                  f"cy={c['cy']:.1f} fill={c['fill']:.2f} aspect={c['aspect']:.2f}")

    # 阶段3：左右分别追踪
    sel_left = track_side(cands_by_z, z_anchor, -1, C)
    sel_right = track_side(cands_by_z, z_anchor, +1, C)

    if verbose:
        print(f"\n左鼻腔追踪层数: {len(sel_left)}  "
              f"z范围 {min(sel_left) if sel_left else '-'}~{max(sel_left) if sel_left else '-'}")
        print(f"右鼻腔追踪层数: {len(sel_right)}  "
              f"z范围 {min(sel_right) if sel_right else '-'}~{max(sel_right) if sel_right else '-'}")

    # 阶段4：构建掩膜
    mask3d = np.zeros_like(air)
    for z, c in sel_left.items():
        mask3d[z] |= c["mask"]
    for z, c in sel_right.items():
        mask3d[z] |= c["mask"]

    # 阶段5：3D 连通性 + 形态学清理
    lbl3, n3 = ndimage.label(mask3d, structure=np.ones((3, 3, 3)))
    kept = []
    if n3 > 0:
        s3 = ndimage.sum(mask3d, lbl3, range(1, n3 + 1))
        for i in range(n3):
            if s3[i] > 3000:      # 保留主要部分
                kept.append(i + 1)
        keep_mask = np.isin(lbl3, kept)
        mask3d = keep_mask

    diag = {
        "params": {k: v for k, v in C.items() if k != "nz"},
        "anchor_z": int(z_anchor),
        "anchor_size": int(anchor_score(z_anchor)),
        "left_layers": len(sel_left),
        "right_layers": len(sel_right),
        "left_z_range": [min(sel_left), max(sel_left)] if sel_left else None,
        "right_z_range": [min(sel_right), max(sel_right)] if sel_right else None,
        "total_voxels": int(mask3d.sum()),
        "n_components_3d": int(n3),
        "kept_components": len(kept),
    }

    if verbose:
        print(f"\n总掩膜体素: {diag['total_voxels']:,}")
        print(f"3D 连通域: {n3}, 保留: {len(kept)}")

    return {"mask": mask3d, "left": sel_left, "right": sel_right, "diagnostics": diag}


if __name__ == "__main__":
    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape}\n")

    res = segment_nasal_v6(vol)
    outdir = r"D:\项目\鼻腔建模\work\02_segment"
    os.makedirs(outdir, exist_ok=True)
    np.save(os.path.join(outdir, "nasal_mask_v6.npy"), res["mask"])
    with open(os.path.join(outdir, "seg_v6_diag.json"), "w", encoding="utf-8") as f:
        json.dump(res["diagnostics"], f, ensure_ascii=False, indent=2)

    from segment_v2 import render_mask_check
    z_list = [120, 140, 155, 170, 185, 200, 215, 230, 245, 260]
    grid, tiles = render_mask_check(vol, res["mask"], outdir, z_list=z_list, prefix="v6")
    print(f"\n=== 渲染 ===")
    for z, fn, n in tiles:
        print(f"  z={z}: {n:,} 体素")
    print(f"  拼图 -> {grid}")
