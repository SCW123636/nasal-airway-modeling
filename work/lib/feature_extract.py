# -*- coding: utf-8 -*-
"""鼻腔 vs 口腔/鼻窦 的判别特征提取（诊断用，先量化再判）。

上一轮教训：仅"中线附近 + 左右两团"会同时命中口腔与上颌窦。
本脚本提取每层的多个形态特征，输出 CSV，供人工/规则联合判定，
不预设结论。

特征：
  n           该层 inside 体素数
  n_center    中线 ±50 体素内的体素数
  x_span      x 跨度
  ncomp       连通分量数
  septum_gap  中线带（±8）内是否为空洞（鼻腔被鼻中隔分开 → 中线无空气）
  bilateral   左右两侧是否各有一团 >= 80 体素
  ant_y       质心 y（前=大）；鼻腔偏前
  top2_ratio  最大两分量占全层比（鼻腔段高）
"""
import os, sys, json, csv
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dicom_sitk import load_series_sitk

ROOT = r"D:\项目\鼻腔建模"
CLEAN = os.path.join(ROOT, "资料", "脱敏数据_clean")
OUT = os.path.join(ROOT, "work", "03_calib", "multi")

CASES = [
    ("患者1", r"患者1\______-______\20260127\202-1.0 x 0.8 Bone"),
    ("患者2", r"患者2\p01360058-____\20250902-Head^07_Sinus (Adult)\4-Sinus  0.75  H40s"),
    ("患者3", r"患者3\250111559-TKT\20260217-5.___\202-0.6 x 0.6_BONE"),
]

FEATS = ["z", "mm_z", "n", "n_center", "x_span", "ncomp", "septum_air",
         "bilateral", "cx", "cy", "top2_ratio", "n_center_frac"]


def feats_one(name, rel):
    d = os.path.join(CLEAN, rel)
    vol, sp, org, meta = load_series_sitk(d)
    nz, ny, nx = vol.shape
    dx, dy, dz = sp
    air = vol < -300

    outside = np.zeros_like(air)
    for z in range(nz):
        a = air[z]
        if not a.any():
            continue
        lbl, n = ndimage.label(a, structure=np.ones((3, 3)))
        if n == 0:
            continue
        el = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
        el.discard(0)
        if el:
            outside[z] = np.isin(lbl, list(el))
    inside = air & (~outside)

    zz, yy, xx = np.where(inside)
    x_mid = int(round(float(np.median(xx)))) if len(xx) else nx // 2

    rows = []
    for z in range(nz):
        m = inside[z]
        n = int(m.sum())
        rec = {k: None for k in FEATS}
        rec.update({"z": z, "mm_z": round(float(org[2] + z * dz), 2), "n": n})
        if n == 0:
            rows.append(rec)
            continue
        ys, xs = np.where(m)
        rec["x_span"] = int(xs.max() - xs.min() + 1)
        rec["cx"] = round(float(xs.mean()), 1)
        rec["cy"] = round(float(ys.mean()), 1)
        lbl, nc = ndimage.label(m, structure=np.ones((3, 3)))
        rec["ncomp"] = int(nc)
        sizes = sorted([int((lbl == i).sum()) for i in range(1, nc + 1)], reverse=True)
        rec["top2_ratio"] = round(sum(sizes[:2]) / n, 3) if n else None
        # 中线带
        lo, hi = max(0, x_mid - 50), min(nx, x_mid + 50)
        rec["n_center"] = int(m[:, lo:hi].sum())
        rec["n_center_frac"] = round(rec["n_center"] / n, 3)
        # 鼻中隔带 ±8：该带内空气量（鼻腔=少，口腔=可能多）
        lo2, hi2 = max(0, x_mid - 8), min(nx, x_mid + 8)
        rec["septum_air"] = int(m[:, lo2:hi2].sum())
        # 左右各一团
        left = m[:, :x_mid]
        right = m[:, x_mid:]
        ll, nl = ndimage.label(left, structure=np.ones((3, 3)))
        rl, nr = ndimage.label(right, structure=np.ones((3, 3)))
        sl = max([int((ll == i).sum()) for i in range(1, nl + 1)], default=0)
        sr = max([int((rl == i).sum()) for i in range(1, nr + 1)], default=0)
        rec["bilateral"] = int(sl >= 80 and sr >= 80)
        rows.append(rec)

    p = os.path.join(OUT, f"features_{name}.csv")
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FEATS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FEATS})
    return p, x_mid, dz, meta


for name, rel in CASES:
    p, x_mid, dz, meta = feats_one(name, rel)
    print(f"{name}: x_mid={x_mid} dz={dz:.3f} -> {p}")
print("done")
