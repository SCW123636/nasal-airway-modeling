# -*- coding: utf-8 -*-
"""渲染 v8 结果：主连通域叠加图"""
import os, sys, json
import numpy as np
from scipy import ndimage
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct
from segment_v8 import segment_nasal_v8

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
res = segment_nasal_v8(vol, verbose=False)

lbl3 = res["labels3"]
n3 = res["n3"]
sizes3 = ndimage.sum(res["raw"], lbl3, range(1, n3 + 1))
main_lab = int(np.argmax(sizes3)) + 1
mask = lbl3 == main_lab
print(f"主连通域 lab={main_lab} 体素={int(mask.sum()):,}")

# 形态分析
zz, yy, xx = np.where(mask)
print(f"z {zz.min()}-{zz.max()}  y {yy.min()}-{yy.max()}  x {xx.min()}-{xx.max()}")
print(f"质心 x={xx.mean():.1f}")
# 左右分开统计
left = mask.copy(); right = mask.copy()
left[:, :, 256:] = False
right[:, :, :256] = False
print(f"中线左(x<256): {int(left.sum()):,}  中线右(x>=256): {int(right.sum()):,}")

outdir = r"D:\项目\鼻腔建模\work\02_segment"
os.makedirs(outdir, exist_ok=True)

# 渲染
z_list = [130, 145, 160, 175, 190, 205, 220, 235]
tiles = []
for z in z_list:
    u8 = window_ct(vol[z], 800, 2000)
    rgb = np.stack([u8, u8, u8], axis=-1).copy()
    m = mask[z]
    rgb[m] = [255, 50, 50]
    fn = os.path.join(outdir, f"v8_z{z:04d}.png")
    Image.fromarray(rgb).save(fn)
    tiles.append((z, fn, int(m.sum())))

imgs = [np.array(Image.open(f)) for _, f, _ in tiles]
cols, rows = 4, 2
h, w = imgs[0].shape[:2]
sc = 0.5
h2, w2 = int(h*sc), int(w*sc)
canvas = np.zeros((rows*h2, cols*w2, 3), dtype=np.uint8)
for i, im in enumerate(imgs):
    r, c = divmod(i, cols)
    canvas[r*h2:(r+1)*h2, c*w2:(c+1)*w2] = np.array(Image.fromarray(im).resize((w2, h2)))
grid = os.path.join(outdir, "v8_grid.png")
Image.fromarray(canvas).save(grid)

print(f"\n=== 渲染 ===")
for z, f, n in tiles:
    print(f"  z={z}: {n:,} 体素")
print(f"  拼图 -> {grid}")

np.save(os.path.join(outdir, "nasal_mask_v8.npy"), mask)
