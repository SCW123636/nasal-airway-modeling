# -*- coding: utf-8 -*-
"""
精确解剖标注：在选定层上人工确认左右鼻腔的准确位置
输出放大后的单层图像 + 详细坐标网格
"""
import os, sys
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape
air = vol < -300
outdir = r"D:\项目\鼻腔建模\work\01_inspect"

# 选鼻腔最典型的层
Z = 160
print(f"=== z={Z} 层详细分析 ===")

# 输出该层所有空气连通域，带完整坐标
from scipy import ndimage
lbl, n = ndimage.label(air[Z], structure=np.ones((3,3)))
print(f"连通域数: {n}")
print(f"\n{'lab':>5} {'size':>8} {'y范围':>14} {'x范围':>14} {'cx':>7} {'cy':>7} {'填充':>6} {'接触边'}")
comps = []
for lab in range(1, n+1):
    m = lbl == lab
    size = int(m.sum())
    if size < 50: continue
    ys, xs = np.where(m)
    y0,y1,x0,x1 = int(ys.min()),int(ys.max()),int(xs.min()),int(xs.max())
    bbox = (y1-y0+1)*(x1-x0+1)
    fill = size/bbox
    te = (y0==0 or y1==ny-1 or x0==0 or x1==nx-1)
    comps.append((lab,size,(y0,y1),(x0,x1),xs.mean(),ys.mean(),fill,te))
comps.sort(key=lambda c:-c[1])
for c in comps[:15]:
    print(f"{c[0]:>5} {c[1]:>8,} {str(c[2]):>14} {str(c[3]):>14} {c[4]:>7.1f} {c[5]:>7.1f} {c[6]:>6.2f} {'是' if c[7] else '否'}")

# 渲染放大图 + 网格
u8 = window_ct(vol[Z], 800, 2000)
rgb = np.stack([u8,u8,u8],axis=-1).copy()

# 标出所有大连通域的边界框
for lab,size,(y0,y1),(x0,x1),cx,cy,fill,te in comps[:10]:
    color = [255,80,80] if te else [80,255,120]
    rgb[y0:y0+2, x0:x1] = color
    rgb[y1-1:y1+1, x0:x1] = color
    rgb[y0:y1, x0:x0+2] = color
    rgb[y0:y1, x1-1:x1+1] = color

fn = os.path.join(outdir, f"annotated_z{Z:04d}.png")
Image.fromarray(rgb).save(fn)
print(f"\n标注图 -> {fn}")

# 再渲染一个裁剪放大的中央区域
crop = rgb[100:280, 150:360]
crop_big = np.array(Image.fromarray(crop).resize((crop.shape[1]*3, crop.shape[0]*3), Image.NEAREST))
fn2 = os.path.join(outdir, f"annotated_z{Z:04d}_crop.png")
Image.fromarray(crop_big).save(fn2)
print(f"放大图 -> {fn2}  (裁剪 y[100:280] x[150:360]，放大3倍)")

# ============ 逐行 scna：找鼻腔精确定位 ============
print(f"\n=== z={Z} 逐行空气段 (y=140~200, x 限定 170~270) ===")
for y in range(140, 205, 5):
    row = air[Z, y, 160:280]
    xs = np.where(row)[0] + 160
    if len(xs) == 0:
        print(f"  y={y:>3}: (无空气)")
        continue
    groups = []
    s = xs[0]; p = xs[0]
    for x in xs[1:]:
        if x-p > 2: groups.append((s,p)); s = x
        p = x
    groups.append((s,p))
    gs = "  ".join(f"[{a}-{b}]w{b-a+1}" for a,b in groups)
    print(f"  y={y:>3}: {gs}")
