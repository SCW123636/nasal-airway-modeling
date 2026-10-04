# -*- coding: utf-8 -*-
"""把复核网页导出的 review_decisions.json 转换成求解管线可消费的确认件。

链路位置
    06_auto_landmarks/index.html (人看图 + 点选)
        -> review_decisions.json            （网页导出，只记录决定，不改任何几何）
        -> 本脚本                            （校验哈希 + 生成确认件）
        -> <case>/review_config_confirmed.json   喂 anatomy_barrier_seg.py --review
        -> <case>/contract_review_record.json    喂 cfd_contract 的 geometry.review

设计红线（不得改动）
    1. 本脚本不修改任何掩膜、不修改任何候选点、不修改 proposal 状态。
    2. oral_exclusion_confirmed / sinus_boundary_policy_confirmed 默认 False，
       且只能由人显式命令行确认。5 个标点全部接受 ≠ 口腔已排除、≠ 鼻窦边界已定。
    3. reviewed_geometry_sha256 必须由 --geometry 显式给出并现场计算，
       不允许凭空生成，也不允许把 provisional 掩膜冒充为最终几何。
    4. 任一哈希不匹配即整例失败，不降级、不跳过。

用法
    python work/lib/confirm_landmark_review.py \
        --decisions 06_auto_landmarks/review_decisions.json \
        --geometry work/05_ts_seg/p0/anatomy/main_narral_airway_T300_provisional.nii.gz

    # 人另外确认了口腔排除 / 鼻窦边界策略时（缺任一项，契约门禁仍锁）
    ... --confirm-oral-exclusion --confirm-sinus-policy
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import cfd_contract
except Exception:  # pragma: no cover
    cfd_contract = None

VALID_DECISIONS = {"accept", "reject", "adjust", "pending"}
BARRIER_PLANES = ("nostril_L", "nostril_R", "nasopharynx_outlet")
OBSERVATION_ONLY = {
    "posterior_choana_L": "后鼻孔为定位确认，不作为裁剪平面，也不构成鼻咽出口边界的独立证据",
    "posterior_choana_R": "后鼻孔为定位确认，不作为裁剪平面，也不构成鼻咽出口边界的独立证据",
}
GATE_BOUNDARIES = set(BARRIER_PLANES)


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_triplet(v):
    return (
        isinstance(v, list)
        and len(v) == 3
        and all(isinstance(x, (int, float)) and math.isfinite(float(x)) for x in v)
    )


def dist_mm(a, b):
    if not (is_triplet(a) and is_triplet(b)):
        return None
    return math.sqrt(sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)))


def now_iso():
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 校验：决定文件 vs 候选文件
# --------------------------------------------------------------------------
def load_proposal_bundle(html_path):
    """从复核网页嵌入的 review-data 里取候选包。

    必须用它、而不是 <case>/landmarks.json：网页导出时的校验基准是这份嵌入数据，
    decisions 里的 source_sha256 / proposal_sha256 也只对它成立。
    磁盘上的 landmarks.json 是更早的格式（landmarks 为 dict、无 proposal_sha256、
    无 source_sha256），拿它校验会全部误判为不匹配。
    """
    with open(html_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    m = re.search(
        r'<script id="review-data" type="application/json">(.*?)</script>', html, re.S
    )
    if not m:
        raise SystemExit("在 %s 中找不到 review-data 数据块" % html_path)
    return json.loads(m.group(1))


def validate(decisions, bundle):
    """返回 (per_case_records, problems, reviewer)。problems 非空即整批拒绝。"""
    problems = []
    if decisions.get("artifact_type") != "landmark_review_decisions":
        problems.append("decisions.artifact_type 不是 landmark_review_decisions")
    if decisions.get("coordinate_system") != "LPS" or decisions.get("unit") != "mm":
        problems.append("decisions 坐标系/单位必须是 LPS/mm")
    if not isinstance(decisions.get("cases"), list):
        problems.append("decisions.cases 缺失")
        return [], problems, None

    b_sha = bundle.get("proposal_bundle_sha256")
    d_sha = decisions.get("proposal_bundle_sha256")
    if b_sha and d_sha and b_sha != d_sha:
        problems.append("proposal_bundle_sha256 与网页候选包不一致，决定可能针对旧版本")

    by_case = {c.get("case"): c for c in bundle.get("cases", [])}
    reviewer = decisions.get("reviewer")
    records = []
    for dcase in decisions["cases"]:
        case = dcase.get("case")
        if not case:
            problems.append("存在缺 case 名的记录")
            continue
        prop = by_case.get(case)
        if prop is None:
            problems.append(f"[{case}] 网页候选包中无此例")
            continue
        if dcase.get("source_sha256") != prop.get("source_sha256"):
            problems.append(f"[{case}] source_sha256 与候选包不一致，决定可能针对旧版本")
            continue

        by_id = {l.get("id"): l for l in prop.get("landmarks", [])}
        items, seen = [], set()
        for d in dcase.get("decisions", []):
            lid = d.get("landmark_id")
            if lid in seen:
                problems.append(f"[{case}/{lid}] 重复记录")
                continue
            seen.add(lid)
            src = by_id.get(lid)
            if src is None:
                problems.append(f"[{case}/{lid}] 候选中无此点")
                continue
            if d.get("proposal_sha256") != src.get("proposal_sha256"):
                problems.append(f"[{case}/{lid}] proposal_sha256 不匹配")
                continue
            p = src.get("proposal", {})
            if json.dumps(p.get("point_lps_mm"), sort_keys=True) != json.dumps(
                d.get("original_point_lps_mm"), sort_keys=True
            ) or json.dumps(p.get("normal_lps"), sort_keys=True) != json.dumps(
                d.get("original_normal_lps"), sort_keys=True
            ):
                problems.append(f"[{case}/{lid}] 原始点/法向与候选不一致")
                continue
            decision = d.get("decision")
            if decision not in VALID_DECISIONS:
                problems.append(f"[{case}/{lid}] decision 非法: {decision}")
                continue
            if decision == "adjust" and not is_triplet(d.get("adjusted_point_lps_mm")):
                problems.append(f"[{case}/{lid}] adjust 缺有效 adjusted_point_lps_mm")
                continue
            if decision == "reject" and lid in BARRIER_PLANES:
                # 不阻止，但显式提示后果
                pass
            items.append(
                {
                    "landmark_id": lid,
                    "label_zh": d.get("label_zh"),
                    "decision": decision,
                    "original_point_lps_mm": p.get("point_lps_mm"),
                    "original_normal_lps": p.get("normal_lps"),
                    "final_point_lps_mm": (
                        d.get("adjusted_point_lps_mm")
                        if decision == "adjust"
                        else p.get("point_lps_mm")
                    ),
                    "final_normal_lps": (
                        d.get("adjusted_normal_lps")
                        if decision == "adjust" and is_triplet(d.get("adjusted_normal_lps"))
                        else p.get("normal_lps")
                    ),
                    "adjustment_distance_mm": (
                        dist_mm(p.get("point_lps_mm"), d.get("adjusted_point_lps_mm"))
                        if decision == "adjust"
                        else 0.0
                    ),
                    "original_status": d.get("original_status"),
                    "note": d.get("note") or "",
                    "updated_at": d.get("updated_at"),
                    "roi_lps_mm": p.get("roi_lps_mm"),
                    "keep_positive": True,
                    "localization_checks": p.get("consistency_checks", {}),
                }
            )
        missing = [k for k in by_id if k not in seen]
        records.append(
            {
                "case": case,
                "source_file": prop.get("source_file"),
                "source_sha256": prop.get("source_sha256"),
                "items": items,
                "undecided": missing,
            }
        )
    return records, problems, reviewer


# --------------------------------------------------------------------------
# 生成确认件
# --------------------------------------------------------------------------
def build_confirmed(records, reviewer, geo_digest, geo_path, oral, sinus, exported_at):
    """生成 anatomy_barrier_review/v2 确认件。"""
    out = {}
    for rec in records:
        planes = {}
        confirmed_boundaries = []
        rejected, pending = [], []
        for it in rec["items"]:
            lid = it["landmark_id"]
            if it["decision"] == "pending":
                pending.append(lid)
                continue
            if it["decision"] == "reject":
                rejected.append(lid)
                if lid in BARRIER_PLANES:
                    planes[lid] = {
                        "status": "rejected",
                        "point_lps_mm": it["original_point_lps_mm"],
                        "normal_lps": it["original_normal_lps"],
                        "review_note": it["note"],
                    }
                continue
            # accept / adjust
            planes[lid] = {
                "status": "confirmed",
                "point_lps_mm": it["final_point_lps_mm"],
                "normal_lps": it["final_normal_lps"],
                "roi_lps_mm": it["roi_lps_mm"],
                "keep_positive": True,
                "localization_checks": it["localization_checks"],
                "review": {
                    "method": "human",
                    "reviewer": reviewer,
                    "decision": it["decision"],
                    "adjustment_distance_mm": it["adjustment_distance_mm"],
                    "note": it["note"],
                    "reviewed_at": it["updated_at"] or exported_at,
                },
            }
            if lid in BARRIER_PLANES:
                confirmed_boundaries.append(lid)
        out[rec["case"]] = {
            "schema": "anatomy_barrier_review/v2",
            "coordinate_system": "LPS",
            "unit": "mm",
            "generated_by": "confirm_landmark_review",
            "generated_at": now_iso(),
            "case": rec["case"],
            "source_file": rec["source_file"],
            "source_sha256": rec["source_sha256"],
            "reviewer": reviewer,
            "planes_lps": planes,
            "confirmed_boundaries": sorted(confirmed_boundaries),
            "observations_not_used_as_planes": {
                k: OBSERVATION_ONLY[k] for k in OBSERVATION_ONLY if k in planes
            },
            "rejected": rejected,
            "undecided": rec["undecided"],
            "pending": pending,
            "boundary_confirmations": {
                "oral_exclusion_confirmed": bool(oral),
                "sinus_boundary_policy_confirmed": bool(sinus),
                "source": "explicit_cli_flag"
                if (oral or sinus)
                else "not_confirmed_by_landmark_review",
            },
            "geometry_binding": {
                "reviewed_geometry_sha256": geo_digest,
                "geometry_file": os.path.abspath(geo_path) if geo_path else None,
                "geometry_is_provisional": bool(
                    geo_path and "provisional" in os.path.basename(geo_path).lower()
                ),
            },
            "note": (
                "仅确认解剖标点定位。口腔排除与鼻窦边界策略不在本文件范围内；"
                "未显式确认时二者为 false，契约门禁不解锁。"
            ),
        }
    return out


def build_contract_record(conf, case, reviewer, geo_digest, geo_path, oral, sinus):
    """生成 cfd_contract 要求的 geometry.review 形状。"""
    return {
        "schema": "cfd_geometry_review/v1",
        "generated_by": "confirm_landmark_review",
        "generated_at": now_iso(),
        "case_id": case,
        "status": "confirmed" if conf["confirmed_boundaries"] else "not_confirmed",
        "method": "human",
        "reviewer": reviewer,
        "reviewed_at": now_iso(),
        "record_file": None,  # 落盘后回填
        "reviewed_geometry_sha256": geo_digest,
        "confirmed_boundaries": conf["confirmed_boundaries"],
        "oral_exclusion_confirmed": bool(oral),
        "sinus_boundary_policy_confirmed": bool(sinus),
        "scope": "landmark localization review only",
        "geometry_file": os.path.abspath(geo_path) if geo_path else None,
        "geometry_is_provisional": bool(
            geo_path and "provisional" in os.path.basename(geo_path).lower()
        ),
        "not_covered_by_this_review": [
            "oral_exclusion",
            "sinus_boundary_policy",
            "nasal_valve",
            "olfactory_cleft",
            "sinus_ostia_status",
        ],
    }


def gate_report(record, digest):
    """用 cfd_contract 自己的判据列剩余缺口，不自创标准。"""
    if cfd_contract is None:
        return None
    geometry = {
        "kind": "patient",
        "case_id": record["case_id"],
        "source_file": record["geometry_file"] or "",
        "sha256": digest,
        "review": {
            "status": record["status"],
            "method": record["method"],
            "reviewer": record["reviewer"],
            "reviewed_at": record["reviewed_at"],
            "record_file": record["record_file"] or "",
            "reviewed_geometry_sha256": record["reviewed_geometry_sha256"],
            "confirmed_boundaries": record["confirmed_boundaries"],
            "oral_exclusion_confirmed": record["oral_exclusion_confirmed"],
            "sinus_boundary_policy_confirmed": record["sinus_boundary_policy_confirmed"],
        },
    }
    return cfd_contract._patient_geometry_issues(geometry)


# --------------------------------------------------------------------------
def main(argv=None):
    root = os.path.dirname(HERE)  # work/
    ap = argparse.ArgumentParser(description="复核决定 -> 求解管线确认件")
    ap.add_argument("--decisions", required=True, help="网页导出的 review_decisions.json")
    ap.add_argument("--proposals-html", default=None,
                    help="复核网页 index.html（内含 review-data 候选包），默认 06_auto_landmarks/index.html")
    ap.add_argument("--out-dir", default=None, help="默认写到 proposals-dir/<case>/")
    ap.add_argument("--geometry", default=None, help="被复核的几何文件（掩膜/表面），用于 sha256 绑定")
    ap.add_argument("--reviewer", default=None, help="决定文件缺 reviewer 时的兜底标识")
    ap.add_argument("--case", action="append", default=None, help="只处理指定例，可多次给")
    ap.add_argument("--confirm-oral-exclusion", action="store_true",
                    help="人已另行确认口腔排除（不是标点定位，需独立判断）")
    ap.add_argument("--confirm-sinus-policy", action="store_true",
                    help="人已另行确认鼻窦边界策略（不是标点定位，需独立判断）")
    args = ap.parse_args(argv)

    props_dir = os.path.join(root, "06_auto_landmarks")
    html_path = args.proposals_html or os.path.join(props_dir, "index.html")
    bundle = load_proposal_bundle(html_path)
    decisions = load_json(args.decisions)
    records, problems, reviewer = validate(decisions, bundle)
    reviewer = reviewer or args.reviewer
    if problems:
        print("❌ 校验未通过，未产出任何确认件：")
        for p in problems:
            print("   -", p)
        return 2
    if not reviewer:
        print("❌ 缺 reviewer（决定文件里为空且未给 --reviewer）；契约要求具名复核人。")
        return 2

    digest = None
    if args.geometry:
        if not os.path.isfile(args.geometry):
            print(f"❌ --geometry 不存在: {args.geometry}")
            return 2
        digest = sha256_file(args.geometry)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            print("❌ geometry sha256 计算异常")
            return 2

    if args.case:
        records = [r for r in records if r["case"] in set(args.case)]

    exported_at = decisions.get("exported_at") or now_iso()
    confirmed = build_confirmed(
        records, reviewer, digest, args.geometry,
        args.confirm_oral_exclusion, args.confirm_sinus_policy, exported_at,
    )

    print(f"✅ 校验通过：{len(records)} 例，reviewer = {reviewer}")
    if digest:
        print(f"   绑定几何 sha256 = {digest[:16]}…")
    else:
        print("   ⚠ 未给 --geometry：reviewed_geometry_sha256 为空，契约门禁必然不通过")

    for rec in records:
        case = rec["case"]
        conf = confirmed[case]
        out_dir = args.out_dir or os.path.join(props_dir, case)
        os.makedirs(out_dir, exist_ok=True)
        conf_path = os.path.join(out_dir, "review_config_confirmed.json")
        with open(conf_path, "w", encoding="utf-8") as fh:
            json.dump(conf, fh, ensure_ascii=False, indent=1)

        record = build_contract_record(
            conf, case, reviewer, digest, args.geometry,
            args.confirm_oral_exclusion, args.confirm_sinus_policy,
        )
        rec_path = os.path.join(out_dir, "contract_review_record.json")
        record["record_file"] = os.path.abspath(rec_path)
        with open(rec_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=1)

        issues = gate_report(record, digest)
        ok = (issues == [])
        summary = {
            "case": case,
            "confirmed_boundaries": conf["confirmed_boundaries"],
            "rejected": conf["rejected"],
            "undecided": conf["undecided"],
            "contract_gate_satisfied": ok,
            "remaining_issues": issues,
        }
        with open(os.path.join(out_dir, "review_gate_status.json"), "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1)

        print(f"\n[{case}] 已确认边界: {conf['confirmed_boundaries'] or '（无）'}")
        for it in rec["items"]:
            tag = {"accept": "接受", "reject": "拒绝", "adjust": "调整", "pending": "待定"}[it["decision"]]
            extra = (
                f"（位移 {it['adjustment_distance_mm']:.2f} mm）" if it["decision"] == "adjust" else ""
            )
            print(f"   {it['label_zh'] or it['landmark_id']}: {tag}{extra}")
        if conf["undecided"]:
            print(f"   ⚠ 未作决定: {conf['undecided']}")
        print(f"   确认件: {conf_path}")
        print(f"   契约记录: {rec_path}")
        if ok:
            print("   契约门禁: ✅ 通过")
        else:
            print("   契约门禁: ⛔ 未解锁，剩余项：")
            for it in issues or []:
                print("       -", it)
    return 0


if __name__ == "__main__":
    sys.exit(main())
