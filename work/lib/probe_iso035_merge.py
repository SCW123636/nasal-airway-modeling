# -*- coding: utf-8 -*-
"""
1) 核实 患者ct+鼻空腔建模 三患者的 机构/设备 归属（只读原始数据，不修改）
2) 验证 脱敏后图像数据 0.35mm 的 3 个 part 能否拼成一个连续完整体数据（几何 + HU）
输出 JSON 供回读。
"""
import os, json, collections
import numpy as np
import pydicom
import SimpleITK as sitk

ORIG = r"D:\项目\鼻腔建模\资料\脱敏数据\患者ct+鼻空腔建模\患者ct+鼻空腔建模"
ISO = r"D:\项目\鼻腔建模\资料\脱敏数据\脱敏后图像数据"
OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\iso035_merge.json"

rep = {"patients": {}, "iso035": {}}

# ---------- 1. 三患者 机构/设备 ----------
TAGS = ["Manufacturer", "ManufacturerModelName", "InstitutionName", "InstitutionAddress",
        "StudyDate", "SeriesDate", "PatientSex", "PatientAge", "StudyDescription",
        "SoftwareVersions", "DeviceSerialNumber", "StationName"]
for p in ["患者1", "患者2", "患者3"]:
    root = os.path.join(ORIG, p)
    seen = {t: collections.Counter() for t in TAGS}
    n_series = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dcms = sorted([f for f in filenames if f.lower().endswith(".dcm")])
        if not dcms:
            continue
        n_series += 1
        try:
            ds = pydicom.dcmread(os.path.join(dirpath, dcms[0]), stop_before_pixels=True, force=True)
        except Exception:
            continue
        for t in TAGS:
            v = ds.get(t, None)
            if v is not None and str(v).strip():
                seen[t][str(v)[:70]] += 1
    rep["patients"][p] = {
        "n_series_dirs": n_series,
        "values": {t: dict(c) for t, c in seen.items() if c},
    }

# ---------- 2. 0.35mm 三 part 拼接 ----------
for series in ["ISO_Bone_0.35mm", "ISO_Soft_0.35mm"]:
    parts = [f"{series}_part{i}" for i in (1, 2, 3)]
    arrs, ipps, tags = [], [], None
    for part in parts:
        d = os.path.join(ISO, part, series)
        fs = sorted([f for f in os.listdir(d) if f.lower().endswith(".dcm")])
        assert fs == sorted(fs), part
        # 按 InstanceNumber 排序
        recs = []
        for f in fs:
            ds = pydicom.dcmread(os.path.join(d, f), stop_before_pixels=True, force=True)
            recs.append((int(ds.InstanceNumber), f))
        recs.sort()
        imgs = []
        for _, f in recs:
            ds = pydicom.dcmread(os.path.join(d, f), force=True)
            a = ds.pixel_array.astype(np.int16)
            hu = a * float(ds.RescaleSlope) + float(ds.RescaleIntercept)
            imgs.append(hu)
            ipps.append([float(x) for x in ds.ImagePositionPatient])
            if tags is None:
                tags = {"rows": int(ds.Rows), "cols": int(ds.Columns),
                        "ps": [float(x) for x in ds.PixelSpacing],
                        "thick": float(ds.SliceThickness),
                        "iop": [float(x) for x in ds.ImageOrientationPatient],
                        "intercept": float(ds.RescaleIntercept),
                        "slope": float(ds.RescaleSlope),
                        "seriesdesc": str(ds.SeriesDescription),
                        "inst_range": [int(recs[0][0]), int(recs[-1][0])]}
        arrs.append(np.stack(imgs, 0))
    vol = np.concatenate(arrs, 0)
    z = np.array([p[2] for p in ipps], dtype=float)
    dz = np.diff(z)
    rep["iso035"][series] = {
        "n_slices_total": int(vol.shape[0]),
        "shape_zyx": list(vol.shape),
        "hu_min": int(vol.min()), "hu_max": int(vol.max()),
        "z_first": round(float(z[0]), 3), "z_last": round(float(z[-1]), 3),
        "z_span_mm": round(float(abs(z[-1] - z[0])), 3),
        "dz_unique": sorted(set(np.round(np.abs(dz), 4).tolist()))[:6],
        "dz_max_jump": round(float(np.abs(dz).max()), 4),
        "monotonic": bool(np.all(dz < 0) or np.all(dz > 0)),
        "tags": tags,
    }

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=1)

print("=== 三患者 机构/设备 ===")
for p, d in rep["patients"].items():
    print(p, "series_dirs=", d["n_series_dirs"])
    for t in ("Manufacturer", "ManufacturerModelName", "InstitutionName", "StudyDate", "SoftwareVersions"):
        if t in d["values"]:
            print("   ", t, "=", list(d["values"][t].keys()))
print()
print("=== 0.35mm 拼接结果 ===")
for s, d in rep["iso035"].items():
    print(s)
    print("   slices", d["n_slices_total"], "shape", d["shape_zyx"], "HU", d["hu_min"], "..", d["hu_max"])
    print("   z", d["z_first"], "->", d["z_last"], "span", d["z_span_mm"], "dz", d["dz_unique"], "maxjump", d["dz_max_jump"])
    print("   monotonic", d["monotonic"], "tags", d["tags"])
print()
print("written:", OUT)
