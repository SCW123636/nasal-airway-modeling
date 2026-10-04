# -*- coding: utf-8 -*-
"""
分析 lab=1（主连通域）的形态，判断它包含哪些解剖结构
"""
import os, sys
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape
air = vol < -300

XC = 256
x_lo, x_hi = XC - 100, XC + 100
sub = air[:, :, x_lo:x_hi]
lbl, n = ndimage.label(sub, structure=np.ones((3, 3, 3)))
main = (lbl == 1)   # 900万体素那一块

print(f"lab=1 体素: {main.sum():,}")
print(f"占全空气比例: {main.sum()/air.sum()*100:.1f}%")
print(f"占柱体比例: {main.sum()/sub.sum()*100:.1f}%")

# ============ 逐层分析 lab=1 的形状 ============
print("\n=== lab=1 逐层形态（每10层） ===")
print(f"{'z':>5} {'体素':>8} {'x范围':>14} {'y范围':>14} {'x跨度':>6} {'y跨度':>6}  说明")
for z in range(0, nz, 10):
    sl = main[z]
    n_air = int(sl.sum())
    if n_air == 0:
        continue
    ys, xs = np.where(sl)
    x_span = xs.max() - xs.min()
    y_span = ys.max() - ys.min()
    desc = ""
    if x_span > 150: desc += "横向极宽(外部?)"
    elif y_span > 200: desc += "纵向极长(通道?)"
    print(f"{z:>5} {n_air:>8,} {xs.min()+x_lo:>6}-{xs.max()+x_lo:<6} "
          f"{ys.min():>6}-{ys.max():<6} {x_span:>6} {y_span:>6}  {desc}")

# ============ 关键：lab=1 在鼻尖前方是否占满整个图像？ ============
print("\n=== 判断标准：鼻腔 vs 外部空气 ===")
print("外部空气特征：占据图像边缘、面积巨大、形状不规则")
print("鼻腔特征：被组织包围、位于中央、截面面积适中(几百~几千像素)")

print(f"\n{'z':>5} {'lab1像素':>9} {'整层空气':>9} {'占比':>7} {'x边界接触':>10} {'判定':>12}")
for z in range(100, 260, 10):
    m = main[z]
    a = air[z]
    n_m = int(m.sum())
    n_a = int(a.sum())
    if n_a == 0: continue
    ratio = n_m / n_a
    xs = np.where(m.any(axis=0))[0]
    touch_left = xs.min() <= x_lo + 2
    touch_right = xs.max() >= x_hi - 3
    verdict = "外部/混杂" if (ratio > 0.7 or touch_left or touch_right) else "鼻腔候选"
    print(f"{z:>5} {n_m:>9,} {n_a:>9,} {ratio*100:>6.1f}% "
          f"{'左' if touch_left else '-'}{'右' if touch_right else '-':>4} {verdict:>12}")

# ============ 尝试分割：把 lab=1 中"位于中央被包围的"部分分离 ============
print("\n=== 形态学分离尝试 ===")
# 思路：鼻腔截面 = lab=1 中，与图像边缘不连通的部分
# 方法：对每层做"孔洞填充"，鼻腔是被骨包围的孔洞
from scipy.ndimage import binary_fill_holes

print("方法A：孔洞填充（鼻腔=被组织包围的孔洞）")
filled = binary_fill_holes(air)     # 填充所有内部孔洞
holes = filled & ~air                # 孔洞 = 应该填但没填的
print(f"  孔洞体素（=被包围的空腔）: {holes.sum():,}")

# 真正的鼻腔应该在 holes 里！
lbl_h, n_h = ndimage.label(holes, structure=np.ones((3,3,3)))
sizes_h = ndimage.sum(holes, lbl_h, range(1, n_h+1))
order_h = np.argsort(-sizes_h)
print(f"\n  孔洞连通域数: {n_h}")
print(f"  前15大孔洞:")
for i, idx in enumerate(order_h[:15]):
    lab = int(idx)+1
    m = lbl_h == lab
    zz, yy, xx = np.where(m)
    print(f"    [{i:>2}] lab={lab:>5} 体素={int(sizes_h[idx]):>9,}  "
          f"z {zz.min():>3}-{zz.max():<3} y {yy.min():>3}-{yy.max():<3} x {xx.min():>3}-{xx.max():<3}")
