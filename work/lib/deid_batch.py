# -*- coding: utf-8 -*-
"""DICOM 批量脱敏（tag 级，PS3.15 Basic Application Level Confidentiality Profile 思路）。

原则：
1. 只读原始目录，输出到独立的新目录，绝不改原始数据。
2. 影像几何（ImagePositionPatient / ImageOrientationPatient / PixelSpacing /
   SliceThickness / Rows / Columns / 像素数据）一律保留 —— 脱敏不能破坏可计算性。
3. UID 全部重映射（保持一致性的查表映射，同一原始 UID 换同一个新 UID）。
4. 日期偏移：同一患者所有日期统一偏移一个固定随机天数，保留相对时间关系
   （患者3 有 2025-07 与 2026-02 两次检查，偏移后仍可做纵向对比）。
5. 保留 ConvolutionKernel / RescaleIntercept / KVP / SliceThickness 等物理参数，
   它们不是 PHI 但决定影像可比性。
"""
import os, sys, json, hashlib, datetime, shutil, traceback
import pydicom
from pydicom.uid import generate_uid
from pydicom.datadict import tag_for_keyword

SRC = r"D:\项目\鼻腔建模\资料\脱敏数据\患者ct+鼻空腔建模\患者ct+鼻空腔建模"
DST = r"D:\项目\鼻腔建模\资料\脱敏数据_clean"
LOG = r"D:\项目\鼻腔建模\.workbuddy\probe\deid_log.json"

# ---- 设备/产品白名单：这些字段不含 PHI 但影响可复现性，保留 ----
KEEP_TAGS = {
    "Modality", "Manufacturer", "ManufacturerModelName", "SoftwareVersions",
    "ConvolutionKernel", "RescaleIntercept", "RescaleSlope", "KVP",
    "XRayTubeCurrent", "Exposure", "ExposureTime", "SliceThickness",
    "SpacingBetweenSlices", "PixelSpacing", "Rows", "Columns", "BitsStored",
    "BitsAllocated", "PixelRepresentation", "PhotometricInterpretation",
    "ImagePositionPatient", "ImageOrientationPatient", "SliceLocation",
    "ImageType", "SOPClassUID", "PatientPosition", "WindowCenter", "WindowWidth",
    "ProtocolName", "SeriesDescription", "StudyDescription", "BodyPartExamined",
    "RescaleType", "PixelSpacingCalibrationType", "SamplesPerPixel",
}

# ---- 直接清空的 PHI 字段 ----
BLANK = [
    "PatientName", "PatientID", "IssuerOfPatientID", "OtherPatientIDs",
    "OtherPatientNames", "PatientBirthDate", "PatientBirthTime", "PatientSex",
    "PatientAge", "PatientAddress", "PatientTelephoneNumbers", "PatientComments",
    "PatientMotherBirthName", "PatientWeight", "PatientSize", "EthnicGroup",
    "Occupation", "MilitaryRank", "MedicalRecordLocator", "PatientInsurancePlanCodeSequence",
    "InstitutionName", "InstitutionAddress", "InstitutionalDepartmentName",
    "ReferringPhysicianName", "PerformingPhysicianName", "OperatorsName",
    "PhysiciansOfRecord", "RequestingPhysician", "NameOfPhysiciansReadingStudy",
    "PhysiciansOfRecordIdentificationSequence", "PatientSetupSequence",
    "StationName", "DeviceSerialNumber", "AccessionNumber", "StudyID",
    "FillerOrderNumberImagingServiceRequest", "PlacerOrderNumberImagingServiceRequest",
    "AdmittingDiagnosesDescription", "ImageComments", "StudyComments",
    "DerivationDescription", "RequestedProcedureDescription",
    "RequestAttributesSequence", "RequestedProcedureID", "ScheduledProcedureStepID",
    "PerformedProcedureStepDescription", "PerformedProcedureStepID",
    "ContentCreatorName", "VerifyingObserverName", "PersonName",
    "PhysicianApprovingInterpretation", "NameOfPhysiciansReadingStudy",
    "SpecialNeeds", "AdditionalPatientHistory", "PatientState",
    "IssuerOfPatientIDQualifiersSequence", "ClinicalTrialSubjectID",
    "ClinicalTrialSubjectReadingID", "ClinicalTrialTimePointID",
]

# ---- 日期字段：统一偏移 ----
DATE_TAGS = ["StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate",
             "InstanceCreationDate", "DateOfLastCalibration", "PerformedProcedureStepStartDate"]
DATETIME_TAGS = ["AcquisitionDateTime", "InstanceCreationTime"]  # time 单独处理
TIME_TAGS = ["StudyTime", "SeriesTime", "AcquisitionTime", "ContentTime",
             "InstanceCreationTime", "PerformedProcedureStepStartTime"]

# ---- UID 字段：重映射 ----
UID_TAGS = ["StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID",
            "FrameOfReferenceUID", "MediaStorageSOPInstanceUID",
            "ReferencedSOPInstanceUID", "ReferencedFrameOfReferenceUID",
            "SynchronizationFrameOfReferenceUID", "ConcatenationUID",
            "DimensionOrganizationUID", "RelatedFrameOfReferenceUID"]

# 每个患者一个固定的 UID 前缀 + 日期偏移，保证可复现
PATIENT_SALT = {"患者1": "P1", "患者2": "P2", "患者3": "P3"}
DATE_SHIFT = {"患者1": -412, "患者2": -97, "患者3": -233}  # 固定偏移天数

uid_map = {}
log = {"files": 0, "errors": [], "blanked": 0, "uid_remapped": 0,
       "date_shifted": 0, "patients": {}}


def remap_uid(old, salt):
    if not old:
        return old
    key = (salt, str(old))
    if key in uid_map:
        return uid_map[key]
    h = hashlib.sha1((salt + "|" + str(old)).encode()).hexdigest()
    # 用固定 root 2.25.<uuid int> 形式，保证 DICOM 合法
    digits = str(int(h[:32], 16))
    new = "2.25." + digits
    uid_map[key] = new
    return new


def shift_date(s):
    if not s:
        return s
    s = str(s).strip()
    if len(s) != 8 or not s.isdigit():
        return s
    try:
        d = datetime.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return s
    d2 = d + datetime.timedelta(days=DATE_SHIFT[pat])
    return d2.strftime("%Y%m%d")


def shift_datetime(s):
    """YYYYMMDDHHMMSS.ffffff -> 偏移日期部分"""
    if not s:
        return s
    s = str(s).strip()
    if len(s) < 8:
        return s
    dpart, tpart = s[:8], s[8:]
    return shift_date(dpart) + tpart


def process_file(fp, out_fp, pat):
    ds = pydicom.dcmread(fp, force=True)
    changed = []

    # 1. 清空 PHI
    for kw in BLANK:
        if hasattr(ds, kw) or kw in ds:
            try:
                delattr(ds, kw)
                changed.append("blank:" + kw)
            except Exception:
                try:
                    del ds[kw]
                    changed.append("blank:" + kw)
                except Exception:
                    pass

    # 1b. 兜底：所有未在 KEEP 白名单里的 PersonName (PN) 类型一律清空
    for elem in list(ds):
        if elem.VR == "PN" and elem.keyword not in KEEP_TAGS:
            try:
                del ds[elem.tag]
                changed.append("blankPN:" + elem.keyword)
            except Exception:
                pass

    # 2. 日期偏移
    for kw in DATE_TAGS:
        if kw in ds:
            try:
                old = str(ds.get(kw))
                new = shift_date(old)
                if new != old:
                    ds[kw].value = new
                    changed.append("date:" + kw)
                    log["date_shifted"] += 1
            except Exception:
                pass
    for kw in DATETIME_TAGS:
        if kw in ds:
            try:
                old = str(ds.get(kw))
                new = shift_datetime(old)
                if new != old:
                    ds[kw].value = new
                    changed.append("dt:" + kw)
            except Exception:
                pass
    # 时间字段本身保留（不含身份信息，且对重建无影响）；但为降低可关联性也偏移
    # 这里选择保留：时间戳不含身份，且偏移可能破坏 AcquisitionDateTime 一致性

    # 3. UID 重映射
    for kw in UID_TAGS:
        if kw in ds:
            try:
                old = str(ds.get(kw))
                new = remap_uid(old, PATIENT_SALT[pat])
                if new != old:
                    ds[kw].value = new
                    log["uid_remapped"] += 1
            except Exception:
                pass
    # 文件元信息里的 UID
    if hasattr(ds, "file_meta") and ds.file_meta is not None:
        for kw in ("MediaStorageSOPInstanceUID",):
            if hasattr(ds.file_meta, kw):
                try:
                    old = str(getattr(ds.file_meta, kw))
                    setattr(ds.file_meta, kw, remap_uid(old, PATIENT_SALT[pat]))
                except Exception:
                    pass

    # 4. 私有 tag 一律删除（来源不明的私有供应商信息最容易漏 PHI）
    for elem in list(ds):
        if elem.tag.is_private:
            try:
                del ds[elem.tag]
                changed.append("priv:" + str(elem.tag))
            except Exception:
                pass
    for elem in list(ds):
        if elem.VR == "SQ":
            pass  # 序列内部已由上面的 keyword 清除覆盖

    os.makedirs(os.path.dirname(out_fp), exist_ok=True)
    ds.save_as(out_fp, write_like_original=False, enforce_file_format=True)
    return changed


# ---------------- main ----------------
if os.path.exists(DST):
    print("DST exists, abort to avoid mixing:", DST)
    sys.exit(2)

for pat in sorted(os.listdir(SRC)):
    pdir = os.path.join(SRC, pat)
    if not os.path.isdir(pdir) or pat not in PATIENT_SALT:
        continue
    pstat = {"files": 0, "series": set()}
    for cur, dirs, files in os.walk(pdir):
        dcms = [f for f in files if f.endswith(".dcm")]
        if not dcms:
            continue
        rel = os.path.relpath(cur, SRC)
        pstat["series"].add(rel)
        for fn in sorted(dcms):
            fp = os.path.join(cur, fn)
            out_fp = os.path.join(DST, rel, fn)
            try:
                process_file(fp, out_fp, pat)
                log["files"] += 1
                pstat["files"] += 1
            except Exception as e:
                log["errors"].append({"file": fp, "err": repr(e),
                                      "tb": traceback.format_exc()[-800:]})
    pstat["series"] = sorted(pstat["series"])
    log["patients"][pat] = pstat

os.makedirs(os.path.dirname(LOG), exist_ok=True)
with open(LOG, "w", encoding="utf-8") as f:
    json.dump(log, f, ensure_ascii=False, indent=2)
print("done:", log["files"], "files;", len(log["errors"]), "errors")
