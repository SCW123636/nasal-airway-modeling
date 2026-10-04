# -*- coding: utf-8 -*-
"""
定位鼻孔平面：找到鼻腔通道与外部空气相连的"咽喉要道"
方法：对每一层，找出"被骨/软组织夹住的中线空气通道"
"""
import os, sys
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape
print(f"体积 {vol.shape}  间距 {sp}")
print(f"origin = {org}")

air = vol < -300
body = ~air

# ============ A. 逐层分析中线附近的空气通道 ============
print("\n=== A. 中线附近(y方向)空气通道剖面 ===")
print("原理：鼻腔在中央，看 x∈[中线±60] 范围内，每一行 y 有多少空气")
print(f"{'z':>5} {'中线空气列数':>12} {'空气y范围':>16} {'前界y':>8} {'后界y':>8}")

x_center = nx // 2
half = 55

for z in range(100, 260, 10):
    strip = air[z, :, x_center-half:x_center+half]   # (ny, 110)
    rows_with_air = strip.sum(axis=1)
    ys = np.where(rows_with_air > 3)[0]
    if len(ys) == 0:
        print(f"{z:>5} {'无':>12}")
        continue
    # 分组连续区间
    groups = []
    start = ys[0]
    prev = ys[0]
    for y in ys[1:]:
        if y - prev > 3:
            groups.append((start, prev))
            start = y
        prev = y
    groups.append((start, prev))
    gstr = " ".join(f"[{a}-{b}]" for a, b in groups[:6])
    print(f"{z:>5} {len(ys):>12} {gstr:>20}")

# ============ B. 鼻尖与鼻孔 ============
print("\n=== B. 面部轮廓前缘（找鼻尖） ===")
print(f"{'z':>5} {'body前缘y':>10} 描述")
prev_front = None
for z in range(80, 250, 10):
    ys = np.where(body[z].any(axis=1))[0]
    if len(ys) == 0:
        print(f"{z:>5} {'-':>10} 无body")
        continue
    front = ys.min()
    desc = ""
    if prev_front is not None:
        d = front - prev_front
        if d < -2:
            desc = f"<- 前突 {d}"
        elif d > 2:
            desc = f"-> 后缩 +{d}"
    print(f"{z:>5} {front:>10} {desc}")
    prev_front = front

# ============ C. 骨密度分布，定位骨性鼻道 ============
print("\n=== C. 关键层的中线横截面（x 剖面，看骨壁位置） ===")
bone = vol > 300
for z in [140, 160, 180, 200]:
    # 取该层中线附近 y 剖面
    print(f"\n--- z={z} ---")
    # 找该层"骨包围的空腔"：对每行 y，看 x 方向上骨-空气-骨的模式
    for y in range(60, 200, 20):
        row_air = air[z, y, :]
        row_bone = bone[z, y, :]
        n_air = row_air.sum()
        n_bone = row_bone.sum()
        # 找空气段的 x 位置
        if n_air > 5:
            xs = np.where(row_air)[0]
            groups = []
            start = xs[0]; prev = xs[0]
            for x in xs[1:]:
                if x - prev > 2:
                    groups.append((start, prev)); start = x
                prev = x
            groups.append((start, prev))
            gs = " ".join(f"{a}-{b}" for a, b in groups[:5])
            print(f"  y={y:>3}: 空气{n_air:>4} 骨{n_bone:>4}  空气段[{gs}]")

# ============ D. 尝试：从"内部"往外做区域生长 ============
print("\n=== D. 区域生长测试（从中央鼻腔内部出发） ===")
# 选一个明确的鼻腔内部点：z=160, y=120（中段前方）, x=中线
test_points = [(160, 130, 256), (170, 140, 256), (180, 150, 256), (150, 120, 256)]
print("测试点是否为空气:", [bool(air[p]) for p in test_points])

# 从鼻腔内部点，限制在 |x-256| < 90 的柱体内做连通
for (z0, y0, x0) in test_points:
    if not air[z0, y0, x0]:
        print(f"  点({z0},{y0},{x0}) 不是空气，跳过")
        continue
    # 限定柱体
    sub = air[:, :, max(0, x0-90):min(nx, x0+90)]
    lbl, n = ndimage.label(sub, structure=np.ones((3,3,3)))
    lab = lbl[z0, y0, x0 - max(0, x0-90)]
    if lab == 0:
        print(f"  点({z0},{y0},{x0}) 连通域=0")
        continue
    size = int((lbl == lab).sum())
    zz, yy, xx = np.where(lbl == lab)
    print(f"  点({z0},{y0},{x0}): 柱体内连通域={lab} 体素={size:,}")
    print(f"      z范围 {zz.min()}-{zz.max()}  y范围 {yy.min()}-{yy.max()}  x范围 {xx.min()+x0-90}-{xx.max()+x0-90}")
