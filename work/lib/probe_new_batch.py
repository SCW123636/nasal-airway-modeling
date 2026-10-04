# -*- coding: utf-8 -*-
"""盘点 资料/脱敏数据 三个新患者的 CT 序列元数据。只读，不改任何数据。"""
import os, json, struct, sys
import pydicom

ROOT = r"D:\项目\鼻腔建模\资料\脱敏数据\患者ct+鼻空腔建模\患者ct+鼻空腔建模"
OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\new_batch_probe.json"

def series_meta(d):
    files = sorted([f for f in os.listdir(d) if f.endswith(".dcm")])
    if not files:
        return None
    rec = {"n_files": len(files), "dir": d}
    try:
        ds0 = pydicom.dcmread(os.path.join(d, files[0]), stop_before_pixels=True)
        rec["series_desc"] = str(getattr(ds0, "SeriesDescription", "?"))
        rec["kernel"] = str(getattr(ds0, "ConvolutionKernel", "?"))
        rec["rows"] = int(getattr(ds0, "Rows", 0))
        rec["cols"] = int(getattr(ds0, "Columns", 0))
        rec["pix_spacing"] = [float(x) for x in getattr(ds0, "PixelSpacing", [])]
        rec["slice_thickness"] = float(getattr(ds0, "SliceThickness", 0))
        rec["spacing_between"] = float(getattr(ds0, "SpacingBetweenSlices", 0))
        rec["rescale_intercept"] = float(getattr(ds0, "RescaleIntercept", 0))
        rec["rescale_slope"] = float(getattr(ds0, "RescaleSlope", 1))
        rec["ipp"] = [float(x) for x in getattr(ds0, "ImagePositionPatient", [])]
        rec["iop"] = [float(x) for x in getattr(ds0, "ImageOrientationPatient", [])]
        rec["modality"] = str(getattr(ds0, "Modality", "?"))
        rec["bits"] = int(getattr(ds0, "BitsStored", 0))
        # 病人信息（检查是否真脱敏）
        rec["PatientName"] = str(getattr(ds0, "PatientName", "?"))
        rec["PatientID"] = str(getattr(ds0, "PatientID", "?"))
        rec["PatientBirthDate"] = str(getattr(ds0, "PatientBirthDate", "?"))
        rec["StudyDate"] = str(getattr(ds0, "StudyDate", "?"))
        rec["StudyDescription"] = str(getattr(ds0, "StudyDescription", "?"))
        rec["Manufacturer"] = str(getattr(ds0, "Manufacturer", "?"))
        rec["Model"] = str(getattr(ds0, "ManufacturerModelName", "?"))
        # 层间距唯一性（末层）
        dsL = pydicom.dcmread(os.path.join(d, files[-1]), stop_before_pixels=True)
        rec["ipp_last"] = [float(x) for x in getattr(dsL, "ImagePositionPatient", [])]
        rec["has_pixels"] = True
    except Exception as e:
        rec["error"] = repr(e)
    return rec

result = {}
for pat in sorted(os.listdir(ROOT)):
    pdir = os.path.join(ROOT, pat)
    if not os.path.isdir(pdir):
        continue
    result[pat] = {"subdirs": {}, "stl": None}
    stl = os.path.join(pdir, "nose.stl")
    if os.path.exists(stl):
        sz = os.path.getsize(stl)
        ntri = None
        with open(stl, "rb") as f:
            head = f.read(84)
            if head[:5] == b"solid":
                f.seek(80)
                n = struct.unpack("<I", f.read(4))[0]
                ntri = n
            else:
                ntri = struct.unpack("<I", head[80:84])[0]
        result[pat]["stl"] = {"size": sz, "ntri": ntri}
    # 递归找所有含 dcm 的目录
    for cur, dirs, files in os.walk(pdir):
        if any(f.endswith(".dcm") for f in files):
            m = series_meta(cur)
            rel = os.path.relpath(cur, pdir)
            result[pat]["subdirs"][rel] = m

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("OK ->", OUT)
