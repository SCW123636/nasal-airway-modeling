# -*- coding: utf-8 -*-
"""
鼻腔气道分割 v4 — 解剖约束逐层筛选（当前最优）
==================================================
判据（三层筛选，全部来自实测解剖）：
  1. **非外部**：不接触图像边缘
  2. **中央性**：形心 x 靠近中线（|cx - 中线| < 阈值）
  3. **被环绕**：bbox 外扩环带中，非空气比例 > 阈值
  4. **合理尺寸**：鼻子通道截面通常 200 ~ 8000 体素

输出：逐层累积的 3D 掩膜
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series


def segment_layer(mask2d, cfg):
    """单层分割，返回 (选中掩膜, 候选详情)"""
    ny, nx = mask2d.shape
    XC = cfg["x_center"]
    lbl, n = ndimage.label(mask2d, structure=np.ones((3, 3)))

    selected = np.zeros_like(mask2d)
    cands = []

    for lab in range(1, n + 1):
        m = lbl == lab
        size = int(m.sum())
        if size < cfg["min_size"] or size > cfg["max_size"]:
            continue
        ys, xs = np.where(m)
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())

        # 判据1：不接触边缘
        if cfg["reject_edge"] and (y0 == 0 or y1 == ny - 1 or x0 == 0 or x1 == nx - 1):
            continue

        cx = float(xs.mean())
        # 判据2：中央性
        if abs(cx - XC) > cfg["x_tol"]:
            continue

        # 判据3：被环绕度
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

        # 通过
        selected |= m
        cands.append({
            "label": lab, "size": size,
            "y": [y0, y1], "x": [x0, x1],
            "cx": round(cx, 1), "surrounded": round(surrounded, 3),
        })

    return selected, cands


def segment_nasal_v4(vol, cfg=None, verbose=True):
    nz, ny, nx = vol.shape
    C = {
        "hu_air_max": -300,
        "x_center": nx // 2,
        "x_tol": 70,              # 形心距中线最大距离
        "min_size": 150,          # 最小截面
        "max_size": 12000,        # 最大截面（排除鼻窦巨型腔）
        "min_surrounded": 0.75,   # 最小环绕度
        "ring_pad": 5,
        "reject_edge": True,
    }
    if cfg:
        C.update(cfg)

    air = vol < C["hu_air_max"]
    mask3d = np.zeros_like(air)
    all_cands = {}
    n_selected_layers = 0

    for z in range(nz):
        sel, cands = segment_layer(air[z], C)
        if sel.any():
            mask3d[z] = sel
            n_selected_layers += 1
        all_cands[z] = cands

    diag = {
        "params": C,
        "layers_with_selection": n_selected_layers,
        "total_voxels": int(mask3d.sum()),
    }

    if verbose:
        print("=== v4 分割诊断 ===")
        print(f"参数: {json.dumps(C, ensure_ascii=False)}")
        print(f"有选中的层数: {n_selected_layers}/{nz}")
        print(f"总掩膜体素: {diag['total_voxels']:,}")
        print(f"\n{'z':>5} {'候选数':>6} {'体素':>8}  候选详情")
        for z in range(0, nz, 20):
            cs = all_cands[z]
            tot = sum(c["size"] for c in cs)
            det = " ".join(f"sz{c['size']}@x{c['cx']:.0f}" for c in cs[:4])
            print(f"{z:>5} {len(cs):>6} {tot:>8,}  {det}")

    return {"mask": mask3d, "cands": all_cands, "diagnostics": diag}


if __name__ == "__main__":
    from nasal_io import load_dicom_series
    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape}\n")

    res = segment_nasal_v4(vol)
    outdir = r"D:\项目\鼻腔建模\work\02_segment"
    os.makedirs(outdir, exist_ok=True)
    np.save(os.path.join(outdir, "nasal_mask_v4.npy"), res["mask"])

    # 渲染
    from segment_v2 import render_mask_check
    z_list = [120, 140, 160, 180, 200, 220, 240, 260, 280, 300]
    grid, tiles = render_mask_check(vol, res["mask"], outdir, z_list=z_list, prefix="v4")
    print(f"\n=== 渲染 ===")
    for z, fn, n in tiles:
        print(f"  z={z}: {n:,} 体素")
    print(f"  拼图 -> {grid}")
