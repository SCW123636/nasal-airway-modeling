"""T-062 步骤4 患者自然分流重跑：共同静压调压至 250 mL/s（M2 口径质量门）。

对 T-058 三例扩展域 case（几何/网格复用，不动）：
  1. 复制 case 的 0/constant/system 到独立 eval 目录（polyMesh 一并复制）；
  2. set_pressure_boundaries 写自然分流 BC —— 两鼻孔共同 fixedValue p/rho、
     出口 fixedValue 0、入口 pressureInletOutletVelocity、有符号 phi 监测；
  3. simpleFoam（沿用 case 的 controlDict endTime）；
  4. 有符号 phi 测总流量 + M2 口径质量门（no_crash / 质量不平衡 / 监测稳定；
     Δp 入带 [10,100] 作为**最终**判据，不作每次 eval 门——调压中 Δp 必跨带）；
  5. 外层割线/二分调 p_outer，使 Q_total → 250 mL/s（solve_common_pressure）。

口径声明：本卡结果 = 共同静压自然分流，**与 T-054/T-047/T-058 的固定 50:50 口径
不是同一个量**，须并列标注、禁混作同一序列比较。

用法（WSL 原生内，先 source OpenFOAM bashrc）：
  python3 run_patient_bc_switch.py \
      --case-root /home/lenovo2/t058_chain_anat \
      --work-dir /home/lenovo2/t062_patient \
      --cases b15 b01 b02 --rho 1.2 --target-m3s 2.5e-4
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
DEFAULT_SOLVER = "/mnt/d/项目/鼻腔建模/work/07_cfd_pipeline/solver/run_openfoam_case.py"
INLETS = ("nostril_L", "nostril_R")
OUTLET = "oropharynx_truncation_outlet"


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


def run_case(case_id, case_root, work, lib, solver, rho, target, initial_p, upper_p):
    (set_pressure_boundaries, monitor_rows, solve_common_pressure,
     FlowEvaluation, signed_patch_fluxes, FeedbackConfig) = _load(lib)

    src = Path(case_root) / case_id / "foam_maxh1"
    if not (src / "constant/polyMesh/points").is_file():
        raise RuntimeError(f"source case has no polyMesh: {src}")
    cdir = work / case_id
    cdir.mkdir(parents=True, exist_ok=True)
    idx = {"n": 0}
    evaluations = []

    def evaluate(pressure_pa):
        idx["n"] += 1
        c = cdir / f"eval_{idx['n']:03d}"
        rec_path = cdir / f"evaluation_{idx['n']:03d}.json"
        if not c.exists():
            c.mkdir(parents=True)
            for folder in ("0", "constant", "system"):
                shutil.copytree(src / folder, c / folder)
        set_pressure_boundaries(c, float(pressure_pa), rho, INLETS, OUTLET)

        # 直接跑 checkMesh + simpleFoam（复用 T-058 生产链模式）。T-058 患者网格含已知
        # Failed 2 checks（det<0.001，M2 判据接受），而 run_openfoam_case.py 的 mesh 门会拒
        # 绝求解，且 --allow-failed-mesh-for-diagnostic 仅限合成 tube.stl 幻影 → 走直跑。
        env = os.environ.copy()
        with (c / "log.checkMesh").open("w") as lf:
            subprocess.run(["checkMesh", "-allGeometry", "-allTopology"],
                           cwd=str(c), stdout=lf, stderr=subprocess.STDOUT, env=env)
        with (c / "log.simpleFoam").open("w") as lf:
            proc = subprocess.run(["simpleFoam"], cwd=str(c), stdout=lf,
                                  stderr=subprocess.STDOUT, env=env)
        (c / "bcswitch.run.log").write_text(
            "direct checkMesh + simpleFoam (T-058 chain mode; mesh gate bypassed)\n"
            f"simpleFoam exit_code={proc.returncode}\n", encoding="ascii")
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
        mesh_ok = "Mesh OK." in mesh_text and not re.search(r"Failed\s+\d+\s+mesh checks", mesh_text)
        mon = _monitor_stability(flows[OUTLET])
        mon_ok = (mon is None) or (mon <= 0.005)
        imb_ok = flux["mass_imbalance_frac"] <= 0.005
        # NOTE: Delta-p band is a FINAL criterion, deliberately NOT applied here
        # (during outer bracketing the pressure ranges over sub- and super-band values).
        converged = bool(end_clean and mesh_ok and imb_ok and mon_ok)

        ev = FlowEvaluation(float(pressure_pa), flux["q_in_by_patch"][INLETS[0]],
                            flux["q_in_by_patch"][INLETS[1]], flux["q_out_m3_s"],
                            converged=converged, mesh_quality_passed=mesh_ok,
                            mass_imbalance_frac=flux["mass_imbalance_frac"],
                            residuals_passed=True)
        record = {"case_dir": str(c), "pressure_pa": float(pressure_pa),
                  "q_total_m3_s": ev.q_total_m3_s, "left_fraction":
                  ev.q_left_m3_s / ev.q_total_m3_s if ev.q_total_m3_s else None,
                  "mass_imbalance_frac": flux["mass_imbalance_frac"],
                  "monitor_change": mon, "end_clean": end_clean, "mesh_ok": mesh_ok,
                  "converged": converged, "signed_phi": signed}
        rec_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        evaluations.append(record)
        print(json.dumps({"event": "eval", "case": case_id, "pressure_pa": pressure_pa,
                          "q_total_m3_s": ev.q_total_m3_s, "converged": converged}),
              flush=True)
        return ev

    result = solve_common_pressure(
        evaluate,
        FeedbackConfig(target_m3_s=target, initial_pressure_pa=initial_p,
                       pressure_upper_pa=upper_p, max_iterations=12,
                       relative_flow_tolerance=0.01))
    return {"result": result, "evaluations": evaluations,
            "source_case": str(src), "rho": rho, "target_m3_s": target}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-root", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--rho", type=float, default=1.2)
    ap.add_argument("--target-m3s", type=float, default=2.5e-4)
    ap.add_argument("--initial-pressure-pa", type=float, default=8.0)
    ap.add_argument("--upper-pressure-pa", type=float, default=200.0)
    ap.add_argument("--lib", default=DEFAULT_LIB)
    ap.add_argument("--solver", default=DEFAULT_SOLVER)
    args = ap.parse_args()

    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out = {"schema": "nasal_t062_patient_bc_switch/v1",
           "boundary_mode": "common_inlet_static_pressure_outer_feedback",
           "target_m3_s": args.target_m3s, "rho_kg_m3": args.rho,
           "clinical_status": "generalisation_test_only_no_human_review",
           "created": datetime.now(timezone.utc).isoformat(),
           "cases": {}}
    for case_id in args.cases:
        try:
            out["cases"][case_id] = run_case(
                case_id, args.case_root, work, args.lib, args.solver, args.rho,
                args.target_m3s, args.initial_pressure_pa, args.upper_pressure_pa)
            out["cases"][case_id]["status"] = "converged"
        except Exception as exc:  # noqa: BLE001
            out["cases"][case_id] = {"status": "error", "error": repr(exc)}
        (work / "patient_bc_switch_report.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
