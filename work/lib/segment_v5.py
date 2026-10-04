# -*- coding: utf-8 -*-
"""
鼻腔气道自动分割 v5 — 逐层筛选 + 连续性约束（最终版）
==========================================================
本版核心改进（针对 v4 的额窦误检）：
  1. **逐层解剖筛选**（继承 v4）：中央性 + 被环绕 + 尺寸合理
  2. **新增：连续性约束** —— 鼻腔是上下贯通管道
     - 建立层间"质心轨迹"，只保留轨迹连续的层
     - 孤立出现的层（如额窦突然出现）被剔除
  3. **新增：面积突变抑制** —— 鼻腔截面积变化是渐进的
     - 相邻层面积比超过阈值 → 判为不同结构

所有参数显式，无隐藏默认。
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series


def segment_layer_candidates(mask2d, cfg):
    """单层：找出所有符合解剖约束的候选腔，返回列表"""
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

        if cfg["reject_edge"] and (y0 == 0 or y1 == ny - 1 or x0 == 0 or x1 == nx - 1):
            continue

        cx = float(xs.mean())
        if abs(cx - XC) > cfg["x_tol"]:
            continue

        pad = cfg["ring_pad"]
        Y0, Y1 = max(0, y0 - pad), min(ny, y1 + pad + 1)
        X0, X1 = max(0, x0 - pad), min(nx, x1 + pad + 1)
        ring = np.ones((Y1 - Y0, X1 - X0), dtype=bool)
        ring[y0 - Y0:y1 - Y0 + 1, x0 - X0:x1 - X0 + 1] = False
        n_ring = int(ring.sum())
        if n_ring == 0:
            continue
        n_ring_air = int((mask2d[Y0:Y1, X0:X1] & ring).sum())
        surrounded = 1.0 - n_ring_air / n_ring
        if surrounded < cfg["min_surrounded"]:
            continue

        out.append({
            "lab": lab, "mask": m, "size": size,
            "cx": cx, "cy": float(ys.mean()),
            "y": (y0, y1), "x": (x0, x1),
            "surrounded": surrounded,
        })
    out.sort(key=lambda c: -c["size"])
    return out


def segment_nasal_v5(vol, cfg=None, verbose=True):
    nz, ny, nx = vol.shape
    C = {
        "hu_air_max": -300,
        "x_center": nx // 2,
        "x_tol": 70,
        "min_size": 150,
        "max_size": 12000,
        "min_surrounded": 0.75,
        "ring_pad": 5,
        "reject_edge": True,
        # 连续性约束
        "max_centroid_jump": 25,     # 相邻层质心最大漂移（像素）
        "max_area_ratio": 2.5,       # 相邻层面积最大变化比
        "min_run_length": 8,         # 最短连续段长度（层数）
    }
    if cfg:
        C.update(cfg)

    air = vol < C["hu_air_max"]

    # ---- 阶段1：逐层候选 ----
    layer_cands = {}
    for z in range(nz):
        layer_cands[z] = segment_layer_candidates(air[z], C)

    # ---- 阶段2：选取"主候选"形成轨迹 ----
    # 策略：从鼻腔最明确的中段层出发，向上下追踪
    # 先找"面积稳定"的层作为锚点
    sizes = {z: (layer_cands[z][0]["size"] if layer_cands[z] else 0)
             for z in range(nz)}

    # 找连续范围内 size 最稳定的区间
    zs_with = [z for z in range(nz) if layer_cands[z]]
    if not zs_with:
        return {"mask": np.zeros_like(air), "diagnostics": {"error": "no candidates"}}

    # 锚点层：候选存在且面积在合理鼻腔范围
    anchor_candidates = [z for z in zs_with
                         if C["min_size"] * 2 <= sizes[z] <= C["max_size"]]
    if not anchor_candidates:
        anchor_candidates = zs_with

    # 从最大面积层出发做双向追踪
    z_anchor = max(anchor_candidates, key=lambda z: sizes[z])

    selected = {}      # z -> candidate dict
    selected[z_anchor] = layer_cands[z_anchor][0]

    # 向上追踪 (z 增大)
    prev = selected[z_anchor]
    for z in range(z_anchor + 1, nz):
        if not layer_cands[z]:
            prev = None
            continue
        best, best_score = None, 1e9
        for c in layer_cands[z]:
            if prev is None:
                score = abs(c["size"] - sizes[z_anchor])
            else:
                d_cent = np.hypot(c["cx"] - prev["cx"], c["cy"] - prev["cy"])
                if d_cent > C["max_centroid_jump"]:
                    continue
                ratio = max(c["size"], prev["size"]) / max(1, min(c["size"], prev["size"]))
                if ratio > C["max_area_ratio"]:
                    continue
                score = d_cent + abs(c["size"] - prev["size"]) * 0.01
            if score < best_score:
                best, best_score = c, score
        if best is not None:
            selected[z] = best
            prev = best
        else:
            prev = None

    # 向下追踪 (z 减小)
    prev = selected[z_anchor]
    for z in range(z_anchor - 1, -1, -1):
        if not layer_cands[z]:
            prev = None
            continue
        best, best_score = None, 1e9
        for c in layer_cands[z]:
            if prev is None:
                score = abs(c["size"] - sizes[z_anchor])
            else:
                d_cent = np.hypot(c["cx"] - prev["cx"], c["cy"] - prev["cy"])
                if d_cent > C["max_centroid_jump"]:
                    continue
                ratio = max(c["size"], prev["size"]) / max(1, min(c["size"], prev["size"]))
                if ratio > C["max_area_ratio"]:
                    continue
                score = d_cent + abs(c["size"] - prev["size"]) * 0.01
            if score < best_score:
                best, best_score = c, score
        if best is not None:
            selected[z] = best
            prev = best
        else:
            prev = None

    # ---- 阶段3：构建掩膜 ----
    mask3d = np.zeros_like(air)
    for z, c in selected.items():
        mask3d[z] = c["mask"]

    # ---- 阶段4：3D 连通性过滤（去掉孤立小块） ----
    lbl3, n3 = ndimage.label(mask3d, structure=np.ones((3, 3, 3)))
    if n3 > 0:
        s3 = ndimage.sum(mask3d, lbl3, range(1, n3 + 1))
        keep = int(np.argmax(s3)) + 1
        main = lbl3 == keep
        n_before = int(mask3d.sum())
        mask3d = main
        diag_drop = n_before - int(main.sum())
    else:
        diag_drop = 0

    diag = {
        "params": C,
        "anchor_z": z_anchor,
        "anchor_size": sizes[z_anchor],
        "layers_selected": len(selected),
        "z_range_selected": [min(selected), max(selected)] if selected else None,
        "total_voxels": int(mask3d.sum()),
        "dropped_by_connectivity": int(diag_drop),
    }

    if verbose:
        print("=== v5 分割诊断 ===")
        print(f"锚点层 z={z_anchor} (size={sizes[z_anchor]:,})")
        print(f"选中层数: {len(selected)}")
        print(f"选中 z 范围: {diag['z_range_selected']}")
        print(f"总掩膜体素: {diag['total_voxels']:,}")
        print(f"\n{'z':>5} {'size':>8} {'cx':>7} {'cy':>7} {'surr':>6}")
        for z in sorted(selected):
            c = selected[z]
            print(f"{z:>5} {c['size']:>8,} {c['cx']:>7.1f} {c['cy']:>7.1f} {c['surrounded']:>6.3f}")

    return {"mask": mask3d, "selected": selected, "diagnostics": diag}


if __name__ == "__main__":
    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape}\n")

    res = segment_nasal_v5(vol)
    outdir = r"D:\项目\鼻腔建模\work\02_segment"
    os.makedirs(outdir, exist_ok=True)
    np.save(os.path.join(outdir, "nasal_mask_v5.npy"), res["mask"])
    with open(os.path.join(outdir, "seg_v5_diag.json"), "w", encoding="utf-8") as f:
        json.dump(res["diagnostics"], f, ensure_ascii=False, indent=2)

    from segment_v2 import render_mask_check
    z_list = [120, 140, 160, 180, 200, 220, 240, 260, 280, 300]
    grid, tiles = render_mask_check(vol, res["mask"], outdir, z_list=z_list, prefix="v5")
    print(f"\n=== 渲染 ===")
    for z, fn, n in tiles:
        print(f"  z={z}: {n:,} 体素")
    print(f"  拼图 -> {grid}")
