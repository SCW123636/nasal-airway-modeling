# -*- coding: utf-8 -*-
"""
解剖定位：自动找出鼻腔主气道区域
核心思路：鼻腔是「被骨壁包围 + 与外部通过鼻孔连通 + 向下通鼻咽」的空气腔
"""
import os, sys
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct
from PIL import Image

OUT = r"D:\项目\鼻腔建模\work\01_inspect"
os.makedirs(OUT, exist_ok=True)

BONE_DIR = r"D:\项目\鼻腔建模\work\00_dicom\bone"

vol, spacing, origin, meta = load_dicom_series(BONE_DIR)
nz, ny, nx = vol.shape
print(f"\n体积 {vol.shape}, 间距 {spacing}")

# ---------- 1. 空气掩膜 ----------
air = vol < -300
print(f"空气体素: {air.sum():,} ({air.mean()*100:.1f}%)")

# ---------- 2. 每层分析，找鼻腔层范围 ----------
print("\n=== 逐层空气占比 (每 20 层采样) ===")
print(f"{'z':>5} {'空气像素':>10} {'占比':>7}  连通域数")
rows = []
for z in range(0, nz, 20):
    sl = air[z]
    n_air = int(sl.sum())
    lbl, n_cc = ndimage.label(sl, structure=np.ones((3, 3)))
    # 最大连通域大小
    if n_cc > 0:
        sizes = ndimage.sum(sl, lbl, range(1, n_cc + 1))
        biggest = int(sizes.max())
    else:
        biggest = 0
    rows.append((z, n_air, n_air / sl.size, n_cc, biggest))
    print(f"{z:>5} {n_air:>10,} {n_air/sl.size*100:>6.1f}%  {n_cc:>4}  最大块={biggest:,}")

# ---------- 3. 3D 连通域分析：找最大的内部空气腔 ----------
print("\n=== 3D 连通域分析 ===")
# 先做形态学清理（去噪）
air_clean = ndimage.binary_opening(air, structure=np.ones((2, 2, 2)))
print(f"形态学清理后空气: {air_clean.sum():,}")

lbl3d, n3d = ndimage.label(air_clean, structure=np.ones((3, 3, 3)))
print(f"3D 连通域数: {n3d}")

sizes3d = ndimage.sum(air_clean, lbl3d, range(1, n3d + 1))
order = np.argsort(-sizes3d)
print("\n前 12 大连通域:")
print(f"{'rank':>5} {'label':>7} {'体素':>12} {'bbox(z0,z1,y0,y1,x0,x1)':>40}")
top_regions = []
for r, idx in enumerate(order[:12]):
    lab = int(idx) + 1
    mask = lbl3d == lab
    zz, yy, xx = np.where(mask)
    bbox = (int(zz.min()), int(zz.max()), int(yy.min()), int(yy.max()),
            int(xx.min()), int(xx.max()))
    top_regions.append({"label": lab, "size": int(sizes3d[idx]), "bbox": bbox})
    print(f"{r+1:>5} {lab:>7} {int(sizes3d[idx]):>12,}   {bbox}")

# ---------- 4. 关键判据：哪个连通域穿过"鼻孔"区域 ----------
# 鼻孔在扫描的前方（y 最小侧，因为 ImagePositionPatient y = -261 是前）
# 鼻咽在后方（y 最大）
print("\n=== 连通域的解剖特征 ===")
for reg in top_regions[:8]:
    lab = reg["label"]
    mask = lbl3d == lab
    zz, yy, xx = np.where(mask)
    print(f"\n[lab={lab}] 体素={reg['size']:,}")
    print(f"   z 范围 {zz.min()}~{zz.max()}  (跨度 {zz.max()-zz.min()})")
    print(f"   y 范围 {yy.min()}~{yy.max()}  (跨度 {yy.max()-yy.min()})")
    print(f"   x 范围 {xx.min()}~{xx.max()}  (跨度 {xx.max()-xx.min()})")
    # 是否接触扫描边界
    touches = []
    if zz.min() == 0: touches.append("z=0")
    if zz.max() == nz-1: touches.append("z=max")
    if yy.min() == 0: touches.append("y=0")
    if yy.max() == ny-1: touches.append("y=max")
    if xx.min() == 0: touches.append("x=0")
    if xx.max() == nx-1: touches.append("x=max")
    print(f"   接触边界: {touches if touches else '无（封闭腔体）'}")

# ---------- 5. 骨骼体积分布（定位解剖标志） ----------
bone = vol > 300
print("\n=== 骨骼(z向分布, 每20层) ===")
for z in range(0, nz, 20):
    b = int(bone[z].sum())
    bar = "#" * int(b / 500)
    print(f"  z={z:>4} {b:>7,} {bar}")

np.save(os.path.join(OUT, "air_mask.npy"), air)
print(f"\n已保存 air_mask.npy")
