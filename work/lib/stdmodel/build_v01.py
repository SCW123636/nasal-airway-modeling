# -*- coding: utf-8 -*-
"""build_v01.py —— 一键装配标准模型 v0.1（CLI）。

    python -m stdmodel.build_v01            # 全量：G 24 例 + C 3 例
    python -m stdmodel.build_v01 --cases b15 b01

流程（B2 已知答案门在最前，不过不出模型）：
1. 证据登记表加载校验
2. G/C 特征行装配（缺 artifact 的例记账跳过，不崩）
3. 已知答案 CI 门：b15/b01/b02 对 T-058 汇总裁决逐位比对
4. S1 常模计算（G 层有效 n + C 层 n=3 切片）
5. 落盘：feature_table.json/csv + norm.json + profiles/*.md + model_card.md
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import CLINICAL_STATUS, MODEL_VERSION, SCHEMA_VERSION
from . import cfd_features, evidence, geom_features, known_answer, s1_norm
from .profile import render_case_markdown
from .schema import FEATURES

ROOT = Path("D:/项目/鼻腔建模")
OUT = ROOT / "outputs/stdmodel_v01"
ALL_CASES = [f"b{i:02d}" for i in range(1, 25)]
CFD_CASES = cfd_features.CFD_CASES

G_FEATURES = [f for f, d in FEATURES.items() if d["layer"] == "G"]
C_FEATURES = [f for f, d in FEATURES.items() if d["layer"] == "C"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=None)
    ap.add_argument("--no-gate", action="store_true", help="跳过已知答案门（仅调试用，记录在案）")
    args = ap.parse_args()
    cases = args.cases or ALL_CASES

    reg = evidence.load_registry()
    print(f"[1] 证据登记表 OK：{len(reg['entries'])} 条"
          f"（E1={len(evidence.anchors(reg))} E2={len(evidence.associations(reg))} "
          f"反例={len(evidence.counterexamples(reg))}）")

    g_rows, skipped = [], []
    for c in cases:
        try:
            g_rows.append(geom_features.build_case_row(c))
            print(f"[2] G {c} OK")
        except Exception as exc:  # 缺 artifact 等：记账跳过，不崩
            skipped.append({"case": c, "layer": "G", "why": f"{type(exc).__name__}: {exc}"})
            print(f"[2] G {c} SKIP: {exc}")
    c_rows = []
    for c in CFD_CASES:
        if c in cases or not cases:
            try:
                c_rows.append(cfd_features.build_case_row(c))
                print(f"[2] C {c} OK")
            except Exception as exc:
                skipped.append({"case": c, "layer": "C", "why": f"{type(exc).__name__}: {exc}"})
                print(f"[2] C {c} SKIP: {exc}")

    # ---- B2 已知答案门（最前判定；不过不出模型）----
    actual = {}
    for r in c_rows:
        actual[r["case"]] = {**r["features"]}
    for r in g_rows:
        f = r["features"]
        actual[r["case"]] = {
            **actual.get(r["case"], {}),
            "nostril_L_mm2": f["nostril_area_L_mm2"],
            "nostril_R_mm2": f["nostril_area_R_mm2"],
            "outlet_opening_mm2": f["outlet_area_mm2"],
        }
    if args.no_gate:
        gate_ok, problems = True, ["GATE SKIPPED BY FLAG --no-gate"]
        print("[3] ⚠ 已知答案门被 --no-gate 跳过（仅调试）")
    else:
        gate_ok, problems = known_answer.gate(actual)
    gate_report = {
        "gate": "known_answer/T-058汇总裁决",
        "passed": gate_ok,
        "problems": problems,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if not gate_ok:
        print("[3] ✗ 已知答案门不过——不出模型：")
        for p in problems:
            print("   ", p)
        (OUT / "known_answer_failure.json").parent.mkdir(parents=True, exist_ok=True)
        with open(OUT / "known_answer_failure.json", "w", encoding="utf-8") as f:
            json.dump(gate_report, f, ensure_ascii=False, indent=2)
        return 2
    print(f"[3] 已知答案门 PASS（{len(known_answer.FIXTURES_T058)} 例逐位）")

    # ---- S1 常模 ----
    norm = s1_norm.norm_all(g_rows, c_rows, G_FEATURES, C_FEATURES)
    g_eff = next(iter(norm["G"]["features"].values()))["n"] if norm["G"]["features"] else 0
    print(f"[4] 常模：G 层 {len(g_rows)}/{norm['G']['n_total']} 进常模（有效 n={g_eff}）；"
          f"C 层 n={norm['C']['n_total']}（切片）")

    # ---- 落盘 ----
    OUT.mkdir(parents=True, exist_ok=True)
    table = {
        "model_version": MODEL_VERSION,
        "schema": SCHEMA_VERSION,
        "clinical_status": CLINICAL_STATUS,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "skipped": skipped,
        "known_answer_gate": gate_report,
        "rows": g_rows + c_rows,
    }
    with open(OUT / "feature_table.json", "w", encoding="utf-8") as f:
        json.dump(table, f, ensure_ascii=False, indent=2)

    flat_cols = ["case", "layer"] + G_FEATURES + C_FEATURES + ["in_norm", "exclude_reason"]
    with open(OUT / "feature_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(flat_cols)
        for r in g_rows + c_rows:
            row = [r["case"], r["layer"]]
            row += [r["features"].get(k, "") for k in G_FEATURES + C_FEATURES]
            row += [r["qc"].get("in_norm"), r["qc"].get("exclude_reason")]
            w.writerow(row)

    with open(OUT / "norm.json", "w", encoding="utf-8") as f:
        json.dump(norm, f, ensure_ascii=False, indent=2)

    pdir = OUT / "profiles"
    pdir.mkdir(exist_ok=True)
    for r in g_rows + c_rows:
        with open(pdir / f"{r['case']}_{r['layer']}.md", "w", encoding="utf-8") as f:
            f.write(render_case_markdown(r, norm, reg))

    with open(OUT / "evidence_registry_copy.json", "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)

    print(f"[5] 落盘 {OUT}：feature_table.json/csv + norm.json + profiles/ + registry copy")
    print(f"     剖面卡 {len(g_rows) + len(c_rows)} 张；跳过 {len(skipped)} 例")
    return 0


if __name__ == "__main__":
    sys.exit(main())
