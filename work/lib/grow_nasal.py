# -*- coding: utf-8 -*-
"""
【DEPRECATED · 已停用】区域增长法提取鼻腔（原 step 3 矩形护栏方案）

废弃裁定（2026-10-01）：
  纯几何 / 矩形护栏路线经三例交叉验证证伪——无法分离鼻腔与口腔 / 上颌窦 / 筛窦；
  对称比≥0.7、bbox 跨度 50–70 mm、面积导数定鼻孔入口均不能作为鼻腔正确性判据。
  项目改走「专家在环的解剖先验分割」：TotalSegmentator head_glands_cavities 初分割
  → 人在环修正（Slicer Grow from Seeds）→ 多标签几何 → CFD（见 work/分割流程规范.md）。

本文件保留仅供追溯，运行即退出，不再作为主流程。
"""
_DEPRECATED = True  # 矩形护栏方案已停用；改 False 可临时恢复（不推荐）
if _DEPRECATED:
    import sys
    sys.stderr.write("[grow_nasal] DEPRECATED: 矩形护栏方案已停用，见 work/分割流程规范.md\n")
    sys.exit(0)

import os, json
import numpy as np
from scipy import ndimage
from PIL import Image

OUT = r"C:\nasal_probe"
arr = np.load(os.path.join(OUT, "vol_zyx.npy"))
nz, ny, nx = arr.shape
rep = {"shape": [nz, ny, nx], "steps": []}


def log(s):
    rep["steps"].append(str(s))
    print(s)


air = (arr > -1100) & (arr < -300)

# ---------- A. 定位鼻中隔与鼻孔 ----------
# 用骨（HU>300）在正中矢状面附近找连续的竖直薄板
bone = arr > 300

# 逐 z 扫，找 x 方向上最靠近 nx/2 的骨性中线
mid_x = nx // 2  # 256
z_lo, z_hi = 120, 240
mid_scores = []
for z in range(z_lo, z_hi):
    row = bone[z, :, :]
    # 中线附近 ±20 的骨占比
    cnt = int(row[:, mid_x - 20:mid_x + 20].sum())
    mid_scores.append((z, cnt))
rep["midline_bone_count"] = mid_scores
log(f"中线骨量（z=120..240）前5: {sorted(mid_scores, key=lambda t:-t[1])[:5]}")

# 鼻中隔最厚处 z
z_septum = max(mid_scores, key=lambda t: t[1])[0]
log(f"z_septum(鼻中隔最厚)={z_septum}")

# ---------- B. 找鼻孔：y 方向的空气「颈缩」 ----------
# 在 z=z_septum 附近，逐 y 统计中线附近空气沿 z 的贯通高度
air_band = []
for y in range(0, ny):
    col = air[:, y, mid_x - 45:mid_x + 45]
    air_band.append(int(col.sum()))
air_band = np.array(air_band)
rep["air_band_by_y"] = air_band.tolist()

# 鼻腔段应是 air_band 的高原；鼻孔在高原的前端（y 大侧）
peak = float(air_band[60:260].max())
thr = peak * 0.35
plateau = np.where(air_band > thr)[0]
log(f"air_band peak={peak:.0f} thr={thr:.0f} plateau y=[{plateau.min()},{plateau.max()}]")

# ---------- C. 种子点 ----------
# 已知解剖锚点（经上一轮 anatomy_locate 实测，z大=上, y大=前）
# 鼻腔本部大致 z=150~215, y=200~330, |x-256|<50
seed_cands = []
for z in range(155, 216, 10):
    for dx in (-32, -22, 22, 32):
        x = mid_x + dx
        for y in (240, 270, 300):
            if air[z, y, x]:
                seed_cands.append((z, y, x))
log(f"seed candidates={len(seed_cands)}")
rep["seed_candidates"] = seed_cands

# 用第一个有效种子做生长（逐个尝试，取最大结果）
best = None
for (sz, sy, sx) in seed_cands:
    seed = np.zeros_like(air)
    seed[sz, sy, sx] = True
    grew = ndimage.binary_propagation(seed, mask=air)
    n = int(grew.sum())
    if best is None or n > best[0]:
        best = (n, (sz, sy, sx), grew)
    log(f"  seed {(sz,sy,sx)} -> grow {n}")

n_raw, seed_pt, grew_raw = best
log(f"BEST seed={seed_pt} raw_grow={n_raw}")
np.save(os.path.join(OUT, "grow_raw.npy"), grew_raw)

# ---------- D. 加护栏生长 ----------
sz, sy, sx = seed_pt
guard = np.zeros_like(air)
XMIN, XMAX = mid_x - 58, mid_x + 58      # ±20mm
ZMIN, ZMAX = 128, 232
YMIN, YMAX = 168, 345                    # 鼻孔后 到 鼻咽前
guard[ZMIN:ZMAX, YMIN:YMAX, XMIN:XMAX] = True
air_g = air & guard
seed = np.zeros_like(air)
seed[sz, sy, sx] = True
grew_g = ndimage.binary_propagation(seed, mask=air_g)
n_g = int(grew_g.sum())
log(f"guarded_grow={n_g}  ratio_to_raw={n_g/max(n_raw,1):.3f}")
np.save(os.path.join(OUT, "grow_guarded.npy"), grew_g)

# 形态学清理
clean = ndimage.binary_opening(grew_g, np.ones((2, 2, 2), bool))
lab, nlab = ndimage.label(clean)
if nlab > 0:
    sizes = ndimage.sum(clean, lab, range(1, nlab + 1)).astype(np.int64)
    keep = int(np.argmax(sizes) + 1)
    clean = lab == keep
log(f"after clean={int(clean.sum())} (nlab={nlab})")
np.save(os.path.join(OUT, "grow_clean.npy"), clean)

idx = np.where(clean)
rep["clean_bbox"] = {"z": [int(idx[0].min()), int(idx[0].max())],
                     "y": [int(idx[1].min()), int(idx[1].max())],
                     "x": [int(idx[2].min()), int(idx[2].max())]}
log(f"clean bbox={rep['clean_bbox']}")
# 左右对称性
left = int(clean[:, :, mid_x + 1:].sum())
right = int(clean[:, :, :mid_x].sum())
rep["left"], rep["right"] = left, right
rep["symmetry_ratio"] = round(min(left, right) / max(left, right, 1), 3)
log(f"L={left} R={right} sym={rep['symmetry_ratio']}")

# ---------- 可视化 ----------
def win(sl):
    lo, hi = -500, 1500
    return (np.clip((sl.astype(np.float32) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


def ov(plane_img, plane_mask, color):
    u8 = win(plane_img)
    rgb = np.stack([u8, u8, u8], -1)
    rgb[plane_mask] = color
    return rgb


for z in (140, 155, 170, 185, 200, 215):
    img = ov(arr[z], clean[z], [255, 60, 60])
    Image.fromarray(img).save(os.path.join(OUT, f"grow_axi_z{z}.png"))
for x in (225, 240, 256, 272, 288):
    img = ov(arr[:, :, x], clean[:, :, x], [255, 60, 60])
    Image.fromarray(img).resize((ny * 2, nz * 2), Image.NEAREST).save(
        os.path.join(OUT, f"grow_sag_x{x}.png"))
for y in (200, 250, 300, 340):
    img = ov(arr[:, y, :], clean[:, y, :], [255, 60, 60])
    Image.fromarray(img).resize((nx * 2, nz * 2), Image.NEAREST).save(
        os.path.join(OUT, f"grow_cor_y{y}.png"))

rep["ok"] = True
with open(os.path.join(OUT, "grow_report.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
log("DONE")
