# -*- coding: utf-8 -*-
"""
思路验证：用「内部空洞」法提取鼻腔

原理：
  1. head = ~air 的大连通体（组织+骨，含面部皮肤）
  2. holes = fill_holes(head) & ~head  → 被头包住的全部空腔
     （= 鼻腔 + 鼻窦 + 耳道 + 咽腔 ... 但不含外部空气）
  3. 关键：鼻腔一定满足「上下贯通 + 位于中轴两侧 + 管状细长」
  4. 再叠加 x/z/y 的解剖窗筛选

这个方法天然排除了外部空气（因为外部空气不在 head 内部），
且不需要在鼻孔处"切一刀"。
"""
import os, json
import numpy as np
from scipy import ndimage
from PIL import Image, ImageDraw

OUT = r"C:\nasal_probe"
arr = np.load(os.path.join(OUT, "vol_zyx.npy"))
nz, ny, nx = arr.shape
rep = {"shape": [nz, ny, nx], "steps": []}


def log(s):
    rep["steps"].append(str(s))
    print(s)


air = (arr > -1100) & (arr < -300)
log(f"air={int(air.sum())}")

# ---- 1. 提取头部实心体 ----
solid = ~air
lab_s, ns = ndimage.label(solid)
sizes_s = ndimage.sum(solid, lab_s, range(1, ns + 1)).astype(np.int64)
head_lab = int(np.argmax(sizes_s) + 1)
head = lab_s == head_lab
log(f"n_solid={ns} head_size={int(head.sum())} ({head.mean()*100:.1f}%)")

# ---- 2. 找被头包住的空洞 ----
filled = ndimage.binary_fill_holes(head)
holes = filled & ~head
log(f"holes={int(holes.sum())} ({holes.mean()*100:.2f}%)")
np.save(os.path.join(OUT, "holes.npy"), holes)

lab_h, nh = ndimage.label(holes)
log(f"n_holes={nh}")
sizes_h = ndimage.sum(holes, lab_h, range(1, nh + 1)).astype(np.int64)
order = np.argsort(sizes_h)[::-1][:25]
top = []
for i in order:
    lb = int(i + 1)
    idx = np.where(lab_h == lb)
    top.append({
        "label": lb, "size": int(sizes_h[i]),
        "z": [int(idx[0].min()), int(idx[0].max())],
        "y": [int(idx[1].min()), int(idx[1].max())],
        "x": [int(idx[2].min()), int(idx[2].max())],
        "c": [round(float(idx[0].mean()), 1), round(float(idx[1].mean()), 1),
              round(float(idx[2].mean()), 1)],
    })
rep["top_holes"] = top
for t in top[:12]:
    log(f"  hole L{t['label']} size={t['size']} z={t['z']} y={t['y']} x={t['x']} c={t['c']}")

# ---- 3. 可视化：把 holes 画在矢状位 / 轴位上 ----
def win(sl):
    lo, hi = -500, 1500
    return (np.clip((sl.astype(np.float32) - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


COLORS = [(255, 60, 60), (60, 220, 60), (60, 120, 255), (255, 220, 40),
          (220, 60, 220), (40, 220, 220), (255, 140, 40), (140, 80, 255)]
colmap = {}
for k, t in enumerate(top[:8]):
    colmap[t["label"]] = COLORS[k % len(COLORS)]


def overlay(plane_arr, lab_plane):
    u8 = win(plane_arr)
    rgb = np.stack([u8, u8, u8], -1)
    for lb, col in colmap.items():
        rgb[lab_plane == lb] = col
    return rgb


# 矢状 x=256
x = 256
img = overlay(arr[:, :, x], lab_h[:, :, x])
Image.fromarray(img).resize((ny * 2, nz * 2), Image.NEAREST).save(
    os.path.join(OUT, "holes_sag_x256.png"))
# 矢状 x=230
x = 230
img = overlay(arr[:, :, x], lab_h[:, :, x])
Image.fromarray(img).resize((ny * 2, nz * 2), Image.NEAREST).save(
    os.path.join(OUT, "holes_sag_x230.png"))
# 轴位 z=170
z = 170
img = overlay(arr[z], lab_h[z])
Image.fromarray(img).save(os.path.join(OUT, "holes_axi_z170.png"))
# 轴位 z=150
z = 150
img = overlay(arr[z], lab_h[z])
Image.fromarray(img).save(os.path.join(OUT, "holes_axi_z150.png"))

# 图例
lg = Image.new("RGB", (620, 60 + 26 * len(colmap)), (255, 255, 255))
d = ImageDraw.Draw(lg)
d.text((8, 8), "hole components (size desc)", fill=(0, 0, 0))
for k, t in enumerate(top[:8]):
    y0 = 34 + k * 26
    d.rectangle([10, y0, 30, y0 + 18], fill=colmap[t["label"]])
    d.text((38, y0 + 3), f"L{t['label']}  size={t['size']}  z{t['z']} y{t['y']} x{t['x']}",
           fill=(0, 0, 0))
lg.save(os.path.join(OUT, "holes_legend.png"))

rep["ok"] = True
with open(os.path.join(OUT, "holes_report.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
log("DONE")
