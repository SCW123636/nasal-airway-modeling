# -*- coding: utf-8 -*-
"""v9 判据失效诊断：逐层列出所有候选连通域（含被拒的），看鼻腔主体被哪条判据拒掉"""
import os, sys, json
import numpy as np
from scipy import ndimage

sys.path.insert(0, r"D:\项目\鼻腔建模\work\lib")
from nasal_io import load_dicom_series

OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\v9_reject_diag.json"

vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
nz, ny, nx = vol.shape
XC = nx // 2

C = {"hu_air_max": -300, "x_center": XC, "x_tol": 58, "min_size": 120,
     "max_size": 8000, "max_fill": 0.42, "min_aspect": 1.4,
     "nasal_x_min": 175, "nasal_x_max": 292}

air = vol < C["hu_air_max"]

# 关键实验：不做 x 硬边界与形态判据，纯连通域，看每层最大的几个空气域长什么样
rows = []
for z in range(125, 240, 5):
    mask2d = air[z]
    lbl, n = ndimage.label(mask2d, structure=np.ones((3, 3)))
    comps = []
    for lab in range(1, n + 1):
        m = lbl == lab
        size = int(m.sum())
        if size < 50:
            continue
        ys, xs = np.where(m)
        y0, y1, x0, x1 = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
        cx, cy = float(xs.mean()), float(ys.mean())
        bbox = (y1 - y0 + 1) * (x1 - x0 + 1)
        fill = size / bbox
        w, h = x1 - x0 + 1, y1 - y0 + 1
        aspect = max(w, h) / max(1, min(w, h))
        edge = (y0 == 0 or y1 == ny - 1 or x0 == 0 or x1 == nx - 1)
        # 判定每条判据
        rej = []
        if edge: rej.append("触边")
        if abs(cx - XC) > C["x_tol"]: rej.append(f"x_tol(cx={cx:.0f})")
        if size < C["min_size"]: rej.append("太小")
        if size > C["max_size"]: rej.append(f"太大({size})")
        if fill > C["max_fill"]: rej.append(f"fill={fill:.2f}")
        if aspect < C["min_aspect"]: rej.append(f"aspect={aspect:.2f}")
        comps.append({"size": size, "cx": round(cx, 1), "cy": round(cy, 1),
                      "bbox_y": [y0, y1], "bbox_x": [x0, x1],
                      "fill": round(float(fill), 3), "aspect": round(float(aspect), 2),
                      "rejected_by": rej, "pass": len(rej) == 0})
    comps.sort(key=lambda c: -c["size"])
    rows.append({"z": z, "n_comp": len(comps), "top": comps[:6]})

res = {"params": C, "rows": rows,
       "note": "这里不做 x 硬边界，只做 v9 的形态判据（x_tol/fill/aspect/size/触边）"}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)

print("WROTE", OUT)
print(f"{'z':>5} {'域':>4} {'size':>7} {'cx':>6} {'fill':>6} {'aspect':>7}  pass  被判据拒绝")
for r in rows:
    for i, c in enumerate(r["top"][:3]):
        print(f"{r['z']:>5} {i:>4} {c['size']:>7} {c['cx']:>6} {c['fill']:>6} "
              f"{c['aspect']:>7}  {'OK' if c['pass'] else 'NG'}   {','.join(c['rejected_by'])}")
