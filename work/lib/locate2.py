# -*- coding: utf-8 -*-
"""
精确定位：鼻中隔两侧的鼻腔通道
"""
import os, sys
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape
air = vol < -300

print("=== 逐点扫描：找鼻腔内部空气点 ===")
print("在 z=140~200, y=100~180 网格上扫描，找远离图像边界(x>100 且 x<412)的空气点")
print(f"{'z':>5} {'y':>5} {'x范围':>16} {'空气段(仅x∈[100,412])':>40}")

found = []
for z in range(140, 210, 10):
    for y in range(100, 190, 10):
        row = air[z, y, 100:412]
        xs = np.where(row)[0] + 100
        if len(xs) < 3:
            continue
        groups = []
        s = xs[0]; p = xs[0]
        for x in xs[1:]:
            if x - p > 2:
                groups.append((s, p)); s = x
            p = x
        groups.append((s, p))
        gs = " ".join(f"{a}-{b}({b-a+1})" for a, b in groups)
        if groups:
            print(f"{z:>5} {y:>5} {'':>16} {gs}")
            for a, b in groups:
                found.append((z, y, (a + b) // 2, b - a + 1))

print(f"\n找到 {len(found)} 个候选空气段")

# 统计：x 位置上哪些是真鼻道（宽度 3-40 且靠近中央 x=200-312）
central = [f for f in found if 190 <= f[2] <= 320 and 2 <= f[3] <= 60]
print(f"其中靠近中央的候选: {len(central)}")
for f in central[:30]:
    print(f"   z={f[0]} y={f[1]} x={f[2]} 宽={f[3]}")

# ============ 关键测试：从中央点做 3D 连通域 ============
print("\n=== 3D 连通域测试（限定在中央柱体 |x-256|<100） ===")
XC = 256
x_lo, x_hi = XC - 100, XC + 100
sub = air[:, :, x_lo:x_hi]
lbl, n = ndimage.label(sub, structure=np.ones((3, 3, 3)))
print(f"柱体内连通域数: {n}")

sizes = ndimage.sum(sub, lbl, range(1, n + 1))
order = np.argsort(-sizes)
print(f"\n前10大连通域:")
for i, idx in enumerate(order[:10]):
    lab = int(idx) + 1
    m = lbl == lab
    zz, yy, xx = np.where(m)
    print(f"  [{i}] lab={lab} 体素={int(sizes[idx]):>10,}")
    print(f"       z {zz.min()}-{zz.max()}  y {yy.min()}-{yy.max()}  "
          f"x {xx.min()+x_lo}-{xx.max()+x_lo}")

# ============ 检查该连通域是否连到图像外部 ============
print("\n=== 边界接触检查（判断是否与外部空气连通） ===")
for i, idx in enumerate(order[:5]):
    lab = int(idx) + 1
    m = lbl == lab
    zz, yy, xx = np.where(m)
    t = []
    if yy.min() == 0: t.append("y=0(前/外)")
    if yy.max() == ny-1: t.append("y=max(后)")
    if zz.min() == 0: t.append("z=0(下)")
    if zz.max() == nz-1: t.append("z=max(上)")
    print(f"  lab={lab}: {t if t else '封闭'}")
