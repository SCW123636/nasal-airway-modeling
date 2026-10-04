# -*- coding: utf-8 -*-
"""
确认解剖方位：哪边是上（头顶）、哪边是前（面部）
用矢状位剖面判断
"""
import os, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series, window_ct

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape
print(f"体积 {vol.shape}  间距 {sp}")
print(f"origin = {org}")
print(f"origin 含义: ImagePositionPatient[0] 是 z 向起点 = {org[2]}")

# ImagePositionPatient 坐标系约定：
# 对于标准轴位 CT: IOP = [1,0,0, 0,1,0]，其中 x=左右(R/L), y=前后(A/P), z=上下(S/I)
# y 增大方向 = 后（Posterior）；z 增大方向 = 上（Superior）

# 验证：找头顶（最高点 = z 最大处应有颅骨）
print("\n=== 验证 z 方向 ===")
bone = vol > 300
for z in [0, 50, 100, 393]:
    b = int(bone[z].sum())
    a = int((vol[z] < -300).sum())
    print(f"  z={z:>3}: 骨={b:>7,} 空气={a:>7,}")

# 验证 y 方向：鼻尖应该在 y 最小（前）
print("\n=== 验证 y 方向（矢状位中剖面） ===")
x_mid = nx // 2
for y in [50, 100, 150, 200, 250, 300, 350, 400, 450]:
    col = vol[:, y, x_mid]     # (z,)
    body = (col > -300).sum()
    print(f"  y={y:>3}: 非空气体素={body:>3}  (该 y 平面的身体厚度)")

# 渲染矢状位，标注坐标
print("\n=== 渲染带坐标的矢状位 ===")
outdir = r"D:\项目\鼻腔建模\work\01_inspect"
for x in [200, 216, 235, 250, 270]:
    sl = vol[:, :, x]      # (z, y)
    u8 = window_ct(sl, 800, 2000)
    # 转置使 y 在水平、z 在垂直（上=z大）
    u8t = u8[::-1, :]      # 翻转 z 使上方=z大
    img = Image.fromarray(u8t)
    fn = os.path.join(outdir, f"sag_coord_x{x:03d}.png")
    img.save(fn)
    print(f"  x={x} -> {os.path.basename(fn)}  (y 从 0 到 {ny-1} 从左到右, z 从大到小 从上到下)")

# 冠状位
print("\n=== 渲染冠状位 ===")
for y in [150, 200, 250, 300]:
    sl = vol[:, y, :]      # (z, x)
    u8 = window_ct(sl, 800, 2000)
    u8t = u8[::-1, :]
    fn = os.path.join(outdir, f"cor_coord_y{y:03d}.png")
    Image.fromarray(u8t).save(fn)
    print(f"  y={y} -> {os.path.basename(fn)}")
