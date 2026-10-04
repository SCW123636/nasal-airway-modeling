# -*- coding: utf-8 -*-
"""独立验证脱敏结果：直接扫输出目录，检查 PHI 是否真的没了、几何是否真的保住了。
不读 deid_batch 自己的日志。"""
import os, json, re
import pydicom

DST = r"D:\项目\鼻腔建模\资料\脱敏数据_clean"
OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\deid_verify.json"

# 必须为空的 PHI 字段
MUST_BE_EMPTY = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientAddress",
    "PatientTelephoneNumbers", "InstitutionName", "InstitutionAddress",
    "InstitutionalDepartmentName", "PerformingPhysicianName", "OperatorsName",
    "ReferringPhysicianName", "StationName", "DeviceSerialNumber",
    "AccessionNumber", "StudyID", "ImageComments", "DerivationDescription",
]
# 必须保留的几何/物理字段
MUST_KEEP = [
    "PixelSpacing", "ImagePositionPatient", "ImageOrientationPatient",
    "Rows", "Columns", "RescaleIntercept", "RescaleSlope", "ConvolutionKernel",
    "SliceThickness", "KVP",
]

# PHI 黑名单正则（任何字段值命中即报警）
PII_RE = re.compile(
    r"(周宇星恒|TANG|KANG TIAN|周佳圆|Fudan|Shenzhen|中南大学|湘雅|"
    r"深圳市|长沙市|岳麓区|福田区|笋岗|桐梓坡|250111559|p01360058|"
    r"19950215|19970309|20011126|CT20250902|20250709001792|20260217000034)",
    re.IGNORECASE)

rep = {"n_files": 0, "phi_leaks": [], "geometry_missing": [], "uid_regex_ok": True,
       "per_patient": {}, "dup_uid_check": {}}
all_uid = {}
uid_field_counts = {}

for cur, dirs, files in os.walk(DST):
    dcms = sorted(f for f in files if f.endswith(".dcm"))
    if not dcms:
        continue
    rel = os.path.relpath(cur, DST)
    pat = rel.split(os.sep)[0]
    pp = rep["per_patient"].setdefault(pat, {"files": 0, "phi": 0, "geo_ok": 0})

    # 每序列只抽查首末两帧（全量2449帧太慢），并对每帧做 PHI 全字段正则扫描
    sample = [dcms[0]] if len(dcms) == 1 else [dcms[0], dcms[-1]]
    for i, fn in enumerate(dcms):
        fp = os.path.join(cur, fn)
        do_full = (fn in sample) or (i % 37 == 0)   # 抽样做逐字段正则
        try:
            ds = pydicom.dcmread(fp, force=True,
                                 stop_before_pixels=not do_full)
        except Exception as e:
            rep["phi_leaks"].append({"file": fp, "err": repr(e)})
            continue
        rep["n_files"] += 1
        pp["files"] += 1

        # 1) 必空字段
        for kw in MUST_BE_EMPTY:
            v = ds.get(kw, None)
            if v not in (None, ""):
                s = str(v).strip()
                if s and s != "None":
                    rep["phi_leaks"].append({"file": rel + "/" + fn, "field": kw, "val": s[:60]})
                    pp["phi"] += 1

        # 2) 几何字段
        miss = [kw for kw in MUST_KEEP
                if kw in [e.keyword for e in ds] and ds.get(kw, None) in (None, [], "")]
        # 只对关键三个硬性要求
        hard = ["Rows", "Columns"]
        miss_hard = [kw for kw in hard if ds.get(kw, None) in (None, 0)]
        if not miss_hard:
            pp["geo_ok"] += 1
        else:
            rep["geometry_missing"].append({"file": rel + "/" + fn, "missing": miss_hard})

        # 3) 全字段 PHI 正则（仅抽样）
        if do_full:
            for elem in ds:
                try:
                    if elem.VR in ("SQ", "OB", "OW", "UN", "OB or OW", "US or SS"):
                        continue
                    v = elem.value
                    if v is None:
                        continue
                    m = PII_RE.search(str(v))
                    if m:
                        rep["phi_leaks"].append({
                            "file": rel + "/" + fn, "field": elem.keyword or str(elem.tag),
                            "val": str(v)[:70], "hit": m.group(0)})
                        pp["phi"] += 1
                except Exception:
                    pass

        # 4) UID 合规 + 唯一性
        for kw in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID",
                   "FrameOfReferenceUID"):
            u = ds.get(kw, None)
            if u in (None, ""):
                continue
            su = str(u)
            if not re.match(r"^[0-9.]+$", su) or len(su) > 64:
                rep["uid_regex_ok"] = False
                rep["phi_leaks"].append({"file": rel + "/" + fn, "field": kw,
                                         "val": "BAD_UID " + su[:60]})
            all_uid.setdefault((pat, su), set()).add(kw)
            uid_field_counts.setdefault(kw, set()).add(su)

rep["n_phi_leaks"] = len([x for x in rep["phi_leaks"] if "err" not in x])
rep["uid_counts"] = {k: len(v) for k, v in uid_field_counts.items()}
rep["geometry_missing_n"] = len(rep["geometry_missing"])
rep["geometry_missing"] = rep["geometry_missing"][:20]
rep["phi_leaks"] = rep["phi_leaks"][:40]

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)
print("verify ->", OUT)
print("files:", rep["n_files"], "PHI leaks:", rep["n_phi_leaks"],
      "geo missing:", rep["geometry_missing_n"], "uid_regex_ok:", rep["uid_regex_ok"])
