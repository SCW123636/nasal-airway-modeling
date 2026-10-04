# -*- coding: utf-8 -*-
"""探两套 CT 序列的基本信息：层数、尺寸、spacing、原点、z 轴是否对齐"""
import os, json, sys
import numpy as np
import pydicom

ROOT = r"D:\项目\鼻腔建模\work\00_dicom"
OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\series_probe.json"

def probe(sub):
    d = os.path.join(ROOT, sub)
    files = sorted([f for f in os.listdir(d) if f.lower().endswith(".dcm")])
    info = {"dir": d, "n_files": len(files)}
    if not files:
        return info
    ds0 = pydicom.dcmread(os.path.join(d, files[0]), force=True)
    dsN = pydicom.dcmread(os.path.join(d, files[-1]), force=True)
    g = lambda ds, k, dv=None: getattr(ds, k, dv)
    info.update({
        "Rows": int(g(ds0, "Rows", 0)),
        "Columns": int(g(ds0, "Columns", 0)),
        "PixelSpacing": [float(x) for x in g(ds0, "PixelSpacing", [0, 0])],
        "SliceThickness": float(g(ds0, "SliceThickness", 0)),
        "SpacingBetweenSlices": float(g(ds0, "SpacingBetweenSlices", 0)),
        "InstanceNumber_first": int(g(ds0, "InstanceNumber", 0)),
        "InstanceNumber_last": int(g(dsN, "InstanceNumber", 0)),
        "IPP_first": [float(x) for x in g(ds0, "ImagePositionPatient", [0, 0, 0])],
        "IPP_last": [float(x) for x in g(dsN, "ImagePositionPatient", [0, 0, 0])],
        "IOP": [float(x) for x in g(ds0, "ImageOrientationPatient", [0]*6)],
        "RescaleSlope": float(g(ds0, "RescaleSlope", 1.0)),
        "RescaleIntercept": float(g(ds0, "RescaleIntercept", 0.0)),
        "WindowCenter": str(g(ds0, "WindowCenter", "")),
        "WindowWidth": str(g(ds0, "WindowWidth", "")),
        "SeriesDescription": str(g(ds0, "SeriesDescription", "")),
        "ConvolutionKernel": str(g(ds0, "ConvolutionKernel", "")),
        "PatientPosition": str(g(ds0, "PatientPosition", "")),
        "Modality": str(g(ds0, "Modality", "")),
    })
    # 真实层间距：所有层 IPP z 的差分中位数
    zs = []
    for f in files:
        ds = pydicom.dcmread(os.path.join(d, f), force=True)
        ipp = getattr(ds, "ImagePositionPatient", None)
        if ipp is not None:
            zs.append(float(ipp[2]))
    zs = np.array(sorted(zs))
    if len(zs) > 1:
        dz = np.diff(zs)
        info["dz_median"] = float(np.median(dz))
        info["dz_unique_n"] = int(len(np.unique(np.round(dz, 3))))
        info["dz_unique_sample"] = sorted(set(np.round(dz, 3).tolist()))[:8]
        info["z_min"] = float(zs.min())
        info["z_max"] = float(zs.max())
        info["z_span"] = float(zs.max() - zs.min())
    return info

res = {}
for sub in ["bone", "soft"]:
    try:
        res[sub] = probe(sub)
    except Exception as e:
        res[sub] = {"error": repr(e)}

# 两套是否对齐
if "bone" in res and "soft" in res and "z_min" in res.get("bone", {}) and "z_min" in res.get("soft", {}):
    b, s = res["bone"], res["soft"]
    res["_compare"] = {
        "z_min_diff": round(b["z_min"] - s["z_min"], 3),
        "z_max_diff": round(b["z_max"] - s["z_max"], 3),
        "dz_bone": b.get("dz_median"), "dz_soft": s.get("dz_median"),
        "same_rows_cols": (b["Rows"], b["Columns"]) == (s["Rows"], s["Columns"]),
        "same_ipp_first": b["IPP_first"] == s["IPP_first"],
        "same_iop": b["IOP"] == s["IOP"],
    }

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=2)
print("WROTE", OUT)
print(json.dumps(res.get("_compare", {}), ensure_ascii=False, indent=2))
