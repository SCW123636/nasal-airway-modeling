# -*- coding: utf-8 -*-
"""
鼻腔解剖锚点标定 —— 用"面积剖面"定位解剖平面
================================================
核心思想：
  在 394 层里靠肉眼翻找"鼻孔在哪一层"是不可靠的。
  但鼻腔横截面积沿 z 的变化有明确的解剖含义，剖面上的拐点就是解剖平面。

  本脚本输出：
    - 面积剖面图（含拐点标注）
    - 逐层面积/质心/宽度 表格 CSV
    - landmarks.json（解剖锚点，可被后续切割脚本消费）

用法：PythonSlicer.exe calib_profile.py
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = r"D:\项目\鼻腔建模"
DICOM = os.path.join(ROOT, "work", "00_dicom", "bone")
OUT = os.path.join(ROOT, "work", "03_calib")
os.makedirs(OUT, exist_ok=True)

# 中文字体（找不到就退回英文，不报错）
for cand in ["Microsoft YaHei", "SimHei", "DejaVu Sans"]:
    if any(cand.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [cand]
        break
plt.rcParams["axes.unicode_minus"] = False

vol, sp, org, meta = load_dicom_series(DICOM, verbose=False)
nz, ny, nx = vol.shape
dx, dy, dz = sp

# ================= 关键前提：必须先在"鼻腔可能的区域"内工作 =================
# 但这次不用矩形框(会框进体外空气)，改用【解剖驱动的约束】：
#   1. 只在人体头部范围内（排除扫描床）
#   2. 用"该层空气面积"的变化来定位，而不是"最大连通域"
# 先做一个保守 ROI，仅用于剖面统计（x 取鼻腔所在区间）
X_LO, X_HI = 175, 335
air = vol < -300
head = np.zeros_like(air)
head[:, :, X_LO:X_HI + 1] = True
a_roi = air & head

# ---------- 逐层统计 ----------
rows = []
for z in range(nz):
    m = a_roi[z]
    n = int(m.sum())
    if n == 0:
        rows.append({"z": z, "n": 0, "x_min": -1, "x_max": -1,
                     "x_span": 0, "cx": -1.0, "cy": -1.0, "ncomp": 0})
        continue
    ys, xs = np.where(m)
    lbl, nc = ndimage.label(m, structure=np.ones((3, 3)))
    rows.append({"z": z, "n": n,
                 "x_min": int(xs.min()), "x_max": int(xs.max()),
                 "x_span": int(xs.max() - xs.min() + 1),
                 "cx": round(float(xs.mean()), 2), "cy": round(float(ys.mean()), 2),
                 "ncomp": int(nc)})

prof = np.array([r["n"] for r in rows], dtype=float)
span = np.array([r["x_span"] for r in rows], dtype=float)
cx = np.array([r["cx"] for r in rows], dtype=float)

# ---------- 找解剖拐点（用导数定位，不用阈值） ----------
# 教训：z_lo=0 处体外空气已满足"达峰值20%"，阈值法必然失效。
# 正解：鼻腔的出现表现为"面积从平台陡升"，用平滑后的正向导数找陡升段。
nz_any = np.where(prof > 0)[0]
z_lo, z_hi = int(nz_any.min()), int(nz_any.max())
print(f"空气(ROI内) z 范围: {z_lo} .. {z_hi}")

def smooth(a, k=9):
    if len(a) < k:
        return a
    ker = np.ones(k) / k
    return np.convolve(a, ker, mode="same")

ps = smooth(prof, 9)
dps = np.gradient(ps)          # 正向 = 面积上升

# 1) 鼻腔起始 = 前半段最强的上升沿
half = nz // 2
seg = dps[:half]
z_rise = int(np.argmax(seg))
# 上升沿的起点（导数转正处）
i = z_rise
while i > 0 and dps[i] > 0:
    i -= 1
z_nostril = i
# 2) 鼻腔本部峰值 = 上升沿之后的全局最大（排除 z<z_nostril 的平台）
z_peak = int(z_nostril + np.argmax(ps[z_nostril:]))
# 3) 鼻咽过渡 = 峰值之后最强下降沿
seg2 = dps[z_peak:]
z_naso = int(z_peak + np.argmin(seg2))
# 4) 鼻腔最宽：在 [z_nostril, z_naso] 内找 span 最大
sl = slice(z_nostril, z_naso + 1)
z_widest = int(z_nostril + np.argmax(span[sl])) if z_naso > z_nostril else z_nostril

print(f"拐点: 上升沿峰 z={z_rise} → 鼻孔入口 z={z_nostril}  "
      f"鼻腔峰值 z={z_peak}  鼻咽过渡(最强下降) z={z_naso}  最宽 z={z_widest}")

# ---------- 画剖面图 ----------
fig, axes = plt.subplots(3, 1, figsize=(13, 10), dpi=110, sharex=True)
ax = axes[0]
ax.plot(np.arange(nz), prof, lw=1.0, color="#1f77b4", label="ROI内空气体素数")
ax.plot(np.arange(nz), ps, lw=1.6, color="#ff7f0e", alpha=0.8, label="平滑")
ax2 = axes[0].twinx()
ax2.plot(np.arange(nz), dps, lw=0.9, color="#7f7f7f", alpha=0.7, label="导数")
ax2.axhline(0, color="#bbbbbb", lw=0.6)
ax2.set_ylabel("面积变化率", color="#7f7f7f")
ann = [(z_nostril, "鼻孔入口", "#2ca02c"), (z_peak, "鼻腔峰值", "#d62728"),
       (z_naso, "鼻咽过渡", "#9467bd"), (z_widest, "最宽", "#8c564b")]
for z, lab, c in ann:
    ax.axvline(z, ls="--", lw=1.3, color=c)
    ax.annotate(f"{lab}\nz={z}", xy=(z, ps[z]), xytext=(8, 12),
                textcoords="offset points", fontsize=9, color=c,
                arrowprops=dict(arrowstyle="->", color=c, lw=0.9))
ax.set_ylabel("空气体素数 / 层")
ax.set_title("鼻腔横截面积沿 z 的剖面 —— 拐点即解剖平面")
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)

ax = axes[1]
ax.plot(np.arange(nz), span, lw=1.2, color="#2ca02c")
ax.axvline(z_widest, ls="--", lw=1.3, color="#8c564b")
ax.set_ylabel("空气 x 跨度 (体素)")
ax.grid(alpha=0.3)

ax = axes[2]
valid = prof > 0
ax.plot(np.arange(nz)[valid], cx[valid], lw=1.2, color="#d62728")
ax.axhline(np.median(cx[valid]), ls=":", color="gray",
           label=f"中位 cx={np.median(cx[valid]):.1f}")
ax.set_xlabel("z 层索引")
ax.set_ylabel("空气质心 x")
ax.legend(fontsize=9)
ax.grid(alpha=0.3)

for a in axes:
    a.set_xlim(max(0, z_lo - 20), min(nz, z_hi + 20))

p = os.path.join(OUT, "area_profile.png")
fig.tight_layout()
fig.savefig(p)
plt.close(fig)
print(f"\n剖面图 -> {p}")

# ---------- CSV ----------
import csv
pc = os.path.join(OUT, "layer_profile.csv")
with open(pc, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"逐层表 -> {pc}")

# ---------- landmarks ----------
lm = {
    "source": {"dicom": DICOM, "shape": list(vol.shape),
               "spacing_xyz_mm": [dx, dy, dz],
               "origin_ipp_first": list(org)},
    "units": "voxel index (z,y,x);  mm_z = origin_z + z*0.35",
    "anchors": {
        "z_nostril_entry": {"z": int(z_nostril),
                            "mm_z": round(org[2] + z_nostril * dz, 3),
                            "meaning": "鼻孔入口平面（面积首次达峰值20%）"},
        "z_nasal_peak": {"z": int(z_peak),
                         "mm_z": round(org[2] + z_peak * dz, 3),
                         "meaning": "鼻腔横截面积最大层"},
        "z_nasopharynx": {"z": int(z_naso),
                          "mm_z": round(org[2] + z_naso * dz, 3),
                          "meaning": "鼻咽过渡（面积回落至峰值45%）"},
        "z_widest": {"z": int(z_widest),
                     "mm_z": round(org[2] + z_widest * dz, 3),
                     "meaning": "x 跨度最大层"},
        "x_center": {"x": int(round(np.median(cx[valid])))},
        "x_roi": [X_LO, X_HI],
    },
    "status": "自动推定，待人工目视确认后方可作为切割基准",
    "note": "这些锚点是'解剖坐标系'的起点；后续切割应写'距鼻孔平面 X mm'而非硬编码 z",
}
pj = os.path.join(OUT, "landmarks.json")
with open(pj, "w", encoding="utf-8") as f:
    json.dump(lm, f, ensure_ascii=False, indent=2)
print(f"锚点 JSON -> {pj}")

# ---------- 关键层渲染 ----------
from PIL import Image
from nasal_io import window_ct
zs = sorted(set([z_nostril, z_nostril + 25, z_peak - 25, z_peak,
                 z_peak + 25, z_peak + 50, z_naso,
                 min(z_hi, z_naso + 20)]))
zs = [z for z in zs if 0 <= z < nz]
tiles = []
for z in zs:
    u8 = window_ct(vol[z], 800, 2000)
    rgb = np.stack([u8] * 3, axis=-1).copy()
    # 把 ROI 内的空气高亮成青色（这是"候选"，不是"结论"）
    rgb[a_roi[z]] = [0, 220, 220]
    rgb[0:2, :] = [255, 230, 60]
    tiles.append(rgb)
h, w = tiles[0].shape[:2]
sc = 0.5
h2, w2 = int(h * sc), int(w * sc)
cols = 4
rws = (len(tiles) + cols - 1) // cols
canvas = np.zeros((rws * h2, cols * w2, 3), dtype=np.uint8)
for i, t in enumerate(tiles):
    r, c = divmod(i, cols)
    canvas[r*h2:(r+1)*h2, c*w2:(c+1)*w2] = np.array(
        Image.fromarray(t).resize((w2, h2)))
pg = os.path.join(OUT, "anchor_layers.png")
Image.fromarray(canvas).save(pg)
print(f"锚点层渲染 -> {pg}  (层: {zs})")

print("\n=== 解剖锚点 ===")
for k, v in lm["anchors"].items():
    print(f"  {k}: {v}")
