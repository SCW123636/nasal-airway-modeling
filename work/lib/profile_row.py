# -*- coding: utf-8 -*-
"""打印具体行的完整 HU 值，看清解剖边界"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape

# 取 z=170（鼻腔明显层），y=150（中段）
for z, y in [(170, 150), (170, 120), (170, 180), (140, 150)]:
    row = vol[z, y]
    print(f"\n{'='*70}")
    print(f"z={z} y={y}  x 剖面 HU 值 (每4像素采样)")
    print(f"{'='*70}")
    for x in range(140, 380, 4):
        v = int(row[x])
        # 分类标记
        if v < -900: mark = "空"      # 深空气
        elif v < -300: mark = "·"     # 空气
        elif v < 100: mark = "软"     # 软组织
        elif v < 300: mark = "组"     # 组织
        else: mark = "骨"             # 骨
        bar = ""
        if v >= 300:
            bar = "#" * min(int(v/200), 30)
        print(f"  x={x:>3} HU={v:>6} {mark} {bar}")

# 打印一行连续的，看边界细节
print(f"\n{'='*70}")
print("z=170 y=150 连续 x 从 180 到 340")
print(f"{'='*70}")
row = vol[170, 150]
line = ""
for x in range(180, 340):
    v = int(row[x])
    if v < -300: line += "."
    elif v < 100: line += "s"
    elif v < 300: line += "t"
    else: line += "#"
print("x=180" + " " * 40 + "x=340")
print(line)
print("\n图例: . = 空气(< -300HU)  s = 软组织(-300~100)  t = 组织(100~300)  # = 骨(>300)")
