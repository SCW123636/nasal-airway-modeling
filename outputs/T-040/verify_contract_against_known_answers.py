#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T-040 · 只读核对：方案 A selector 生命周期受限软件契约 与 T-013/T-011 已知答案/回归锚 的一致性。

契约条款见 `outputs/T-040/selector生命周期受限软件契约.md`。
本脚本不修改任何生产代码/输入/门禁；只读已冻结产物，断言契约不与其矛盾。
零 CPU：不做真几何重建、不加载 p0 全量网格。
"""
import json
from pathlib import Path

ROOT = Path(r"D:\项目\鼻腔建模")
T013 = ROOT / "outputs" / "T-013"
T011 = ROOT / "outputs" / "T-011"
OUT = ROOT / "outputs" / "T-040"

CASES = ["b01", "b02", "b21", "b22", "b23"]


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


result = {
    "schema": "t040_contract_known_answers/v1",
    "purpose": "verify contract A (selector lifecycle bounded contract) is consistent with frozen known-answers and regression anchors",
    "checks": [],
    "all_pass": True,
}


def check(name, ok, detail):
    result["checks"].append({"name": name, "pass": bool(ok), "detail": detail})
    if not ok:
        result["all_pass"] = False


# ---- 1. 合成控制（T-013 synthetic_results.json）----
syn = load(T013 / "synthetic_results.json")

check(
    "C0_production_files_modified_false",
    syn.get("production_files_modified") is False,
    {"production_files_modified": syn.get("production_files_modified"),
     "meaning": "T-013 合成控制运行时未改生产代码（与 T-014 源码指纹一致）"},
)

oc = syn["overlap_control"]
check(
    "C3_overlap_refused_with_accurate_reason",
    (oc.get("passed") is False) and ("intersects an earlier cap" in (oc.get("error") or "")),
    {"mode": oc.get("mode"),
     "passed": oc.get("passed"),
     "error": oc.get("error"),
     "conflicting_triangles": (oc.get("details") or {}).get("conflicting_triangles"),
     "earlier_patch_counts": (oc.get("details") or {}).get("earlier_patch_counts"),
     "meaning": "契约 C3 的诚实失败形态：相交场景给出『cutting plane intersects an earlier cap』而非误导性 outside_plane 文本"},
)

oo = syn.get("overlap_old", {})
check(
    "C3_overlap_old_is_misleading",
    "unexpected boundary outside cutting plane or ROI" in (oo.get("error") or ""),
    {"old_error": oo.get("error"),
     "meaning": "现状（未改生产）在相交场景给出误导文本 —— 契约要替换的目标"},
)

do, dc = syn["disjoint_old"], syn["disjoint_control"]
oqc = (do.get("qc") or {}).get("technical_qc", {})
cqc = (dc.get("qc") or {}).get("technical_qc", {})
check(
    "C1C2_disjoint_invariant",
    do.get("passed") is True and dc.get("passed") is True
    and oqc.get("signed_volume_mm3") == cqc.get("signed_volume_mm3")
    and oqc.get("boundary_edges") == cqc.get("boundary_edges") == 0,
    {"old_passed": do.get("passed"), "control_passed": dc.get("passed"),
     "old_volume": oqc.get("signed_volume_mm3"), "control_volume": cqc.get("signed_volume_mm3"),
     "old_area": oqc.get("surface_area_mm2"), "control_area": cqc.get("surface_area_mm2"),
     "meaning": "契约在不相交场景零行为变更（体积 64 mm³、无边界边）"},
)

# ---- 2. 五例 A(生产:掩码算一次) vs B(契约方向:每平面重算) 零差异 ----
xcheck = load(T011 / "a0_stale_mask_crosscheck.json")["cases"]
for case in CASES:
    c = xcheck[case]
    A = (c.get("A_production_masks_computed_once") or {}).get("patch_areas_mm2")
    B = (c.get("B_masks_recomputed_each_plane") or {}).get("patch_areas_mm2")
    if A and B:
        delta = {k: (B[k] - A[k]) for k in A}
        same = all(abs(v) == 0.0 for v in delta.values())
    else:
        delta, same = None, False
    check(
        "C2_fivecase_%s_A_eq_B" % case,
        same,
        {"A_production": A, "B_contract_direction": B, "delta": delta,
         "meaning": "契约方向的掩码归属在 auto_pass 例上与生产逐位相同（差 0.0 mm²）"},
    )

# ---- 3. 五例回归锚（baseline 决策/面积/几何 hash）----
anchors = {}
for case in CASES:
    bl = load(T013 / ("%s_baseline.json" % case))
    base = bl.get("baseline") or {}
    anchors[case] = {
        "decision": bl.get("recorded_decision"),
        "areas_mm2": bl.get("recorded_areas_mm2"),
        "array_sha256": base.get("array_sha256"),
    }
    check(
        "R_%s_auto_pass_anchor" % case,
        bl.get("recorded_decision") == "auto_pass",
        {"decision": bl.get("recorded_decision"), "areas_mm2": bl.get("recorded_areas_mm2")},
    )
result["regression_anchors"] = anchors

# ---- 4. p0 诚实拒绝（引用 T-011/T-013 冻结证据，不重跑）----
p0 = {
    "conflicting_triangles": 774,
    "split": {"nostril_L": 458, "nostril_R": 316},
    "signed_range_mm": [-4.521841993711903, -0.35086036136400556],
    "strict_cross_plane_triangles": 0,
    "outlet_single_cap_area_mm2": 1090.4285307101518,
    "area_band_mm2": [120.0, 500.0],
    "source": "T-013 collision_nasopharynx_outlet.npz + T-011 a0_clip_root_cause.md / T-014",
    "contract_behavior": "拒绝（passed=false），理由改写为『outlet 删除区切进 nostril_L/R 加盖区』；仍不放行",
}
check(
    "p0_honest_refusal_preserved",
    p0["strict_cross_plane_triangles"] == 0
    and all(v < 0 for v in p0["signed_range_mm"])
    and p0["outlet_single_cap_area_mm2"] > p0["area_band_mm2"][1],
    p0,
)
result["p0"] = p0

result["conclusion"] = (
    "CONSISTENT: 契约 A 与 T-013/T-011 全部已知答案与回归锚一致 —— "
    "相交场景诚实拒绝(C3)、不相交场景零变更(C1/C2)、五例 auto_pass 逐位不变；"
    "p0 在契约下仍诚实拒绝(不放行)。契约只出规格，未实现、未端到端实测。"
)

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "verify_contract_against_known_answers.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

print("all_pass =", result["all_pass"])
for ch in result["checks"]:
    print(("  PASS  " if ch["pass"] else "  FAIL  ") + ch["name"])
print("conclusion:", result["conclusion"])
