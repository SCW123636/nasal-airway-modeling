# -*- coding: utf-8 -*-
"""对三例做解剖复核：逐层统计"类鼻腔"结构（中线附近 + 双侧对称）的出现区间，
与 calib_multi 的自动锚点对比，判断自动锚点是否落在鼻腔上。

判据（比面积导数更贴近解剖）：
  1. x 方向在图像中线 ±60 体素内
  2. 该层掩膜须呈"左右各一团"（左右半区各有 >=50 体素的连通体）
  3. 层面积 >= 阈值
"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dicom_sitk import load_series_sitk
from PIL import Image
from nasal_io import window_ct

ROOT = r"D:\项目\鼻腔建模"
CLEAN = os.path.join(ROOT, "资料", "脱敏数据_clean")
OUT = os.path.join(ROOT, "work", "03_calib", "multi")
os.makedirs(OUT, exist_ok=True)

CASES = [
    ("患者1", r"患者1\______-______\20260127\202-1.0 x 0.8 Bone"),
    ("患者2", r"患者2\p01360058-____\20250902-Head^07_Sinus (Adult)\4-Sinus  0.75  H40s"),
    ("患者3", r"患者3\250111559-TKT\20260217-5.___\202-0.6 x 0.6_BONE"),
]


def analyze(name, rel):
    d = os.path.join(CLEAN, rel)
    vol, sp, org, meta = load_series_sitk(d)
    nz, ny, nx = vol.shape
    dx, dy, dz = sp
    air = vol < -300

    outside = np.zeros_like(air)
    for z in range(nz):
        a = air[z]
        if not a.any():
            continue
        lbl, n = ndimage.label(a, structure=np.ones((3, 3)))
        if n == 0:
            continue
        el = set(lbl[0, :]) | set(lbl[-1, :]) | set(lbl[:, 0]) | set(lbl[:, -1])
        el.discard(0)
        if el:
            outside[z] = np.isin(lbl, list(el))
    inside = air & (~outside)

    # 全局中线：所有层 inside 的 x 中位
    zz, yy, xx = np.where(inside)
    x_mid = float(np.median(xx)) if len(xx) else nx / 2

    rows = []
    for z in range(nz):
        m = inside[z]
        n = int(m.sum())
        rec = {"z": z, "n": n, "bilateral": False, "n_side": 0,
               "n_center": 0, "x_span": 0}
        if n:
            ys, xs = np.where(m)
            rec["x_span"] = int(xs.max() - xs.min() + 1)
            # 中线附近
            cen = m[:, max(0, int(x_mid) - 60):min(nx, int(x_mid) + 60)]
            rec["n_center"] = int(cen.sum())
            # 左右各一团
            left = m[:, :int(x_mid)]
            right = m[:, int(x_mid):]
            ll, nl = ndimage.label(left, structure=np.ones((3, 3)))
            rl, nr = ndimage.label(right, structure=np.ones((3, 3)))
            sl = max([int((ll == i).sum()) for i in range(1, nl + 1)], default=0)
            sr = max([int((rl == i).sum()) for i in range(1, nr + 1)], default=0)
            rec["bilateral"] = (sl >= 50 and sr >= 50)
            rec["n_side"] = min(sl, sr)
        rows.append(rec)

    # 找"双侧鼻腔"连续区间（宽限：允许中间有少量断点）
    bil = np.array([r["bilateral"] for r in rows])
    # 连续段
    segs = []
    s = None
    for i, b in enumerate(bil):
        if b and s is None:
            s = i
        elif not b and s is not None:
            if i - s >= 3:
                segs.append((s, i - 1))
            s = None
    if s is not None and len(bil) - s >= 3:
        segs.append((s, len(bil) - 1))
    # 取最长段
    segs_span = [(a, b) for a, b in segs]
    best = max(segs_span, key=lambda ab: ab[1] - ab[0]) if segs_span else None

    res = {
        "patient": name, "series": meta["series_description"],
        "dz": dz, "nz": nz, "x_mid": round(x_mid, 1),
        "bilateral_segments": segs_span,
        "longest_bilateral": best,
        "longest_span_mm": round((best[1] - best[0]) * dz, 2) if best else None,
    }
    return res, vol, inside, outside, x_mid, dz, org


summary = []
for name, rel in CASES:
    r, vol, inside, outside, x_mid, dz, org = analyze(name, rel)
    summary.append(r)
    print(f"== {r['patient']} {r['series']}  dz={dz:.3f} x_mid={r['x_mid']}")
    print(f"   双侧鼻腔连续段 (z): {r['bilateral_segments']}")
    print(f"   最长段: {r['longest_bilateral']}  跨度={r['longest_span_mm']} mm")

    # 渲染最长段的前中后三层
    if r["longest_bilateral"]:
        a, b = r["longest_bilateral"]
        zs = [max(0, a - 6), a, (a + b) // 2, b, min(len(inside) - 1, b + 6)]
        tiles = []
        for z in zs:
            u8 = window_ct(vol[z], 800, 2000)
            rgb = np.stack([u8] * 3, axis=-1).copy()
            rgb[outside[z]] = [70, 120, 235]
            rgb[inside[z]] = [255, 80, 80]
            # 中线
            xm = int(x_mid)
            if 0 <= xm < rgb.shape[1]:
                rgb[:, max(0, xm - 1):xm + 1] = [255, 255, 0]
            tiles.append(rgb)
        h, w = tiles[0].shape[:2]
        sc = 0.55
        h2, w2 = int(h * sc), int(w * sc)
        canvas = np.zeros((h2, len(tiles) * w2, 3), dtype=np.uint8)
        for i, t in enumerate(tiles):
            canvas[:, i * w2:(i + 1) * w2] = np.array(Image.fromarray(t).resize((w2, h2)))
        Image.fromarray(canvas).save(os.path.join(OUT, f"bilateral_{name}.png"))
        print(f"   -> bilateral_{name}.png  层 {zs}")

with open(os.path.join(OUT, "bilateral_check.json"), "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print("\ndone")
