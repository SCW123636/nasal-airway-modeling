# -*- coding: utf-8 -*-
"""
鼻腔分割 v3 — 逐层几何法
================================================
核心洞察（来自实测剖面）：
  鼻腔在每一层轴位图上的特征：
  1. 位于图像中央（x 中线附近）
  2. 被组织/骨**环绕**（前方、后方、外侧都有组织）
  3. 与外部空气**不直接相邻**（除了鼻孔层）
  4. 鼻窦虽然也是空腔，但位置更靠外侧（上颌窦）或更靠上（额窦/筛窦）

方法：
  逐层做「连通域 + 几何筛选」：
    - 每个空气连通域，检查它的**包围度**（bounding box 内的非空气比例）
    - 检查它是否**接触图像边缘**
    - 检查它**是否靠近中线**
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasal_io import load_dicom_series

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape
air = vol < -300
XC = nx // 2

print(f"体积 {vol.shape}  中线 x={XC}")


def analyze_layer(mask2d):
    """分析一层的所有空气连通域，返回特征列表"""
    lbl, n = ndimage.label(mask2d, structure=np.ones((3, 3)))
    out = []
    for lab in range(1, n + 1):
        m = lbl == lab
        size = int(m.sum())
        if size < 20:
            continue
        ys, xs = np.where(m)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        # bounding box 包围度
        bbox_area = (y1 - y0 + 1) * (x1 - x0 + 1)
        fill_ratio = size / bbox_area
        # 是否接触图像边缘
        touch_edge = (y0 == 0 or y1 == ny - 1 or x0 == 0 or x1 == nx - 1)
        # 形心
        cy, cx = ys.mean(), xs.mean()
        out.append({
            "label": lab, "size": size,
            "y": (int(y0), int(y1)), "x": (int(x0), int(x1)),
            "fill_ratio": float(fill_ratio),
            "touch_edge": bool(touch_edge),
            "centroid": (float(cy), float(cx)),
            "x_span": int(x1 - x0), "y_span": int(y1 - y0),
        })
    return out


print("\n=== 逐层特征（每 20 层） ===")
for z in range(100, 300, 20):
    feats = analyze_layer(air[z])
    # 按尺寸排序
    feats.sort(key=lambda f: -f["size"])
    print(f"\n--- z={z} ---  共 {len(feats)} 个连通域")
    print(f"  {'sz':>7} {'y范围':>12} {'x范围':>12} {'填充':>6} {'接触边':>6} {'形心x':>7} {'判定':>12}")
    for f in feats[:8]:
        # 判定规则
        v = "?"
        if f["touch_edge"]:
            v = "外部"
        elif f["fill_ratio"] < 0.45:
            v = "分支状(鼻甲?)"
        elif abs(f["centroid"][1] - XC) < 60 and f["size"] > 100:
            v = "中央腔"
        print(f"  {f['size']:>7,} {str(f['y']):>12} {str(f['x']):>12} "
              f"{f['fill_ratio']:>6.2f} {'是' if f['touch_edge'] else '否':>6} "
              f"{f['centroid'][1]:>7.0f} {v:>12}")

# ============ 关键：找出"被组织环绕"的中央腔 ============
print("\n\n=== 核心判据测试：被环绕度 ===")
print("对每个中央连通域，统计其 bbox 外扩 5 像素后的环带中，非空气比例")
print("鼻腔：环带几乎全是组织/骨（比例高）")
print("外部空气：环带接触图像边缘（比例低）")

z_test = 170
feats = analyze_layer(air[z_test])
feats.sort(key=lambda f: -f["size"])

for f in feats[:6]:
    y0, y1 = f["y"]; x0, x1 = f["x"]
    pad = 6
    Y0, Y1 = max(0, y0 - pad), min(ny, y1 + pad + 1)
    X0, X1 = max(0, x0 - pad), min(nx, x1 + pad + 1)
    ring = np.ones((Y1 - Y0, X1 - X0), dtype=bool)
    # 挖掉内部
    ring[y0 - Y0:y1 - Y0 + 1, x0 - X0:x1 - X0 + 1] = False
    n_ring = int(ring.sum())
    n_ring_air = int((air[z_test][Y0:Y1, X0:X1] & ring).sum())
    surrounded = 1 - (n_ring_air / n_ring) if n_ring else 0
    print(f"\n  size={f['size']:,} y={f['y']} x={f['x']}")
    print(f"     环带像素={n_ring} 环带中空气={n_ring_air}  → 环绕度={surrounded:.3f} "
          f"{'(被包围 ✓)' if surrounded > 0.9 else '(连到外部 ✗)'}")
