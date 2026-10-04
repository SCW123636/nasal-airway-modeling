# -*- coding: utf-8 -*-
"""
探查 资料/脱敏数据/脱敏后图像数据/ —— 上一轮脱敏与标定都未覆盖的一批数据。
目的：判定它是什么（哪个患者/哪台设备/什么几何）、是否真脱敏、能否用于项目。
只读，不修改任何数据。
"""
import os, json, collections

import pydicom

ROOT = r"D:\项目\鼻腔建模\资料\脱敏数据\脱敏后图像数据"
OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\iso035_scan.json"

PHI_TAGS = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex", "PatientAge",
    "PatientAddress", "PatientTelephoneNumbers", "OtherPatientIDs",
    "StudyDate", "StudyTime", "SeriesDate", "AcquisitionDate", "AcquisitionDateTime",
    "ContentDate", "InstanceCreationDate",
    "AccessionNumber", "StudyID", "InstitutionName", "InstitutionAddress",
    "InstitutionalDepartmentName", "ReferringPhysicianName", "PerformingPhysicianName",
    "OperatorsName", "NameOfPhysiciansReadingStudy", "PhysiciansOfRecord",
    "StationName", "DeviceSerialNumber", "Manufacturer", "ManufacturerModelName",
    "StudyDescription", "SeriesDescription", "ProtocolName", "BodyPartExamined",
    "PatientPosition", "SoftwareVersions", "PrivateCreator",
]

report = {"root": ROOT, "series": [], "phi_table": {}, "phi_leaks": [], "dup_check": {}}

# ---------- 1. 逐个 part 目录清点 ----------
dirs = sorted([d for d in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, d))])
name_map = collections.defaultdict(list)   # 逻辑序列名 -> [(part_dir, {basename})...]

for d in dirs:
    sub = os.path.join(ROOT, d)
    inner = [x for x in os.listdir(sub) if os.path.isdir(os.path.join(sub, x))]
    target = os.path.join(sub, inner[0]) if inner else sub
    files = sorted([f for f in os.listdir(target) if f.lower().endswith(".dcm")])
    logical = d.rsplit("_part", 1)[0]
    name_map[logical].append((d, set(files)))
    report["series"].append({
        "part_dir": d, "inner": inner, "n_dcm": len(files),
        "first": files[0] if files else None,
        "last": files[-1] if files else None,
        "files": files, "path": target,
    })

# ---------- 2. 合并重名检查 ----------
for logical, parts in name_map.items():
    seen = collections.Counter()
    for d, fs in parts:
        seen.update(fs)
    dups = {k: v for k, v in seen.items() if v > 1}
    report["dup_check"][logical] = {
        "n_parts": len(parts),
        "total_files": sum(len(fs) for _, fs in parts),
        "unique_names": len(seen),
        "duplicates": dups,
    }

# ---------- 3. 读头部：几何 + PHI（每个 part 取首帧 + 全局首末） ----------
def dump(ds):
    out = {}
    for t in PHI_TAGS:
        v = ds.get(t, None)
        if v is None:
            continue
        s = str(v)
        out[t] = s if len(s) <= 80 else s[:80] + "..."
    return out

first_dir = report["series"][0]["path"] if report["series"] else None
for rec in report["series"]:
    p = rec["path"]
    fs = sorted([f for f in os.listdir(p) if f.lower().endswith(".dcm")])
    if not fs:
        continue
    try:
        ds = pydicom.dcmread(os.path.join(p, fs[0]), stop_before_pixels=True, force=True)
    except Exception as e:
        rec["error"] = repr(e)
        continue
    rec["sop_class"] = str(ds.get("SOPClassUID", ""))
    rec["modality"] = str(ds.get("Modality", ""))
    rec["rows"] = int(ds.get("Rows", 0) or 0)
    rec["cols"] = int(ds.get("Columns", 0) or 0)
    rec["pixel_spacing"] = [float(x) for x in ds.get("PixelSpacing", [])] or None
    rec["slice_thickness"] = float(ds.get("SliceThickness", 0) or 0) or None
    rec["spacing_between"] = float(ds.get("SpacingBetweenSlices", 0) or 0) or None
    rec["rescale_intercept"] = float(ds.get("RescaleIntercept", 0) or 0)
    rec["rescale_slope"] = float(ds.get("RescaleSlope", 1) or 1)
    rec["instance_number"] = int(ds.get("InstanceNumber", 0) or 0)
    rec["transfer_syntax"] = str(ds.file_meta.TransferSyntaxUID)
    rec["bits"] = f"{ds.get('BitsAllocated')}/{ds.get('BitsStored')}"
    rec["ipp_first"] = [round(float(x), 3) for x in ds.get("ImagePositionPatient", [])] or None
    iop = ds.get("ImageOrientationPatient", None)
    rec["iop"] = [round(float(x), 4) for x in iop] if iop else None

    # 末帧 z 覆盖
    try:
        last = pydicom.dcmread(os.path.join(p, fs[-1]), stop_before_pixels=True, force=True)
        rec["ipp_last"] = [round(float(x), 3) for x in last.ImagePositionPatient]
    except Exception:
        rec["ipp_last"] = None

    rec["head"] = dump(ds)

# ---------- 4. PHI 泄露判定（关键词命中） ----------
SUSPECT = re_kw = ["姓名", "医生", "医院", "浙", "患者", "MRN", "TEL"]
for rec in report["series"]:
    h = rec.get("head", {})
    for k, v in h.items():
        if k in ("Manufacturer", "ManufacturerModelName", "Modality", "BodyPartExamined",
                 "PatientPosition", "SoftwareVersions"):
            continue
        s = str(v)
        # 明显未脱敏：含中文姓名样式 / 非掩码字符 / 真实机构
        suspicious = False
        if k in ("PatientName",) and s.strip("*") and not set(s) <= set("* "):
            suspicious = True
        if k in ("InstitutionName", "InstitutionAddress") and s and s not in ("(none)",):
            suspicious = True
        if k in ("ReferringPhysicianName", "PerformingPhysicianName", "OperatorsName",
                 "NameOfPhysiciansReadingStudy") and s and not set(s) <= set("*^ "):
            suspicious = True
        if k in ("PatientAddress", "PatientTelephoneNumbers", "PatientID",
                 "AccessionNumber", "StationName", "DeviceSerialNumber") and s and not set(s) <= set("* "):
            suspicious = True
        if suspicious:
            report["phi_leaks"].append({"part_dir": rec["part_dir"], "tag": k, "value": s})

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)

# ---------- 5. 控制台摘要 ----------
print("=== 逻辑序列 ===")
for logical, d in report["dup_check"].items():
    print(f"{logical}: parts={d['n_parts']} total={d['total_files']} unique={d['unique_names']} dups={len(d['duplicates'])}")
print()
print("=== 首帧几何 ===")
for rec in report["series"]:
    if "error" in rec:
        print(rec["part_dir"], "ERROR", rec["error"]); continue
    print(f"{rec['part_dir']}: {rec['rows']}x{rec['cols']} ps={rec['pixel_spacing']} "
          f"thick={rec['slice_thickness']} sbs={rec['spacing_between']} "
          f"intercept={rec['rescale_intercept']} inst={rec['instance_number']} "
          f"ts={rec['transfer_syntax']} bits={rec['bits']}")
print()
print("=== 关键头部(首帧) ===")
if report["series"]:
    for k, v in report["series"][0].get("head", {}).items():
        print(f"  {k} = {v}")
print()
print("=== PHI 疑点 ===", len(report["phi_leaks"]))
for x in report["phi_leaks"][:30]:
    print("  ", x["tag"], "=", x["value"])
print()
print("written:", OUT)
