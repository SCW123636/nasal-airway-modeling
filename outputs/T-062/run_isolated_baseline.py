"""T-062 步骤1 隔离基准：验证「共同静压 + 自然分流」求解适配器（C1/C2/C3）。

复用 T-021 已验证组件（不重写求解逻辑）：
  - structured_split_feedback.write_case  —— 不等分支 2D 示意几何（blockMesh）
  - openfoam_pressure_adapter.OpenFOAMPressureEvaluator —— 真实 OpenFOAM 评估（入口共同
    fixedValue p/rho + pressureInletOutletVelocity；出口 fixedValue 0；有符号 phi）
  - pressure_feedback.solve_common_pressure —— 外层割线/二分调压至总流量目标

必须在 WSL 原生文件系统内执行（适配器要求 os.name=='posix' 且工作目录非 /mnt）。
用法（WSL 内）：
  source /usr/share/openfoam/etc/bashrc
  python3 run_isolated_baseline.py --work-dir /home/lenovo2/t062_iso --groups A
组：
  A_reproduce  —— 复现 T-021 已知答案（原几何 2:1 / 1:1，target = 1 L/min）
  B_patient    —— 患者工况（放大几何保持层流，target = 250 mL/s）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 本项目 work/lib（WSL 路径；含中文目录，导入已验证可用）
DEFAULT_LIB = "/mnt/d/项目/鼻腔建模/work/lib"

GROUPS = {
    "A": {
        "name": "A_reproduce_t021",
        "target_m3_s": 1.666666666666667e-5,      # 1 L/min（T-021 原 target）
        "initial_pressure_pa": 1.0,
        "pressure_upper_pa": 200.0,
        "end_time": 3000,
        "scenarios": [("unequal", 2.0, 1.0, False),
                      ("symmetric", 1.5, 1.5, False),
                      ("swapped_labels", 2.0, 1.0, True)],
    },
    "B": {
        "name": "B_patient_flow",
        "target_m3_s": 2.5e-4,                     # 250 mL/s（患者目标）
        "initial_pressure_pa": 1.0,
        "pressure_upper_pa": 100.0,
        "end_time": 3000,
        # 2D empty 挤压下 Re ∝ Q/depth（放大宽度不降 Re）；加大深度 10->100mm
        # 把 250 mL/s 的 Re 降到层流（≈1.5e2），使控制器能在 250 mL/s 下充分收敛。
        "depth_mm": 100.0,
        "scenarios": [("unequal", 12.0, 6.0, False),
                      ("symmetric", 9.0, 9.0, False),
                      ("swapped_labels", 12.0, 6.0, True)],
    },
}


def run_group(gkey: str, work: Path, lib: str):
    sys.path.insert(0, lib)
    import structured_split_feedback as ssf
    from structured_split_feedback import write_case
    from openfoam_pressure_adapter import OpenFOAMPressureEvaluator
    from pressure_feedback import solve_common_pressure, FeedbackConfig

    g = GROUPS[gkey]
    if g.get("depth_mm"):
        ssf.DEPTH_MM = float(g["depth_mm"])   # 模块级 depth 常量（write_case 读取）
    gdir = work / g["name"]
    gdir.mkdir(parents=True, exist_ok=True)
    rep = {"target_m3_s": g["target_m3_s"], "scenarios": {}}
    cfgs = []

    for name, lw, rw, swapped in g["scenarios"]:
        base = gdir / name
        template = base / "template"
        base.mkdir(parents=True, exist_ok=True)
        if not template.exists():
            write_case(template, 0.0, lw, rw, swapped, end_time=g["end_time"])
        evaluator = OpenFOAMPressureEvaluator(
            template, base / "evaluations",
            inlets=("inlet_L", "inlet_R"), outlet="outlet")
        result = solve_common_pressure(
            evaluator,
            FeedbackConfig(target_m3_s=g["target_m3_s"],
                           initial_pressure_pa=g["initial_pressure_pa"],
                           pressure_upper_pa=g["pressure_upper_pa"],
                           max_iterations=15,
                           relative_flow_tolerance=0.01))
        ideal = lw ** 3 / (lw ** 3 + rw ** 3)   # 层流 2D 平行板 Q ∝ width^3
        rep["scenarios"][name] = {
            "result": result,
            "geometry": {"left_width_mm": lw, "right_width_mm": rw, "swapped": swapped},
            "ideal_planar_left_fraction": ideal,
            "evaluations": evaluator.evaluations,
        }
        print(json.dumps({"group": gkey, "scenario": name, "status": result["status"],
                          "q_total_m3_s": result["q_total_m3_s"],
                          "pressure_pa": result["pressure_pa"],
                          "left_fraction": result["left_fraction"], "ideal": ideal}),
              flush=True)

    u = rep["scenarios"]["unequal"]["result"]
    s = rep["scenarios"]["symmetric"]["result"]
    w = rep["scenarios"]["swapped_labels"]["result"]
    ideal_u = rep["scenarios"]["unequal"]["ideal_planar_left_fraction"]
    rep["checks"] = {
        "all_scenarios_converged": all(
            rep["scenarios"][k]["result"]["status"] == "converged"
            for k in ("unequal", "symmetric", "swapped_labels")),
        "unequal_split_is_not_symmetric": abs(u["left_fraction"] - 0.5) > 0.1,
        "symmetric_split_near_half": abs(s["left_fraction"] - 0.5) <= 0.02,
        "label_swap_complements_split": abs(w["left_fraction"] - (1.0 - u["left_fraction"])) <= 0.02,
        "unequal_matches_cubic_law": abs(u["left_fraction"] - ideal_u) <= 0.03,
        "all_flow_errors_within_one_percent": all(
            abs(rep["scenarios"][k]["result"]["q_total_m3_s"] - g["target_m3_s"]) / g["target_m3_s"] <= 0.01
            for k in ("unequal", "symmetric", "swapped_labels")),
    }
    rep["status"] = "pass" if all(rep["checks"].values()) else "fail"
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--lib", default=DEFAULT_LIB)
    ap.add_argument("--groups", nargs="+", default=["A", "B"], choices=["A", "B"])
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out = {"schema": "nasal_t062_isolated_baseline/v1", "patient_data": False, "groups": {}}
    for gkey in args.groups:
        try:
            out["groups"][GROUPS[gkey]["name"]] = run_group(gkey, work, args.lib)
        except Exception as exc:  # noqa: BLE001
            out["groups"][GROUPS[gkey]["name"]] = {"status": "error", "error": repr(exc)}

    out["status"] = ("pass" if out["groups"] and
                     all(r.get("status") == "pass" for r in out["groups"].values()) else "fail")
    (work / "isolated_baseline_report.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"overall_status": out["status"]}), flush=True)
    return 0 if out["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
