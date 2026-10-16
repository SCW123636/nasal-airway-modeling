"""T-062 步骤4 患者自然分流重跑 v2 —— 修正 v1 两处缺陷 + 稳定化求解器设置。

v1（run_patient_bc_switch.py）缺陷（2026-10-16 诊断确认）：
  (A) `mesh_ok` 要求 "Mesh OK." 且无 "Failed N mesh checks" —— 但 T-058 患者网格是
      **已知 Failed 2 checks**（非正交 Max 76.56 > 70；482 个 det<0.001 胞元），该网格
      在 T-054/T-058 生产链中已被接受。结果 `converged` 恒 False → 外层
      `solve_common_pressure` 的 `validate()` 必抛错，驱动**永远不可能成功**。
  (B) 直接沿用生产链 `fvSolution`（`consistent yes` + `relTol 0.01` + U 0.7 / p 0.15…）。
      该设置在**速度驱动**（flowRateInletVelocity）下收敛良好，但在**压力驱动**
      （两鼻孔 fixedValue p + pressureInletOutletVelocity）下会**缓慢发散**：
      实测 b15 于 Δp=8 Pa 冷启动 57 步报 576 mL/s（物理不可能，50:50 基线
      17.114 Pa 才 250 mL/s），Ux 初始残差由 0.023 单调升到 0.029；以生产 50:50
      收敛解为初场、同 Δp=17.114 Pa 热启动时残差仍由 0.0014 升到 0.029。
      **根因 = 欠阻尼**：`consistent yes` 不使用压力松弛，稳定性全赖线性求解精度，
      而 `relTol 0.01` 只解到 2 位有效 → 误差累积漂移。
      对照实验（同网格同初场，120 步）：见 `步骤4_自然分流BC稳定性诊断.md`。

v2 稳定化设置（D 变体，实测漂移衰减 0.021%/步 → 0.006%/步，Ux 初始残差平稳 ~0.0015）：
  `consistent no` + `relTol 0.01` + `U 0.4` + `p 0.15` + `nNonOrthogonalCorrectors 2`。
  这些是**纯数值参数**（不动离散格式、不动 BC 语义、不动几何），不改变定常解。

热启动：eval_001 可由 `--seed-time-dir` 指定初场（如生产 50:50 的 600/），
eval_n>1 自动从 eval_{n-1} 最新时间目录热启动 —— 定常解与初场无关，热启动只加速。

口径声明：本卡结果 = 共同静压自然分流，**与 T-054/T-047/T-058 的固定 50:50 口径
不是同一个量**，须并列标注、禁混作同一序列比较。

用法（WSL 原生内，先 source OpenFOAM bashrc）：
  python3 run_patient_bc_switch_v2.py \
      --case-root /home/lenovo2/t058_chain_anat --work-dir /home/lenovo2/t062_patient_v2 \
      --cases b15 --rho 1.2 --target-m3s 2.5e-4 --initial-pressure-pa 17.0 \
      --seed-time-dir /home/lenovo2/t058_chain_anat/b15/foam_maxh1/600
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LIB = "/mnt/d/项目/鼻腔建模/work/lib"
INLETS = ("nostril_L", "nostril_R")
OUTLET = "oropharynx_truncation_outlet"

# ---- M2 网格判据：接受 T-058 生产链已知的两项失败（非本卡引入）----
MESH_MAX_NONORTH = 80.0        # 实测 76.56
MESH_MAX_DET_CELLS = 1000      # 实测 482

# ---- 压力驱动（自然分流）稳定化 fvSolution ----
STABLE_FVSOLUTION = """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}

// T-062 natural-split (pressure-driven) stabilised settings.
// Pure numerical parameters: discretisation, BC semantics and geometry untouched.
// Evidence: outputs/T-062/step4-natural-split-BC-stability-diagnosis.md (variants A-F).
solvers
{
    p { solver GAMG; tolerance 1e-12; relTol 0.01; smoother GaussSeidel; }
    U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
}
SIMPLE
{
    nNonOrthogonalCorrectors 2;
    consistent no;
    residualControl { p 1e-10; U 1e-8; }
}
relaxationFactors { equations { U 0.4; } fields { p 0.15; } }
"""


def _load(lib):
    sys.path.insert(0, lib)
    from openfoam_pressure_adapter import set_pressure_boundaries, monitor_rows  # noqa
    from pressure_feedback import (solve_common_pressure, FlowEvaluation,  # noqa
                                   signed_patch_fluxes, FeedbackConfig)
    return (set_pressure_boundaries, monitor_rows, solve_common_pressure,
            FlowEvaluation, signed_patch_fluxes, FeedbackConfig)


def _monitor_stability(rows, win=20, tol=0.005):
    """M2 monitor criterion: last two non-overlapping 20-sample window means."""
    if len(rows) < 2 * win:
        return None
    last = sum(r[1] for r in rows[-win:]) / win
    prior = sum(r[1] for r in rows[-2 * win:-win]) / win
    return abs(last - prior) / max(abs(last), 1e-30)


def _m2_mesh_ok(mesh_text):
    """M2 判据：接受 T-058 生产链已知的网格失败（非正交 Max≤80 / 小行列式胞元≤1000）。"""
    if "FOAM FATAL" in mesh_text:
        return False, "foam_fatal"
    det = re.search(r"small determinant \(< ?0\.001\) found, number of cells:\s*(\d+)", mesh_text)
    non = re.search(r"Mesh non-orthogonality Max:\s*([\d.]+)", mesh_text)
    if det is None or non is None:
        return ("Mesh OK." in mesh_text), "no_failure_reported"
    n_det, n_non = int(det.group(1)), float(non.group(1))
    ok = (n_det <= MESH_MAX_DET_CELLS) and (n_non <= MESH_MAX_NONORTH)
    return ok, "det_cells=%d nonorth=%.2f" % (n_det, n_non)


def _latest_time_dir(case):
    best, best_t = None, -1.0
    for child in case.iterdir():
        if child.is_dir() and re.fullmatch(r"[0-9]+(\.[0-9]+)?", child.name):
            t = float(child.name)
            if t > best_t:
                best, best_t = child, t
    return best


def _seed_fields(dst_case, seed_dir, fields=("U", "p", "phi")):
    """把 seed 时间目录的场拷入 dst_case/0（随后 set_pressure_boundaries 会重写边界块）。"""
    n = 0
    for name in fields:
        src = Path(seed_dir) / name
        if src.is_file():
            shutil.copy2(src, Path(dst_case) / "0" / name)
            n += 1
    return n


def _apply_stable_settings(case, end_time, write_interval):
    (case / "system/fvSolution").write_text(STABLE_FVSOLUTION, encoding="ascii")
    cd = case / "system/controlDict"
    text = cd.read_text()
    # 只在 `functions` 块之前替换顶层键 —— 否则会把每个函数对象的
    # `writeInterval 1` 一并改成 200，监测样本骤减（曾踩，见 v2 注释）。
    m = re.search(r"(?m)^\s*functions\s*\{", text)
    head, tail = (text[:m.start()], text[m.start():]) if m else (text, "")
    head = re.sub(r"\bendTime\s+[-+\d.eE]+;", "endTime %d;" % end_time, head)
    head = re.sub(r"\bwriteInterval\s+[-+\d.eE]+;", "writeInterval %d;" % write_interval, head)
    head = re.sub(r"\bpurgeWrite\s+\d+;", "purgeWrite 0;", head)
    head = re.sub(r"\bwriteControl\s+\w+;", "writeControl timeStep;", head)
    # 函数对象务必逐步写（M2 监测窗 20 样本需要）
    tail = re.sub(r"\bwriteControl\s+\w+;", "writeControl timeStep;", tail)
    tail = re.sub(r"\bwriteInterval\s+[-+\d.eE]+;", "writeInterval 1;", tail)
    cd.write_text(head + tail, encoding="ascii")


def run_case(case_id, case_root, work, lib, rho, target, initial_p, upper_p,
             seed_time_dir, end_time, write_interval):
    (set_pressure_boundaries, monitor_rows, solve_common_pressure,
     FlowEvaluation, signed_patch_fluxes, FeedbackConfig) = _load(lib)

    src = Path(case_root) / case_id / "foam_maxh1"
    if not (src / "constant/polyMesh/points").is_file():
        raise RuntimeError(f"source case has no polyMesh: {src}")
    cdir = work / case_id
    cdir.mkdir(parents=True, exist_ok=True)
    idx = {"n": 0}
    evaluations = []
    prev_time_dir = None

    def evaluate(pressure_pa):
        idx["n"] += 1
        nonlocal prev_time_dir
        c = cdir / f"eval_{idx['n']:03d}"
        rec_path = cdir / f"evaluation_{idx['n']:03d}.json"
        if not c.exists():
            c.mkdir(parents=True)
            for folder in ("0", "constant", "system"):
                shutil.copytree(src / folder, c / folder)
            # 热启动：eval_001 用 --seed-time-dir；后续 eval 用上一 eval 的最新时间目录
            seed = prev_time_dir or (Path(seed_time_dir) if seed_time_dir else None)
            seeded = _seed_fields(c, seed) if (seed and Path(seed).is_dir()) else 0
        else:
            seeded = None
        set_pressure_boundaries(c, float(pressure_pa), rho, INLETS, OUTLET)
        _apply_stable_settings(c, end_time, write_interval)

        env = os.environ.copy()
        with (c / "log.checkMesh").open("w") as lf:
            subprocess.run(["checkMesh", "-allGeometry", "-allTopology"],
                           cwd=str(c), stdout=lf, stderr=subprocess.STDOUT, env=env)
        with (c / "log.simpleFoam").open("w") as lf:
            proc = subprocess.run(["simpleFoam"], cwd=str(c), stdout=lf,
                                  stderr=subprocess.STDOUT, env=env)
        (c / "bcswitch.run.log").write_text(
            "T-062 v2: direct checkMesh + simpleFoam; stable fvSolution "
            "(consistent no, relTol 0.01, U 0.4, p 0.15); endTime=%d\n"
            "simpleFoam exit_code=%d\n" % (end_time, proc.returncode), encoding="ascii")
        if proc.returncode:
            raise RuntimeError(f"simpleFoam failed exit={proc.returncode} case={c}")

        flows = {n: monitor_rows(c, "flow_" + n) for n in (*INLETS, OUTLET)}
        signed = {n: flows[n][-1][1] for n in flows}
        flux = signed_patch_fluxes(signed, list(INLETS), [OUTLET])
        if len({flows[n][-1][0] for n in flows}) != 1:
            raise RuntimeError("patch monitors do not share final timestep")

        log_text = (c / "log.simpleFoam").read_text(errors="replace")
        mesh_text = (c / "log.checkMesh").read_text(errors="replace")
        end_clean = bool(re.search(r"(?m)^End\s*$", log_text)) and "FOAM FATAL" not in log_text
        mesh_ok, mesh_note = _m2_mesh_ok(mesh_text)
        mon = _monitor_stability(flows[OUTLET])
        mon_ok = (mon is None) or (mon <= 0.005)
        imb_ok = flux["mass_imbalance_frac"] <= 0.005
        converged = bool(end_clean and mesh_ok and imb_ok and mon_ok)

        ev = FlowEvaluation(float(pressure_pa), flux["q_in_by_patch"][INLETS[0]],
                            flux["q_in_by_patch"][INLETS[1]], flux["q_out_m3_s"],
                            converged=converged, mesh_quality_passed=mesh_ok,
                            mass_imbalance_frac=flux["mass_imbalance_frac"],
                            residuals_passed=True)
        ux = re.findall(r"Solving for Ux, Initial residual = ([\deE+.-]+)", log_text)
        record = {"case_dir": str(c), "pressure_pa": float(pressure_pa),
                  "q_total_m3_s": ev.q_total_m3_s, "left_fraction":
                  ev.q_left_m3_s / ev.q_total_m3_s if ev.q_total_m3_s else None,
                  "mass_imbalance_frac": flux["mass_imbalance_frac"],
                  "monitor_change": mon, "end_clean": end_clean,
                  "mesh_ok": mesh_ok, "mesh_note": mesh_note,
                  "ux_initial_residual_first": float(ux[0]) if ux else None,
                  "ux_initial_residual_last": float(ux[-1]) if ux else None,
                  "steps": len(ux), "seeded_fields": seeded,
                  "solver_settings": {"consistent": "no", "relTol": 0.01,
                                      "U_relax": 0.4, "p_relax": 0.15,
                                      "nNonOrthogonalCorrectors": 2, "endTime": end_time},
                  "converged": converged, "signed_phi": signed}
        rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        latest = _latest_time_dir(c)
        prev_time_dir = latest if latest is not None and float(latest.name) > 0 else prev_time_dir
        evaluations.append(record)
        print(json.dumps({"event": "eval", "case": case_id, "pressure_pa": pressure_pa,
                          "q_total_m3_s": ev.q_total_m3_s, "left_fraction":
                          record["left_fraction"], "converged": converged}),
              flush=True)
        return ev

    result = solve_common_pressure(
        evaluate,
        FeedbackConfig(target_m3_s=target, initial_pressure_pa=initial_p,
                       pressure_upper_pa=upper_p, max_iterations=12,
                       relative_flow_tolerance=0.01))
    return {"result": result, "evaluations": evaluations,
            "source_case": str(src), "rho": rho, "target_m3_s": target,
            "seed_time_dir": seed_time_dir}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-root", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--rho", type=float, default=1.2)
    ap.add_argument("--target-m3s", type=float, default=2.5e-4)
    ap.add_argument("--initial-pressure-pa", type=float, default=17.0)
    ap.add_argument("--upper-pressure-pa", type=float, default=200.0)
    ap.add_argument("--seed-time-dir", default=None)
    ap.add_argument("--end-time", type=int, default=300)
    ap.add_argument("--write-interval", type=int, default=100)
    ap.add_argument("--lib", default=DEFAULT_LIB)
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out = {"schema": "nasal_t062_patient_bc_switch_v2/v1",
           "boundary_mode": "common_inlet_static_pressure_outer_feedback",
           "solver_settings": {"consistent": "no", "relTol": 0.01, "U_relax": 0.4,
                               "p_relax": 0.15, "endTime": args.end_time},
           "mesh_criterion": {"mode": "M2_accept_known_T058_failures",
                              "max_nonorthogonality": MESH_MAX_NONORTH,
                              "max_det_lt_0p001_cells": MESH_MAX_DET_CELLS},
           "target_m3_s": args.target_m3s, "rho_kg_m3": args.rho,
           "initial_pressure_pa": args.initial_pressure_pa,
           "seed_time_dir": args.seed_time_dir,
           "clinical_status": "generalisation_test_only_no_human_review",
           "created": datetime.now(timezone.utc).isoformat(),
           "cases": {}}
    for case_id in args.cases:
        try:
            out["cases"][case_id] = run_case(
                case_id, args.case_root, work, args.lib, args.rho,
                args.target_m3s, args.initial_pressure_pa, args.upper_pressure_pa,
                args.seed_time_dir, args.end_time, args.write_interval)
            out["cases"][case_id]["status"] = "converged"
        except Exception as exc:  # noqa: BLE001
            out["cases"][case_id] = {"status": "error", "error": repr(exc)}
        (work / "patient_bc_switch_report_v2.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
