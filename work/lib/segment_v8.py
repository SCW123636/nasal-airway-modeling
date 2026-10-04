# -*- coding: utf-8 -*-
"""
鼻腔气道自动分割 v8 — 逐层形态判据 + 3D 连通筛选（修正 v6 追踪 bug）
====================================================================
v6 的教训：逐层追踪的 side/jump 判定太脆弱，一旦断链就失败。
v8 方案：**不做追踪**。对每一层独立应用形态判据，收集所有"像鼻腔"的腔，
         然后用 3D 连通性把噪声剔除。

形态判据（v6 已验证有效）：
  - 中央性：|cx - XC| < x_tol
  - 低填充率：fill < max_fill（鼻腔细长）
  - 长宽比：aspect > min_aspect
  - 尺寸范围：[min_size, max_size]

关键修正：
  1. 不用追踪；逐层独立判定
  2. 3D 连通后，保留与"鼻腔主体"连通的成分
  3. 左右鼻腔分别处理（按 cx 相对中线）
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series


def layer_candidates(mask2d, cfg):
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
        if y0 == 0 or y1 == ny - 1 or x0 == 0 or x1 == nx - 1:
            continue
        cx, cy = float(xs.mean()), float(ys.mean())
        if abs(cx - XC) > cfg["x_tol"]:
            continue
        bbox = (y1 - y0 + 1) * (x1 - x0 + 1)
        fill = size / bbox
        if fill > cfg["max_fill"]:
            continue
        w, h = x1 - x0 + 1, y1 - y0 + 1
        aspect = max(w, h) / max(1, min(w, h))
        if aspect < cfg["min_aspect"]:
            continue
        out.append({"lab": lab, "mask": m, "size": size,
                    "cx": cx, "cy": cy, "y": (y0, y1), "x": (x0, x1),
                    "fill": float(fill), "aspect": float(aspect)})
    out.sort(key=lambda c: -c["size"])
    return out


def segment_nasal_v8(vol, cfg=None, verbose=True, render=False):
    nz, ny, nx = vol.shape
    XC = nx // 2
    C = {
        "hu_air_max": -300,
        "x_center": XC,
        "x_tol": 60,
        "min_size": 120,
        "max_size": 9000,
        "max_fill": 0.52,
        "min_aspect": 1.2,
        # 每层最多保留几个候选（左右各一）
        "per_layer_max": 4,
    }
    if cfg:
        C.update(cfg)

    air = vol < C["hu_air_max"]

    # ---- 逐层独立判定 ----
    per_layer = {}
    total_cand = 0
    for z in range(nz):
        cs = layer_candidates(air[z], C)[:C["per_layer_max"]]
        per_layer[z] = cs
        total_cand += len(cs)

    if verbose:
        print(f"=== v8 诊断 ===")
        print(f"总候选数（所有层）: {total_cand}")
        print(f"\n{'z':>5} {'候选':>4}  详情")
        for z in range(120, 300, 10):
            cs = per_layer[z]
            det = " | ".join(f"sz{c['size']}x{c['cx']:.0f}f{c['fill']:.2f}a{c['aspect']:.1f}"
                             for c in cs[:4])
            print(f"{z:>5} {len(cs):>4}  {det}")

    # ---- 构建逐层掩膜（保留所有候选，靠 3D 连通性筛选） ----
    raw = np.zeros_like(air)
    for z, cs in per_layer.items():
        for c in cs:
            raw[z] |= c["mask"]

    # ---- 3D 连通性分析 ----
    lbl3, n3 = ndimage.label(raw, structure=np.ones((3, 3, 3)))
    sizes3 = ndimage.sum(raw, lbl3, range(1, n3 + 1)) if n3 else np.array([])
    order = np.argsort(-sizes3) if n3 else []

    if verbose:
        print(f"\n=== 3D 连通域（共 {n3}） ===")
        print(f"{'#':>3} {'lab':>6} {'体素':>9} {'z范围':>12} {'y范围':>14} {'x范围':>14} {'质心x':>7}")
        comps = []
        for i, idx in enumerate(order[:20]):
            lab = int(idx) + 1
            m = lbl3 == lab
            zz, yy, xx = np.where(m)
            comps.append({
                "label": lab, "size": int(sizes3[idx]),
                "z": (int(zz.min()), int(zz.max())),
                "y": (int(yy.min()), int(yy.max())),
                "x": (int(xx.min()), int(xx.max())),
                "cx": float(xx.mean()),
            })
            print(f"{i:>3} {lab:>6} {int(sizes3[idx]):>9,} "
                  f"{str((int(zz.min()),int(zz.max()))):>12} "
                  f"{str((int(yy.min()),int(yy.max()))):>14} "
                  f"{str((int(xx.min()),int(xx.max()))):>14} {xx.mean():>7.1f}")

    return {"raw": raw, "per_layer": per_layer, "labels3": lbl3, "n3": n3,
            "comps": comps if verbose else [], "params": C}


if __name__ == "__main__":
    vol, sp, org, meta = load_dicom_series(
        r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
    print(f"体积 {vol.shape}\n")
    res = segment_nasal_v8(vol, render=True)
