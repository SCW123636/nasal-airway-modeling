# -*- coding: utf-8 -*-
"""
鼻腔解剖锚点标定 v2 —— 用"是否被组织包围"区分鼻腔 vs 体外空气
================================================================
v1 失败教训：
  只用"空气面积/导数"无法区分鼻腔与体外空气——两者在 ROI 框内都表现为空气。
  v1 把 z=0 的体外空气平台误判为鼻孔入口。

v2 核心判据（这才是真正区分鼻腔与体外的物理事实）：
  【体外空气】与图像边界连通，可以从边缘一路 flood fill 到。
  【鼻腔空气】被皮肤/骨/软组织包围，从图像边缘 flood fill 无法到达。

  做法：
    1. 从 512x512 每一层的图像四边做 flood fill（对"空气"做），
       得到"体外空气"掩膜。
    2. 空气 - 体外空气 = 体内空气（鼻腔+鼻窦+咽部+...）。
    3. 在体内空气中，鼻腔的体现为：z 剖面上升沿 + x 靠近中线。

用法：PythonSlicer.exe calib_v2.py
"""
import os, sys, json, csv
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image

ROOT = r"D:\项目\鼻腔建模"
DICOM = os.path.join(ROOT, "work", "00_dicom", "bone")
OUT = os.path.join(ROOT, "work", "03_calib")
os.makedirs(OUT, exist_ok=True)

for cand in ["Microsoft YaHei", "SimHei", "DejaVu Sans"]:
    if any(cand.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [cand]
        break
plt.rcParams["axes.unicode_minus"] = False

vol, sp, org, meta = load_dicom_series(DICOM, verbose=False)
nz, ny, nx = vol.shape
dx, dy, dz = sp
air = vol < -300
print(f"体积 {vol.shape}  air 总占比 {air.mean():.3f}")

# ============ 核心：体外空气 = 从图像边缘 flood fill 可达的空气 ============
outside = np.zeros_like(air)
for z in range(nz):
    a = air[z]
    if not a.any():
        continue
    # 从四边种子的连通域
    lbl, n = ndimage.label(a, structure=np.ones((3, 3)))
    edge_labels = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
    edge_labels.discard(0)
    if edge_labels:
        outside[z] = np.isin(lbl, list(edge_labels))

inside = air & (~outside)
print(f"体外空气 {int(outside.sum()):,}  体内空气 {int(inside.sum()):,}")

# ============ 逐层统计 inside ============
rows = []
for z in range(nz):
    m = inside[z]
    n = int(m.sum())
    if n == 0:
        rows.append({"z": z, "n": 0, "x_min": -1, "x_max": -1, "x_span": 0,
                     "cx": -1.0, "ncomp": 0})
        continue
    ys, xs = np.where(m)
    lbl, nc = ndimage.label(m, structure=np.ones((3, 3)))
    rows.append({"z": z, "n": n, "x_min": int(xs.min()), "x_max": int(xs.max()),
                 "x_span": int(xs.max() - xs.min() + 1),
                 "cx": round(float(xs.mean()), 2), "ncomp": int(nc)})

prof = np.array([r["n"] for r in rows], dtype=float)
cx = np.array([r["cx"] for r in rows], dtype=float)

def smooth(a, k=9):
    if len(a) < k:
        return a
    return np.convolve(a, np.ones(k) / k, mode="same")

ps = smooth(prof, 9)
dps = np.gradient(ps)

nz_any = np.where(prof > 0)[0]
z_lo, z_hi = int(nz_any.min()), int(nz_any.max())
print(f"体内空气 z 范围: {z_lo} .. {z_hi}  (峰值 {prof.max():,.0f} @z={int(prof.argmax())})")

# ---- 找鼻腔起点：上升沿，但排除 z_lo 附近的起始伪影 ----
# 策略：在 z_lo+15 之后找最强上升沿
search_from = z_lo + 15
i_rise = search_from + int(np.argmax(dps[search_from:]))
i = i_rise
while i > search_from and dps[i] > 0:
    i -= 1
z_nostril = i
z_peak = int(z_nostril + np.argmax(ps[z_nostril:]))
# 鼻咽过渡 = 峰值后最强下降沿
i_fall = z_peak + int(np.argmin(dps[z_peak:]))
# 最宽 = 鼻腔区间内 x_span 最大
span = np.array([r["x_span"] for r in rows], dtype=float)
z_widest = int(z_nostril + np.argmax(span[z_nostril:z_peak + 1]))

print(f"拐点: 上升沿 z={z_nostril}  峰值 z={z_peak}  "
      f"鼻咽最强下降 z={i_fall}  最宽 z={z_widest}")
print(f"→ 鼻腔区间估计 z ∈ [{z_nostril}, {i_fall}]，跨度 "
      f"{(i_fall - z_nostril) * dz:.2f} mm")

# ---- 画图 ----
fig, axes = plt.subplots(3, 1, figsize=(13, 10), dpi=110, sharex=True)
ax = axes[0]
ax.plot(np.arange(nz), prof, lw=1.0, color="#1f77b4", label="体内空气体素数/层")
ax.plot(np.arange(nz), ps, lw=1.6, color="#ff7f0e", alpha=0.85, label="平滑")
axb = ax.twinx()
axb.plot(np.arange(nz), dps, lw=0.9, color="#999999", alpha=0.7, label="导数")
axb.axhline(0, color="#cccccc", lw=0.6)
axb.set_ylabel("变化率", color="#888888")
for z, lab, c in [(z_nostril, "鼻孔入口", "#2ca02c"), (z_peak, "鼻腔峰值", "#d62728"),
                  (i_fall, "鼻咽过渡", "#9467bd"), (z_widest, "最宽", "#8c564b")]:
    ax.axvline(z, ls="--", lw=1.3, color=c)
    ax.annotate(f"{lab}\nz={z}", xy=(z, ps[z]), xytext=(10, 14),
                textcoords="offset points", fontsize=9, color=c,
                arrowprops=dict(arrowstyle="->", color=c, lw=0.9))
ax.set_ylabel("体内空气体素数/层")
ax.set_title("体内空气（排除体外）沿 z 剖面 —— 这才是鼻腔的真实信号")
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)

axes[1].plot(np.arange(nz), span, lw=1.2, color="#2ca02c")
axes[1].axvline(z_widest, ls="--", lw=1.3, color="#8c564b")
axes[1].set_ylabel("x 跨度 (体素)")
axes[1].grid(alpha=0.3)

v = prof > 0
axes[2].plot(np.arange(nz)[v], cx[v], lw=1.2, color="#d62728")
med = np.median(cx[z_nostril:z_peak + 1])
axes[2].axhline(med, ls=":", color="gray", label=f"鼻腔段中位 cx={med:.1f}")
axes[2].set_xlabel("z 层索引")
axes[2].set_ylabel("质心 x")
axes[2].legend(fontsize=9)
axes[2].grid(alpha=0.3)
for a in axes:
    a.set_xlim(max(0, z_lo - 15), min(nz, z_hi + 15))

p = os.path.join(OUT, "area_profile_inside.png")
fig.tight_layout()
fig.savefig(p)
plt.close(fig)
print(f"剖面图 -> {p}")

# ---- CSV ----
pc = os.path.join(OUT, "layer_profile_inside.csv")
with open(pc, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"逐层表 -> {pc}")

# ---- landmarks ----
lm = {
    "source": {"dicom": DICOM, "shape": list(vol.shape),
               "spacing_xyz_mm": [dx, dy, dz], "origin_ipp_first": list(org)},
    "method": "体内空气(排除边缘连通) + 面积导数拐点",
    "anchors": {
        "z_nostril_entry": {"z": int(z_nostril),
                            "mm_z": round(org[2] + z_nostril * dz, 3),
                            "meaning": "鼻腔起始（面积上升沿起点）"},
        "z_nasal_peak": {"z": int(z_peak),
                         "mm_z": round(org[2] + z_peak * dz, 3),
                         "meaning": "鼻腔横截面积最大层"},
        "z_nasopharynx": {"z": int(i_fall),
                          "mm_z": round(org[2] + i_fall * dz, 3),
                          "meaning": "鼻咽过渡（最强下降沿）"},
        "z_widest": {"z": int(z_widest),
                     "mm_z": round(org[2] + z_widest * dz, 3),
                     "meaning": "鼻腔段 x 跨度最大层"},
        "x_center_nasal": {"x": int(round(med))},
    },
    "nasal_span_mm": round((i_fall - z_nostril) * dz, 2),
    "status": "自动推定，需人工目视确认",
}
pj = os.path.join(OUT, "landmarks.json")
with open(pj, "w", encoding="utf-8") as f:
    json.dump(lm, f, ensure_ascii=False, indent=2)
print(f"锚点 -> {pj}")

# ---- 渲染：三层对比（CT + 体外 + 体内） ----
zs = sorted(set([max(0, z_nostril - 20), z_nostril, z_nostril + 20,
                 (z_nostril + z_peak) // 2, z_peak,
                 z_peak + 20, i_fall, min(nz - 1, i_fall + 20)]))
zs = [z for z in zs if 0 <= z < nz]
tiles = []
for z in zs:
    u8 = window_ct(vol[z], 800, 2000)
    rgb = np.stack([u8] * 3, axis=-1).copy()
    rgb[outside[z]] = [90, 140, 255]     # 体外空气 = 蓝
    rgb[inside[z]] = [255, 90, 90]       # 体内空气 = 红
    tiles.append((z, rgb))
h, w = tiles[0][1].shape[:2]
sc = 0.5
h2, w2 = int(h * sc), int(w * sc)
cols = 4
rws = (len(tiles) + cols - 1) // cols
canvas = np.zeros((rws * h2, cols * w2, 3), dtype=np.uint8)
for i, (z, t) in enumerate(tiles):
    r, c = divmod(i, cols)
    # 层号标注：左上角画一个小色块
    canvas[r*h2:(r+1)*h2, c*w2:(c+1)*w2] = np.array(
        Image.fromarray(t).resize((w2, h2)))
pg = os.path.join(OUT, "inside_vs_outside.png")
Image.fromarray(canvas).save(pg)
print(f"体内/体外对比 -> {pg}  (层: {zs})")

print("\n=== 锚点 ===")
for k, vv in lm["anchors"].items():
    print(f"  {k}: {vv}")
print(f"鼻腔跨度: {lm['nasal_span_mm']} mm")
