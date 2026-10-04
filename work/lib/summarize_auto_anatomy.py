"""Summarize existing landmark proposals and QC without modifying either input.

Only same-scan distances and palate-frame coordinates are compared for p3t1/p3.
There is no patient registration, reference annotation, or clinical validation.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COHORT = {
    "p0": ("患者0", "单次扫描"), "p1": ("患者1", "单次扫描"),
    "p2": ("患者2", "单次扫描"), "p3": ("患者3", "t2"), "p3t1": ("患者3", "t1"),
}
LANDMARK_LABELS = {
    "nostril_L": "左鼻孔入口 (left nostril inlet)",
    "nostril_R": "右鼻孔入口 (right nostril inlet)",
    "posterior_choana_L": "左后鼻孔候选 (left posterior choana)",
    "posterior_choana_R": "右后鼻孔候选 (right posterior choana)",
    "nasopharynx_outlet": "鼻咽出口候选 (nasopharynx outlet)",
}
REASON_LABELS = {
    "all_three_thresholds_found": "−300/−350/−400 HU 未全部得到候选",
    "enough_patch_samples": "接触面/表面候选采样数不足",
    "plane_residual_within_engineering_limit": "平面拟合残差超出工程阈值",
    "threshold_position_stable": "阈值变化下点位漂移超出工程阈值",
    "threshold_direction_stable": "阈值变化下法向变化超出工程阈值",
    "no_competing_large_patch": "存在较大的竞争候选块",
}
ANATOMY_LABELS = {
    "nasal_cavity_left": "左鼻腔 (left nasal cavity)", "nasal_cavity_right": "右鼻腔 (right nasal cavity)",
    "nasopharynx": "鼻咽 (nasopharynx)", "oropharynx": "口咽 (oropharynx)",
    "hard_palate": "硬腭 (hard palate)", "soft_palate": "软腭 (soft palate)",
}
UNRESOLVED = [
    "鼻阀 (nasal valve)", "鼻阈 (limen nasi)", "嗅裂 (olfactory cleft)",
    "鼻甲 (turbinate) 间隙", "鼻窦 (paranasal sinus) 自然开口状态",
]


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def vector(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    result = [number(x) for x in value]
    return result if all(x is not None for x in result) else None


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def local_frame(frame):
    origin = vector(frame.get("origin_lps_mm"))
    basis = [vector(frame.get(k)) for k in ("left_lps", "posterior_lps", "superior_lps")]
    if origin is None or any(v is None for v in basis):
        return {"usable": False, "reason": "局部框架缺失或包含非有限坐标"}
    error = max(abs(dot(x, y) - (1.0 if i == j else 0.0))
                for i, x in enumerate(basis) for j, y in enumerate(basis))
    return {"usable": error <= 1e-4, "origin_lps_mm": origin, "basis_rows_left_posterior_superior": basis,
            "orthonormal_error": error, "axes": ["left", "posterior", "superior"],
            "unit": "mm", "reason": None if error <= 1e-4 else "局部框架非正交/非单位基底"}


def point_in_frame(point, frame):
    point = vector(point)
    if point is None or not frame.get("usable"):
        return None
    offset = [p-o for p, o in zip(point, frame["origin_lps_mm"])]
    return [dot(offset, axis) for axis in frame["basis_rows_left_posterior_superior"]]


def qc_geometry_matches(source, qc):
    """Check metadata only; this does not verify image content identity."""
    try:
        sg, qg = source["source_geometry"], qc["ct_geometry"]
        if source.get("coordinate_system") != "LPS" or source.get("unit") != "mm":
            return False
        if qg.get("coordinate_system") != "LPS" or qg.get("unit") != "mm":
            return False
        if sg["size_xyz"] != qg["size_xyz"]:
            return False
        spacing, origin, direction = qg["spacing_xyz_mm"], qg["origin_xyz_mm"], qg["direction"]
        expected = [[direction[3*r+c] * spacing[c] for c in range(3)] + [origin[r]] for r in range(3)]
        expected.append([0, 0, 0, 1])
        affine = sg["affine_4x4_LPS"]
        return all(number(affine[r][c]) is not None and abs(affine[r][c] - expected[r][c]) <= 1e-5
                   for r in range(4) for c in range(4))
    except (KeyError, IndexError, TypeError):
        return False


def load_json(path):
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("JSON 根节点必须为对象")
    return data, hashlib.sha256(raw).hexdigest()


def summarize_point(key, value, frame):
    evidence = value.get("evidence") or {}
    variants = [v for v in evidence.get("threshold_variants", []) if isinstance(v, dict)]
    ratios = [number(v.get("secondary_patch_ratio")) for v in variants]
    ratios = [r for r in ratios if r is not None]
    base_ratio = number(evidence.get("secondary_patch_ratio"))
    if not ratios and base_ratio is not None:
        ratios = [base_ratio]
    status = value.get("status", "missing")
    reasons = list(value.get("review_reasons") or [])
    if status not in ("proposed", "needs_review", "unavailable"):
        reasons.append("来源状态不是已知自动候选状态；汇总器不予升级或确认")
    point = vector(value.get("point_lps_mm"))
    if status == "proposed" and point is None:
        reasons.append("proposed 状态缺少有效点位")
    return {
        "label": LANDMARK_LABELS.get(key, key), "status": status,
        "point_lps_mm": point, "normal_lps": vector(value.get("normal_lps")),
        "palate_frame_left_posterior_superior_mm": point_in_frame(point, frame),
        "threshold_drift_mm": number(evidence.get("threshold_drift_mm")),
        "threshold_normal_change_deg": number(evidence.get("threshold_normal_change_deg")),
        "secondary_patch_ratio_base": base_ratio,
        "secondary_patch_ratio_max_across_thresholds": max(ratios) if ratios else None,
        "patch_count_base": evidence.get("patch_count"),
        "threshold_variants_found": len(variants), "samples_base": evidence.get("samples"),
        "plane_rms_mm": number(evidence.get("rms_mm")),
        "consistency_checks": value.get("consistency_checks") or {},
        "review_reasons": list(dict.fromkeys(str(x) for x in reasons)),
        "clinical_validation": "not_validated", "is_human_confirmed": False,
        "source_clinical_validation": value.get("clinical_validation"),
    }


def summarize_case(key, base, qc_base):
    lm_path, qc_path = base / key / "landmarks.json", qc_base / key / ("gate_" + key + ".json")
    result = {"case": key, "patient": COHORT.get(key, (None, None))[0],
              "timepoint": COHORT.get(key, (None, None))[1], "input_errors": [],
              "source_landmarks": str(lm_path), "source_qc": str(qc_path), "landmarks": {}, "review_queue": []}
    try:
        source, lm_hash = load_json(lm_path)
        result.update({"source_landmarks_sha256": lm_hash, "source_schema": source.get("schema"),
                       "proposal_hash": source.get("proposal_hash")})
    except (OSError, ValueError) as exc:
        result["input_errors"].append("无法读取标定结果: " + str(exc))
        return result
    try:
        qc, qc_hash = load_json(qc_path)
        result["source_qc_sha256"] = qc_hash
    except (OSError, ValueError) as exc:
        result["input_errors"].append("无法读取 QC: " + str(exc))
        qc = {}
    if source.get("case") != key or qc and qc.get("case") != key:
        result["input_errors"].append("文件夹病例 ID 与 JSON case 字段不一致")
    if source.get("coordinate_system") != "LPS" or source.get("unit") != "mm":
        result["input_errors"].append("标定坐标不是 LPS/mm")
    frame = local_frame(source.get("anatomy_frame") or {})
    if result["input_errors"] or not frame["usable"]:
        frame["usable"] = False
    result["palate_local_frame"] = frame
    if not frame["usable"]:
        result["input_errors"].append("硬腭 (hard palate) 局部框架不可用于坐标比较")
    result["qc_geometry_consistent_with_landmark_source"] = qc_geometry_matches(source, qc)
    if not result["qc_geometry_consistent_with_landmark_source"]:
        result["input_errors"].append("QC 与标定源的空间几何元数据不一致或不完整")
    candidate = qc.get("semantic_air_candidate") or {}
    fov = {name: detail.get("fov_boundary_contact") for name, detail in (qc.get("per_class") or {}).items()
           if (detail.get("fov_boundary_contact") or {}).get("touches_image_boundary")}
    result["data_integrity"] = {"status": qc.get("data_integrity_status", "unavailable"),
        "qc_overall_status": qc.get("overall_status", "unavailable"), "audit_version": qc.get("audit_version"),
        "hard_failures": qc.get("hard_failures", []), "warnings": qc.get("warnings", []),
        "fov_boundary_contacts": fov, "candidate_volume_mL": candidate.get("volume_mL"),
        "components_6_connected": candidate.get("components_6_connected"),
        "components_26_connected": candidate.get("components_26_connected"),
        "nasal_to_nasopharynx_paths": qc.get("nasal_to_nasopharynx_paths"),
        "medical_or_cfd_validation_pass": False}
    source_points = source.get("landmarks") or {}
    for name in dict.fromkeys(list(LANDMARK_LABELS) + list(source_points)):
        point = summarize_point(name, source_points.get(name, {}), frame)
        if name not in source_points:
            result["input_errors"].append("缺少预期候选记录: " + name)
        result["landmarks"][name] = point
        if point["status"] != "proposed" or point["review_reasons"]:
            result["review_queue"].append({"landmark": name, "label": point["label"],
                "status": point["status"], "reasons": point["review_reasons"] or ["没有可用候选"]})
    result["source_review_queue"] = source.get("review_queue", [])
    result["status_counts"] = dict(Counter(p["status"] for p in result["landmarks"].values()))
    result["unresolved_anatomy"] = UNRESOLVED
    return result


def within_scan_distances(case):
    points = case.get("landmarks", {})
    pairs = {
        "left_inlet_to_choana": ("nostril_L", "posterior_choana_L"),
        "right_inlet_to_choana": ("nostril_R", "posterior_choana_R"),
        "bilateral_inlet_separation": ("nostril_L", "nostril_R"),
        "bilateral_choana_separation": ("posterior_choana_L", "posterior_choana_R"),
    }
    result = {}
    for name, (start, end) in pairs.items():
        a, b = points.get(start, {}), points.get(end, {})
        pa, pb = a.get("point_lps_mm"), b.get("point_lps_mm")
        result[name] = {"distance_mm": distance(pa, pb) if pa is not None and pb is not None else None,
                        "endpoints": [start, end], "endpoint_statuses": [a.get("status"), b.get("status")],
                        "definition": "same-scan Euclidean candidate-point distance; not centerline length"}
    return result


def longitudinal_descriptors(cases):
    result = {"status": "descriptive_only_without_independent_registration",
        "patient": "患者3", "scan_t1": "p3t1", "scan_t2": "p3",
        "axes": ["left", "posterior", "superior"], "unit": "mm", "scans": {},
        "raw_cross_scan_LPS_subtraction_performed": False,
        "independent_registration_performed": False, "longitudinal_accuracy_estimated": False,
        "treatment_effect_inferred": False,
        "limitations": ["分别投影至各自硬腭 (hard palate) 局部框架；并非独立影像配准。",
                        "局部框架仍依赖本次语义分割和鼻腔/鼻咽相对位置，不能当作稳定金标准。",
                        "同扫描候选点间欧氏距离不是中心线长度或气流阻力。",
                        "扫描协议、阈值、框架估计和候选定义可产生差异；不据此推断手术疗效。"]}
    for key in ("p3t1", "p3"):
        case = cases.get(key, {})
        result["scans"][key] = {
            "palate_frame_coordinates_mm": {name: {"coordinates": p.get("palate_frame_left_posterior_superior_mm"),
                "candidate_status": p["status"]} for name, p in case.get("landmarks", {}).items()},
            "within_scan_distances": within_scan_distances(case)}
    result["available_timepoints"] = [key for key in ("p3t1", "p3") if cases.get(key, {}).get("landmarks")]
    if len(result["available_timepoints"]) != 2:
        result["status"] = "unavailable_requires_p3t1_and_p3"
    return result


def build_summary(base, qc_base, case_keys=None):
    base, qc_base = Path(base).resolve(), Path(qc_base).resolve()
    extra = sorted(p.parent.name for p in base.glob("*/landmarks.json") if p.parent.name not in COHORT)
    selected = list(dict.fromkeys(case_keys)) if case_keys else list(COHORT) + extra
    if any(Path(key).name != key or key in (".", "..") for key in selected):
        raise ValueError("case 必须为单级扫描目录名")
    extra = [key for key in selected if key not in COHORT]
    cases = {key: summarize_case(key, base, qc_base) for key in selected}
    schemas = sorted({c.get("source_schema") for c in cases.values() if c.get("source_schema")})
    problems = [key + ": " + reason for key, c in cases.items() for reason in c["input_errors"]]
    if len(schemas) > 1:
        problems.append("来源标定结果使用多个 schema 版本，不能视为统一算法的一次回测")
    if extra:
        problems.append("发现未登记患者关系的额外扫描: " + ", ".join(extra))
    counts = Counter(p["status"] for c in cases.values() for p in c["landmarks"].values())
    return {"schema": "auto_anatomy_summary/v1", "generated_at": datetime.now().astimezone().isoformat(),
        "base_dir": str(base), "qc_base": str(qc_base), "assembly_status": "complete" if not problems else "incomplete",
        "input_problems": problems, "expected_cohort": {"patients": 4, "scans": 5},
        "selected_cases": selected, "case_subset_requested": case_keys is not None,
        "known_cases_not_selected": [key for key in COHORT if key not in selected],
        "loaded_scan_count": sum("source_landmarks_sha256" in c for c in cases.values()),
        "loaded_known_patient_count": len({c["patient"] for c in cases.values() if c["patient"] and "source_landmarks_sha256" in c}),
        "source_schemas": schemas, "landmark_status_counts": dict(counts),
        "cases": cases, "p3_timepoint_descriptors": longitudinal_descriptors(cases),
        "validation": {"human_reference_annotations_available": False, "initial_clinical_validation_performed": False,
                       "accuracy_estimated": False, "medical_or_cfd_validation_pass": False,
                       "interpretation": "threshold stability is repeatability evidence, not anatomical accuracy"},
        "unresolved_anatomy": UNRESOLVED}


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def fmt(value, digits=3):
    return "—" if number(value) is None else f"{value:.{digits}f}"


def coords(value):
    return "—" if value is None else "(" + ", ".join(fmt(v) for v in value) + ")"


def qc_warning_text(value):
    text = str(value)
    for side, cn in (("left", "左"), ("right", "右")):
        if text == side + " nasal air contains components disconnected from nasopharynx in 6-neighborhood":
            return cn + "鼻腔 (nasal cavity) 有部分分量在 6 邻域下不能到达鼻咽 (nasopharynx)；需结合体积判断"
    if text.startswith("label touches image boundary: "):
        text = "标签触及图像边界：" + text.removeprefix("label touches image boundary: ")
    for key, label in ANATOMY_LABELS.items():
        text = text.replace(key, label)
    return text


def render_markdown(summary):
    counts = summary["landmark_status_counts"]
    lines = ["# 自动定位回测报告", "", "生成时间：" + summary["generated_at"], "",
        "本项目登记 4 位患者、5 次扫描：p0、p1、p2、p3（患者3_t2）和 p3t1（同一患者_t1）。"
        f"本报告实际读入 {summary['loaded_scan_count']} 次扫描、{summary['loaded_known_patient_count']} 位已登记患者；汇总状态 `{summary['assembly_status']}`。",
        "", "**初次仍无人工真值：未进行人工参考标注对照，未估计定位准确率、纵向精度或手术疗效。**"
        "三个 HU 阈值间稳定只反映当前算法的重复性，稳定不等于准确。`proposed` 为候选，`needs_review` 为异常复核，`unavailable` 为暂缺；均不是人工确认或 CFD 放行。",
        "", f"候选计数：proposed {counts.get('proposed', 0)}；needs_review {counts.get('needs_review', 0)}；unavailable {counts.get('unavailable', 0)}。", ""]
    if summary["case_subset_requested"]:
        lines += ["本次显式纳入：" + "、".join(summary["selected_cases"]) + "；未纳入的既有扫描不参与本批计数。", ""]
    if summary["input_problems"]:
        lines += ["## 输入完整性问题", ""] + ["- " + cell(x) for x in summary["input_problems"]] + [""]
    lines += ["## 数据与候选汇总", "", "| 扫描 | 数据完整性 | QC 状态 | proposed / needs_review / unavailable | 6 / 26 分量数 | FOV 标签触边 |", "|---|---|---|---:|---:|---|"]
    for key, case in summary["cases"].items():
        qc, sc = case.get("data_integrity", {}), case.get("status_counts", {})
        c6, c26 = qc.get("components_6_connected") or {}, qc.get("components_26_connected") or {}
        fov = "; ".join(ANATOMY_LABELS.get(name, name) + ": " + ",".join(v.get("index_faces", [])) for name, v in qc.get("fov_boundary_contacts", {}).items()) or "无或不可用，见 JSON"
        lines.append(f"| {key} | {qc.get('status', 'unavailable')} | {qc.get('qc_overall_status', 'unavailable')} | {sc.get('proposed',0)} / {sc.get('needs_review',0)} / {sc.get('unavailable',0)} | {c6.get('count','—')} / {c26.get('count','—')} | {cell(fov)} |")
    lines += ["", "QC 数据完整性通过只说明输入可继续处理。非零微小分量数不直接等于重大阻塞；6/26 邻域路径也没有验证已确认入口到出口的有效通道口径。"
              "标签触及扫描边界仅为覆盖提示，不能单独证明解剖截断。", ""]
    for key, case in summary["cases"].items():
        lines += ["## " + key + "：逐点结果与异常队列", "", "| 标定点 | 状态 | 阈值漂移 mm | 法向变化 ° | 竞争块比例（最大） | 基准候选块数 | 平面 RMS mm |", "|---|---|---:|---:|---:|---:|---:|"]
        for point in case["landmarks"].values():
            lines.append("| " + " | ".join([cell(point["label"]), point["status"], fmt(point["threshold_drift_mm"]),
                fmt(point["threshold_normal_change_deg"]), fmt(point["secondary_patch_ratio_max_across_thresholds"]),
                str(point["patch_count_base"]) if point["patch_count_base"] is not None else "—", fmt(point["plane_rms_mm"])]) + " |")
        lines += ["", "异常候选队列：", ""]
        if not case["review_queue"]:
            lines.append("- 未报告工程异常候选；仍未完成初次医学真值验证。")
        for item in case["review_queue"]:
            reasons = [REASON_LABELS.get(r, r) for r in item["reasons"]]
            lines.append("- " + item["label"] + "：" + item["status"] + "；" + cell("；".join(reasons)))
        qc = case.get("data_integrity", {})
        lines += ["", "数据完整性与 QC 提示：", ""]
        for reason in case["input_errors"] + qc.get("hard_failures", []):
            lines.append("- 输入/硬失败：" + cell(reason))
        if not case["input_errors"] and not qc.get("hard_failures"):
            lines.append("- 未报告数据完整性硬失败。")
        lines += ["- QC 提示：" + cell(qc_warning_text(w)) for w in qc.get("warnings", [])]
        lines += ["", "源版本：`" + str(case.get("source_schema")) + "`；proposal_hash：`" + str(case.get("proposal_hash")) + "`。", ""]
    lines += ["## 患者3双时点：局部描述性比较", "",
        "以下坐标分别投影到各扫描的硬腭 (hard palate) 局部框架，轴序为左、后、上，单位 mm。"
        "框架本身依赖语义分割和鼻腔/鼻咽关系，未做独立影像配准。未将两次扫描的原始 LPS 坐标直接相减，也不把此表称为纵向精度或术后疗效。", "",
        "| 候选点 | p3t1 局部坐标 | p3t1 状态 | p3 局部坐标 | p3 状态 |", "|---|---|---|---|---|"]
    descriptors = summary["p3_timepoint_descriptors"]["scans"]
    if summary["p3_timepoint_descriptors"]["status"] == "unavailable_requires_p3t1_and_p3":
        lines += ["| 本批未同时纳入两个时点 | — | — | — | — |"]
    for key, label in LANDMARK_LABELS.items():
        p1 = descriptors["p3t1"]["palate_frame_coordinates_mm"].get(key, {})
        p2 = descriptors["p3"]["palate_frame_coordinates_mm"].get(key, {})
        lines.append(f"| {label} | {coords(p1.get('coordinates'))} | {p1.get('candidate_status','missing')} | {coords(p2.get('coordinates'))} | {p2.get('candidate_status','missing')} |")
    labels = {"left_inlet_to_choana": "左入口—左后鼻孔", "right_inlet_to_choana": "右入口—右后鼻孔",
              "bilateral_inlet_separation": "左右入口间距", "bilateral_choana_separation": "左右后鼻孔间距"}
    lines += ["", "以下均为同一次扫描内候选点间欧氏距离，不是中心线长度。候选状态见上表，异常候选参与的距离仍属于待复核描述。", "",
              "| 同扫描点间距 | p3t1 mm | p3 mm |", "|---|---:|---:|"]
    for key, label in labels.items():
        a = descriptors["p3t1"]["within_scan_distances"][key]["distance_mm"]
        b = descriptors["p3"]["within_scan_distances"][key]["distance_mm"]
        lines.append(f"| {label} | {fmt(a)} | {fmt(b)} |")
    lines += ["", "## 未解决结构与人工最小化边界", ""] + ["- " + name + "：当前未有经人工真值验证的自动定位/开口判断。" for name in UNRESOLVED]
    lines += ["", "鼻孔入口仍是局部影像与有限空气射线支持的候选；外界空气终点与真实鼻翼缘未被独立标注。"
              "鼻咽出口使用鼻咽/口咽语义界面，不能当成已确认软腭 (soft palate) 游离缘层面。",
              "", "当前可用异常队列集中复核工程失败或不稳定候选；首次建立准确性仍需参考标注，尚不能由这批无真值数据计算自动免复核率。"
              "任何候选均未在汇总时升级为 confirmed；未生成正式 CFD 放行结论。", ""]
    return "\n".join(lines)


def write_outputs(summary, base):
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    paths = [base / "auto_anatomy_summary.json", base / "自动定位回测报告.md"]
    content = [json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", render_markdown(summary)]
    for path, text in zip(paths, content):
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(ROOT / "work" / "06_auto_landmarks"))
    parser.add_argument("--qc-base", default=str(ROOT / "work" / "05_ts_seg"))
    parser.add_argument("--cases", nargs="+", help="Only include these scan directories (for a successful runner batch)")
    args = parser.parse_args(argv)
    summary = build_summary(args.base_dir, args.qc_base, args.cases)
    paths = write_outputs(summary, args.base_dir)
    print(json.dumps({"assembly_status": summary["assembly_status"],
        "landmark_status_counts": summary["landmark_status_counts"], "input_problems": summary["input_problems"],
        "outputs": [str(p.resolve()) for p in paths]}, ensure_ascii=False, indent=2))
    return 0 if summary["assembly_status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
