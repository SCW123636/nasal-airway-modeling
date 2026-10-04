# -*- coding: utf-8 -*-
"""核查：v9 掩膜覆盖区的 HU 分布 vs 真实空气区的 HU 分布
目的：判定红色掩膜究竟压在空气上还是压在组织上
"""
import os, sys, json
import numpy as np
sys.path.insert(0, r"D:\项目\鼻腔建模\work\lib")
from nasal_io import load_dicom_series

OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\mask_hu_check.json"
vol, sp, org, meta = load_dicom_series(r"D:\项目\鼻腔建模\work\00_dicom\bone", verbose=False)
mask = np.load(r"D:\项目\鼻腔建模\work\02_segment\nasal_mask_v9.npy")

res = {"vol_shape": list(vol.shape), "spacing": list(sp) if sp is not None else None}

# 掩膜内 HU 分布
mv = vol[mask]
res["mask_voxels"] = int(mask.sum())
if mv.size:
    res["mask_hu"] = {
        "min": int(mv.min()), "max": int(mv.max()),
        "mean": round(float(mv.mean()), 1), "median": int(np.median(mv)),
        "p01": int(np.percentile(mv, 1)), "p05": int(np.percentile(mv, 5)),
        "p50": int(np.percentile(mv, 50)), "p95": int(np.percentile(mv, 95)),
        "p99": int(np.percentile(mv, 99)),
        "frac_below_-300": round(float((mv < -300).mean()), 4),
        "frac_below_-500": round(float((mv < -500).mean()), 4),
        "frac_above_0": round(float((mv > 0).mean()), 4),
    }

# 逐层对比：z=130..235 每层的 `空气总数` vs `掩膜数` vs `掩膜内非空气数`
rows = []
for z in range(120, 245, 5):
    air2d = int((vol[z] < -300).sum())
    m2d = int(mask[z].sum())
    if m2d:
        nonair = int((vol[z][mask[z]] >= -300).sum())
    else:
        nonair = 0
    rows.append({"z": z, "air_lt_-300": air2d, "mask": m2d,
                 "mask_nonair": nonair,
                 "bad_ratio": round(nonair / max(1, m2d), 3)})
res["per_layer"] = rows

# 掩膜 bbox 内的空气占比（判断是否漏掉了大量空气）
zz, yy, xx = np.where(mask)
b = {"z": [int(zz.min()), int(zz.max())], "y": [int(yy.min()), int(yy.max())],
     "x": [int(xx.min()), int(xx.max())]}
res["mask_bbox"] = b
sub = vol[b["z"][0]:b["z"][1]+1, b["y"][0]:b["y"][1]+1, b["x"][0]:b["x"][1]+1]
res["bbox_air_total"] = int((sub < -300).sum())
res["bbox_air_captured"] = int(mask.sum())
res["bbox_capture_rate"] = round(float(mask.sum() / max(1, (sub < -300).sum())), 4)

# x 方向空气分布直方图（找出鼻腔主体真实的 x 位置）
zr = vol[130:230]
air_3d = zr < -300
x_hist = air_3d.sum(axis=(0, 1))
res["x_air_hist_nonzero"] = [[int(i), int(v)] for i, v in enumerate(x_hist) if v > 500]
res["x_air_peak"] = int(np.argmax(x_hist))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
print("WROTE", OUT)
print(json.dumps(res["mask_hu"], ensure_ascii=False, indent=2))
print("bbox:", b, "capture_rate:", res["bbox_capture_rate"], "x_peak:", res["x_air_peak"])
