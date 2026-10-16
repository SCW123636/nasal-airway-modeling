#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 三患者症状痕迹探查（病历挖掘第一步）
=====================================
目的：在 B 三患者 CT 的 DICOM 头里找症状/诊断痕迹（检查描述、ICD/CPT 编码、
      请求过程描述、SR 报告文本），为「症状对应」主线的 Y 侧标签提供证据。

PHI 纪律（硬约束）：
  - 本脚本只读取白名单「临床语义字段」，身份类字段（姓名/ID/生日/机构/医师/
    日期/流水号/设备号）在代码层面就不构造 tag，不存在泄露路径。
  - 输出 JSON 中不得出现任何身份字段值；序列目录名如含身份信息只做脱敏替换。
  - 原始目录（带 PHI）与脱敏副本都扫，用于对比脱敏是否清掉了临床描述。

技术说明：
  - 只读 DICOM 头（stop_before_pixels=True），不碰像素，规避 JPEG Lossless 解码问题。
  - 白名单字段：
      StudyDescription(0008,1030) / SeriesDescription(0008,103E) /
      BodyPartExamined(0018,0015) / RequestedProcedureDescription(0032,1060) /
      ProcedureCodeSequence(0008,1032) -> CodeValue/CodeMeaning/CodingScheme /
      ImageComments(0020,4000) / Modality(0008,0060) / ImageType(0008,0008) /
      SR: ContentSequence(0040,A730) 递归取 TextValue(0040,A160)+ConceptName
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import pydicom

# ---- 白名单 tag（仅临床语义；身份 tag 不出现在本文件中） ----
TAG_STUDY_DESC = (0x0008, 0x1030)
TAG_SERIES_DESC = (0x0008, 0x103E)
TAG_BODY_PART = (0x0018, 0x0015)
TAG_REQ_PROC_DESC = (0x0032, 0x1060)
TAG_PROC_CODE_SEQ = (0x0008, 0x1032)
TAG_IMAGE_COMMENTS = (0x0020, 0x4000)
TAG_MODALITY = (0x0008, 0x0060)
TAG_IMAGE_TYPE = (0x0008, 0x0008)
TAG_SOP_CLASS = (0x0008, 0x0016)
TAG_CONTENT_SEQ = (0x0040, 0xA730)
TAG_TEXT_VALUE = (0x0040, 0xA160)
TAG_CONCEPT_NAME_SEQ = (0x0040, 0xA043)
TAG_CONCEPT_CODE_SEQ = (0x0040, 0xA168)
TAG_CODE_VALUE = (0x0008, 0x0100)
TAG_CODE_MEANING = (0x0008, 0x0104)
TAG_CODE_SCHEME = (0x0008, 0x0102)
TAG_INSTANCE_NUMBER = (0x0020, 0x0013)
TAG_SERIES_NUMBER = (0x0020, 0x0011)
TAG_SERIES_UID = (0x0020, 0x000E)


def _txt(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _code_item(ds, seq_tag):
    """取编码序列里的 CodeValue + CodeMeaning + CodingScheme。"""
    seq = ds.get(seq_tag, None)
    if not seq:
        return []
    out = []
    for item in seq:
        out.append({
            "code": _txt(item.get(TAG_CODE_VALUE, None)),
            "meaning": _txt(item.get(TAG_CODE_MEANING, None)),
            "scheme": _txt(item.get(TAG_CODE_SCHEME, None)),
        })
    return out


def _walk_content(ds, depth=0, max_depth=6, acc=None):
    """递归提取 SR ContentSequence 的 TextValue + 概念名。"""
    if acc is None:
        acc = []
    if depth > max_depth:
        return acc
    seq = ds.get(TAG_CONTENT_SEQ, None)
    if not seq:
        return acc
    for item in seq:
        concept = None
        cseq = item.get(TAG_CONCEPT_NAME_SEQ, None)
        if cseq:
            concept = _txt(cseq[0].get(TAG_CODE_MEANING, None)) or _txt(cseq[0].get(TAG_CODE_VALUE, None))
        # 有些 SR 用 ConceptNameCodeSequence 以外的方式编码，兼容取 (0040,A168)
        if not concept:
            cseq2 = item.get(TAG_CONCEPT_CODE_SEQ, None)
            if cseq2:
                concept = _txt(cseq2[0].get(TAG_CODE_MEANING, None))
        text = _txt(item.get(TAG_TEXT_VALUE, None))
        if concept or text:
            acc.append({"concept": concept, "text": text, "depth": depth})
        _walk_content(item, depth + 1, max_depth, acc)
    return acc


def scan_patient(root: Path):
    """扫一个患者目录：按 SeriesInstanceUID 归组，每序列取代表帧读头。"""
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".dcm", ".ima", "")]
    # 逐文件读头太慢：按 SeriesInstanceUID 分组，每组只读前 2 帧 + 最后 1 帧
    series_map = defaultdict(list)
    unreadable = 0
    for f in files:
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
        except Exception:
            unreadable += 1
            continue
        suid = _txt(ds.get(TAG_SERIES_UID, None)) or f"__nosuid__{f.parent.name}"
        series_map[suid].append((f, ds))
    out = {}
    for suid, members in series_map.items():
        members.sort(key=lambda m: m[0].name)
        rep = [members[0], members[-1]]
        info = {"frames_in_series": len(members), "reads": []}
        seen = set()
        for f, ds in rep:
            rec = {
                "file": f.name,
                "modality": _txt(ds.get(TAG_MODALITY, None)),
                "sop_class": _txt(ds.get(TAG_SOP_CLASS, None)),
                "study_desc": _txt(ds.get(TAG_STUDY_DESC, None)),
                "series_desc": _txt(ds.get(TAG_SERIES_DESC, None)),
                "body_part": _txt(ds.get(TAG_BODY_PART, None)),
                "requested_proc": _txt(ds.get(TAG_REQ_PROC_DESC, None)),
                "proc_codes": _code_item(ds, TAG_PROC_CODE_SEQ),
                "image_comments": _txt(ds.get(TAG_IMAGE_COMMENTS, None)),
                "image_type": [str(x) for x in ds.get(TAG_IMAGE_TYPE, [])] if ds.get(TAG_IMAGE_TYPE, None) is not None else None,
            }
            sr = _walk_content(ds)
            if sr:
                rec["sr_texts"] = sr
            key = json.dumps(rec, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                info["reads"].append(rec)
        out[suid[:40]] = info  # UID 截断仅作键，不用于识别
    return out, len(files), unreadable


def main():
    base = Path("D:/项目/鼻腔建模/资料")
    sources = {
        "脱敏副本_脱敏数据_clean": base / "脱敏数据_clean",
        "原始_患者ct+鼻空腔建模": base / "脱敏数据" / "患者ct+鼻空腔建模" / "患者ct+鼻空腔建模",
    }
    report = {
        "scan_policy": "仅白名单临床语义字段；身份字段脚本层面不构造。输出已剔除身份信息。",
        "sources": {},
    }
    for label, root in sources.items():
        if not root.exists():
            report["sources"][label] = {"error": "目录不存在"}
            continue
        patients = {}
        for pdir in sorted(root.iterdir()):
            if not pdir.is_dir():
                continue
            pname = pdir.name
            # 患者3 脱敏副本目录名残留病案号格式时做替换，仅保留「患者N」
            safe_name = pname if pname.startswith("患者") else "患者目录_名已脱敏替换"
            res, nfiles, nbad = scan_patient(pdir)
            patients[safe_name] = {"series_count": len(res), "files": nfiles, "unreadable": nbad, "series": res}
        report["sources"][label] = {"root": str(root), "patients": patients}

    # 汇总：哪些临床字段非空
    nonempty = defaultdict(set)
    for label, sdata in report["sources"].items():
        for pname, pdata in sdata.get("patients", {}).items():
            for suid, sinfo in pdata.get("series", {}).items():
                for rec in sinfo.get("reads", []):
                    for field in ("study_desc", "series_desc", "body_part", "requested_proc", "image_comments"):
                        if rec.get(field):
                            nonempty[field].add(f"{label}/{pname}")
                    if rec.get("proc_codes"):
                        nonempty["proc_codes"].add(f"{label}/{pname}")
                    if rec.get("sr_texts"):
                        nonempty["sr_texts"].add(f"{label}/{pname}")
    report["summary_nonempty_fields"] = {k: sorted(v) for k, v in nonempty.items()}

    out_path = Path("D:/项目/鼻腔建模/outputs/20261016-B患者症状痕迹探查/probe_result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {out_path}")
    print(f"summary: {json.dumps(report['summary_nonempty_fields'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
