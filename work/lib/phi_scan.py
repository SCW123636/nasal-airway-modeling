# -*- coding: utf-8 -*-
"""扫描 资料/脱敏数据 全量 DICOM 的 PHI 字段现状（只读）。
输出 JSON 报告，供决定脱敏字段清单。"""
import os, json, re
from collections import Counter, defaultdict
import pydicom

ROOT = r"D:\项目\鼻腔建模\资料\脱敏数据\患者ct+鼻空腔建模\患者ct+鼻空腔建模"
OUT = r"D:\项目\鼻腔建模\.workbuddy\probe\phi_scan.json"

# 需要重点盯的字段（DICOM PS3.15 基本应用级保密配置 + 本项目补充）
WATCH = [
    "PatientName", "PatientID", "PatientBirthDate", "PatientBirthTime",
    "PatientSex", "PatientAge", "PatientAddress", "PatientTelephoneNumbers",
    "OtherPatientIDs", "OtherPatientNames", "PatientMotherBirthName",
    "IssuerOfPatientID", "PatientComments", "PatientWeight", "PatientSize",
    "StudyID", "AccessionNumber", "StudyDescription", "SeriesDescription",
    "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName",
    "ReferringPhysicianName", "PerformingPhysicianName", "OperatorsName",
    "PhysiciansOfRecord", "RequestingPhysician", "NameOfPhysiciansReadingStudy",
    "StationName", "DeviceSerialNumber", "ManufacturerModelName",
    "StudyDate", "StudyTime", "SeriesDate", "AcquisitionDate", "ContentDate",
    "AcquisitionDateTime", "InstanceCreationDate", "InstanceCreationTime",
    "SoftwareVersions", "ImageComments", "DerivationDescription",
    "ProtocolName", "FrameOfReferenceUID", "StudyInstanceUID",
    "SeriesInstanceUID", "SOPInstanceUID", "MediaStorageSOPInstanceUID",
    "SOPClassUID", "MediaStorageSOPClassUID", "IssuerOfPatientID",
    "DeviceSerialNumber", "ImageType", "ConvolutionKernel",
    "RescaleIntercept", "RescaleSlope", "KVP", "XRayTubeCurrent",
    "Exposure", "ExposureTime", "PatientPosition", "SliceThickness",
]

counters = defaultdict(Counter)      # field -> Counter(values) 只有非空才统计
present = Counter()                  # field -> 出现文件数
unique_vals = defaultdict(set)

nf = 0
for pat in sorted(os.listdir(ROOT)):
    pdir = os.path.join(ROOT, pat)
    if not os.path.isdir(pdir):
        continue
    for cur, dirs, files in os.walk(pdir):
        for fn in files:
            if not fn.endswith(".dcm"):
                continue
            fp = os.path.join(cur, fn)
            try:
                ds = pydicom.dcmread(fp, stop_before_pixels=True, force=True)
            except Exception:
                continue
            nf += 1
            for f in WATCH:
                v = ds.get(f, None)
                if v is None:
                    continue
                s = str(v).strip()
                if s == "":
                    continue
                present[f] += 1
                if len(unique_vals[f]) < 40:
                    unique_vals[f].add(s[:80])

report = {
    "n_files_scanned": nf,
    "field_presence": dict(sorted(present.items(), key=lambda kv: -kv[1])),
    "distinct_values": {k: sorted(v) for k, v in sorted(unique_vals.items())},
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print("scanned", nf, "->", OUT)
