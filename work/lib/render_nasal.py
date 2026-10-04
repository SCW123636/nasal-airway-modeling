# -*- coding: utf-8 -*-
"""渲染鼻腔关键区间切片，含空气掩膜叠加"""
import os, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct

OUT = r"D:\项目\鼻腔建模\work\01_inspect"
BONE_DIR = r"D:\项目\鼻腔建模\work\00_dicom\bone"

vol, spacing, origin, meta = load_dicom_series(BONE_DIR, verbose=False)
nz, ny, nx = vol.shape
print(f"体积 {vol.shape}  间距 {spacing}  origin {origin}")

# 鼻腔区间：骨骼在 z=140~220 最密，鼻腔主体应在其中
Z_RANGE = [140, 160, 170, 180, 190, 200, 210, 220]

print("\n=== 渲染鼻腔区轴位切片 ===")
tiles = []
for z in Z_RANGE:
    sl = vol[z]
    u8 = window_ct(sl, 800, 2000)
    # 叠加空气掩膜（红色调）
    air = sl < -300
    rgb = np.stack([u8, u8, u8], axis=-1).copy()
    # 空气区域染青蓝色 (B 高, R 低)，便于识别
    rgb[air, 0] = (u8[air] * 0.25).astype(np.uint8)
    rgb[air, 1] = (u8[air] * 0.55).astype(np.uint8)
    rgb[air, 2] = np.clip(u8[air].astype(np.int16) + 70, 0, 255).astype(np.uint8)
    fn = os.path.join(OUT, f"nasal_axial_z{z:04d}.png")
    Image.fromarray(rgb).save(fn)
    tiles.append((z, fn))
    print(f"  z={z:>4} 空气={int(air.sum()):>7,}  -> {os.path.basename(fn)}")

# 拼成一张大图便于观察
print("\n=== 拼图 ===")
imgs = [np.array(Image.open(fn)) for _, fn in tiles]
# 4x2 网格
cols, rows = 4, 2
h, w = imgs[0].shape[:2]
scale = 0.45
h2, w2 = int(h * scale), int(w * scale)
canvas = np.zeros((rows * h2, cols * w2, 3), dtype=np.uint8)
for i, im in enumerate(imgs):
    r, c = divmod(i, cols)
    pil = Image.fromarray(im).resize((w2, h2))
    canvas[r*h2:(r+1)*h2, c*w2:(c+1)*w2] = np.array(pil)
grid_fn = os.path.join(OUT, "nasal_axial_grid.png")
Image.fromarray(canvas).save(grid_fn)
print(f"  -> {grid_fn} ({os.path.getsize(grid_fn)} bytes)")

# 矢状位中央切片（看鼻腔前后走向）
print("\n=== 渲染矢状位 ===")
for x in [230, 250, 270, 290]:
    sl = vol[:, :, x]
    u8 = window_ct(sl, 800, 2000)
    fn = os.path.join(OUT, f"nasal_sagittal_x{x:04d}.png")
    Image.fromarray(u8).save(fn)
    print(f"  x={x} -> {os.path.basename(fn)}")

# 冠状位（看左右鼻道）
print("\n=== 渲染冠状位 ===")
for y in [180, 210, 240, 270]:
    sl = vol[:, y, :]
    u8 = window_ct(sl, 800, 2000)
    fn = os.path.join(OUT, f"nasal_coronal_y{y:04d}.png")
    Image.fromarray(u8).save(fn)
    print(f"  y={y} -> {os.path.basename(fn)}")
