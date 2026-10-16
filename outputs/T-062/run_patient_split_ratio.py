"""T-062 步骤4（替代路线）：分流比外层自然分流驱动。

背景（outputs/T-062/步骤4_自然分流BC稳定性诊断.md §7–8）：
  压力驱动（两鼻孔 fixedValue p + 自然分流）在 T-058 患者网格上存在边缘失稳模态：
  p relTol 0.01 时无论初场一致性如何都会指数发散（eval_001 t>60、H_d600 t>66 确认），
  p relTol 0 虽可能稳定但 ~60 s/步（600 步 ≈ 6 h/eval）不可行。

本路线的物理等价性：
  「共同静压 + 自然分流 + 总流量 250 mL/s」的稳态解 = 「总流量 250、分流比 λ* 使
  两鼻孔静压相等」的稳态解——两者是同一个定常解的两种参数化。因此：
    内层：沿用生产链**流量驱动** BC（flowRateInletVelocity，本网格 600 步收敛良好，
          consistent yes + U0.7/p0.3 原设置，T-054/T-058 已验证）；
    外层：调分流比 λ（nostril_L 占总流量的比例），解 g(λ) = p_L(λ) − p_R(λ) = 0
          （g 关于 λ 严格单调递增），割线法，容差 |g| ≤ 0.05 Pa（≈0.3% Δp）。
  收敛后报告 λ*、p_L、p_R、p_common=(p_L+p_R)/2、Q_total、left_fraction。
  Δp 口径 = p_common（出口 gauge 静压 0，与 T-054 的 18.267 Pa 同为端压差，可直接并列）。

运行（WSL 原生，先 source /usr/share/openfoam/etc/bashrc）：
  python3 run_patient_split_ratio.py --case-root /home/lenovo2/t058_chain_anat \
      --work-dir /home/lenovo2/t062_split --cases b15 --rho 1.2 --target-m3s 2.5e-4 \
      --seed-time-dir /home/lenovo2/t058_chain_anat/b15/foam_maxh1/600 --end-time 600
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

MESH_MAX_NONORTH = 80.0        # T-058 已知：实测 76.56
MESH_MAX_DET_CELLS = 1000      # T-058 已知：实测 482


def _load(lib):
    sys.path.insert(0, lib)
    from openfoam_pressure_adapter import monitor_rows  # noqa
    return monitor_rows


def _m2_mesh_ok(mesh_text):
    if "FOAM FATAL" in mesh_text:
        return False, "foam_fatal"
    det = re.search(r"small determinant \(< ?0\.001\) found, number of cells:\s*(\d+)", mesh_text)
    non = re.search(r"Mesh non-orthogonality Max:\s*([\d.]+)", mesh_text)
    if det is None or non is None:
        return ("Mesh OK." in mesh_text), "no_failure_reported"
    ok = (int(det.group(1)) <= MESH_MAX_DET_CELLS) and (float(non.group(1)) <= MESH_MAX_NONORTH)
    return ok, "det_cells=%s nonorth=%s" % (det.group(1), non.group(1))


def _monitor_stability(rows, win=20, tol=0.005):
    if len(rows) < 2 * win:
        return None
    last = sum(r[1] for r in rows[-win:]) / win
    prior = sum(r[1] for r in rows[-2 * win:-win]) / win
    return abs(last - prior) / max(abs(last), 1e-30)


def _latest_time_dir(case):
    best, best_t = None, -1.0
    for child in case.iterdir():
        if child.is_dir() and re.fullmatch(r"[0-9]+(\.[0-9]+)?", child.name):
            t = float(child.name)
            if t > best_t:
                best, best_t = child, t
    return best


def _seed_fields(dst_case, seed_dir, fields=("U", "p", "phi")):
    n = 0
    for name in fields:
        src = Path(seed_dir) / name
        if src.is_file():
            shutil.copy2(src, Path(dst_case) / "0" / name)
            n += 1
    return n


def _set_split_rates(case, lam, target):
    """改 0/U 两个鼻孔的 volumetricFlowRate（流量驱动，生产 BC 语义不动）。"""
    u_path = case / "0/U"
    text = u_path.read_text()
    q_l, q_r = lam * target, (1.0 - lam) * target
    for patch, q in ((INLETS[0], q_l), (INLETS[1], q_r)):
        pat = r"(%s\s*\{[^}]*volumetricFlowRate\s+constant\s+)[-+\d.eE]+(;)" % patch
        new, n = re.subn(pat, r"\g<1>%.6e\g<2>" % q, text, count=1)
        if n != 1:
            raise RuntimeError("volumetricFlowRate not patched: %s" % patch)
        text = new
    u_path.write_text(text, encoding="ascii")
    return q_l, q_r


def _fix_controldict(case, end_time, write_interval):
    """只改 functions 块之前的顶层键（防止把函数对象 writeInterval 一并改掉——曾踩）。"""
    cd = case / "system/controlDict"
    text = cd.read_text()
    m = re.search(r"(?m)^\s*functions\s*\{", text)
    head, tail = (text[:m.start()], text[m.start():]) if m else (text, "")
    head = re.sub(r"\bendTime\s+[-+\d.eE]+;", "endTime %d;" % end_time, head)
    head = re.sub(r"\bwriteInterval\s+[-+\d.eE]+;", "writeInterval %d;" % write_interval, head)
    head = re.sub(r"\bpurgeWrite\s+\d+;", "purgeWrite 0;", head)
    head = re.sub(r"\bwriteControl\s+\w+;", "writeControl timeStep;", head)
    cd.write_text(head + tail, encoding="ascii")


def run_case(case_id, case_root, work, monitor_rows, rho, target, seed_time_dir,
             end_time, write_interval, p_tol_pa, max_evals):
    src = Path(case_root) / case_id / "foam_maxh1"
    if not (src / "constant/polyMesh/points").is_file():
        raise RuntimeError("source case has no polyMesh: %s" % src)
    cdir = work / case_id
    cdir.mkdir(parents=True, exist_ok=True)
    state = {"n": 0, "seed": Path(seed_time_dir) if seed_time_dir else None}
    evaluations = []

    def evaluate(lam):
        state["n"] += 1
        c = cdir / ("eval_%03d" % state["n"])
        c.mkdir(parents=True, exist_ok=True)
        if not (c / "0").exists():
            for folder in ("0", "constant", "system"):
                shutil.copytree(src / folder, c / folder)
            seeded = _seed_fields(c, state["seed"]) if state["seed"] else 0
        else:
            seeded = None
        q_l, q_r = _set_split_rates(c, float(lam), target)
        _fix_controldict(c, end_time, write_interval)

        env = os.environ.copy()
        with (c / "log.checkMesh").open("w") as lf:
            subprocess.run(["checkMesh", "-allGeometry", "-allTopology"], cwd=str(c),
                           stdout=lf, stderr=subprocess.STDOUT, env=env)
        with (c / "log.simpleFoam").open("w") as lf:
            proc = subprocess.run(["simpleFoam"], cwd=str(c), stdout=lf,
                                  stderr=subprocess.STDOUT, env=env)
        (c / "split.run.log").write_text(
            "T-062 split-ratio mode: flow-driven inner (production fvSolution untouched), "
            "lambda=%.6f endTime=%d; simpleFoam exit=%d\n" % (lam, end_time, proc.returncode),
            encoding="ascii")
        if proc.returncode:
            raise RuntimeError("simpleFoam failed exit=%d case=%s" % (proc.returncode, c))

        flows = {n: monitor_rows(c, "flowIn" + sfx) for n, sfx in
                 ((INLETS[0], "L"), (INLETS[1], "R"))}
        flows[OUTLET] = monitor_rows(c, "flowOut")
        pressures = {n: monitor_rows(c, "pressureIn" + sfx) for n, sfx in
                     ((INLETS[0], "L"), (INLETS[1], "R"))}
        q_in = flows[INLETS[0]][-1][1] + flows[INLETS[1]][-1][1]
        q_out = flows[OUTLET][-1][1]
        imb = abs(q_in + q_out) / max(abs(q_in), 1e-30)
        p_l = pressures[INLETS[0]][-1][1] * rho
        p_r = pressures[INLETS[1]][-1][1] * rho
        g = p_l - p_r

        log_text = (c / "log.simpleFoam").read_text(errors="replace")
        mesh_text = (c / "log.checkMesh").read_text(errors="replace")
        end_clean = bool(re.search(r"(?m)^End\s*$", log_text)) and "FOAM FATAL" not in log_text
        mesh_ok, mesh_note = _m2_mesh_ok(mesh_text)
        mon = _monitor_stability(flows[OUTLET])
        mon_ok = (mon is None) or (mon <= 0.005)
        converged = bool(end_clean and mesh_ok and imb <= 0.005 and mon_ok)

        last_t = max(rows[-1][0] for rows in list(flows.values()) + list(pressures.values()))
        record = {
            "case_dir": str(c), "lambda_left": float(lam),
            "q_left_m3_s": flows[INLETS[0]][-1][1], "q_right_m3_s": flows[INLETS[1]][-1][1],
            "q_total_m3_s": q_in, "q_outlet_m3_s": q_out, "mass_imbalance_frac": imb,
            "p_left_pa": p_l, "p_right_pa": p_r, "g_p_left_minus_right_pa": g,
            "p_common_pa": 0.5 * (p_l + p_r),
            "left_fraction": flows[INLETS[0]][-1][1] / q_in if q_in else None,
            "end_clean": end_clean, "mesh_ok": mesh_ok, "mesh_note": mesh_note,
            "monitor_change": mon, "converged": converged,
            "last_monitor_time": last_t, "seeded_fields": seeded,
            "inner_settings": {"mode": "flow_driven_production_fvSolution_untouched",
                               "endTime": end_time},
        }
        (cdir / ("evaluation_%03d.json" % state["n"])).write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        latest = _latest_time_dir(c)
        if latest is not None and float(latest.name) > 0:
            state["seed"] = latest
        evaluations.append(record)
        print(json.dumps({"event": "eval", "case": case_id, "lambda": lam,
                          "p_left_pa": p_l, "p_right_pa": p_r, "g_pa": g,
                          "q_total_m3_s": q_in, "converged": converged}), flush=True)
        return record

    # 外层割线：起点 λ0=0.52（probe D 预测 0.523），第二点 λ1=0.55；g 单调递增
    lam_lo, lam_hi = 0.52, 0.55
    r_lo = evaluate(lam_lo)
    best = r_lo
    if abs(r_lo["g_p_left_minus_right_pa"]) > p_tol_pa:
        r_hi = evaluate(lam_hi)
        best = r_hi
        it = 2
        while abs(best["g_p_left_minus_right_pa"]) > p_tol_pa and it < max_evals:
            glo = r_lo["g_p_left_minus_right_pa"]
            ghi = r_hi["g_p_left_minus_right_pa"]
            lam2 = lam_hi - ghi * (lam_hi - lam_lo) / (ghi - glo)
            lam2 = min(0.7, max(0.3, lam2))
            r2 = evaluate(lam2)
            lam_lo, r_lo, lam_hi, r_hi = lam_hi, r_hi, lam2, r2
            best = r2
            it += 1
    solved = abs(best["g_p_left_minus_right_pa"]) <= p_tol_pa
    return {"status": "converged" if solved else "pressure_balance_not_reached",
            "best": best, "evaluations": evaluations,
            "p_tolerance_pa": p_tol_pa, "source_case": str(src),
            "rho_kg_m3": rho, "target_m3_s": target}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-root", required=True)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--rho", type=float, default=1.2)
    ap.add_argument("--target-m3s", type=float, default=2.5e-4)
    ap.add_argument("--seed-time-dir", default=None)
    ap.add_argument("--end-time", type=int, default=600)
    ap.add_argument("--write-interval", type=int, default=200)
    ap.add_argument("--p-tol-pa", type=float, default=0.05)
    ap.add_argument("--max-evals", type=int, default=6)
    ap.add_argument("--lib", default=DEFAULT_LIB)
    args = ap.parse_args()

    monitor_rows = _load(args.lib)
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    out = {"schema": "nasal_t062_patient_split_ratio/v1",
           "boundary_mode": ("flow_driven_split_ratio_outer_feedback "
                             "(physically equivalent to common static pressure natural split)"),
           "equivalence_note": ("steady state of [common inlet static pressure + natural split + "
                                "Q_total=target] equals steady state of [Q_total=target with split "
                                "ratio lambda such that p_left(lambda)=p_right(lambda)]"),
           "mesh_criterion": {"mode": "M2_accept_known_T058_failures",
                              "max_nonorthogonality": MESH_MAX_NONORTH,
                              "max_det_lt_0p001_cells": MESH_MAX_DET_CELLS},
           "target_m3_s": args.target_m3s, "rho_kg_m3": args.rho,
           "p_tolerance_pa": args.p_tol_pa, "seed_time_dir": args.seed_time_dir,
           "clinical_status": "generalisation_test_only_no_human_review",
           "created": datetime.now(timezone.utc).isoformat(),
           "cases": {}}
    for case_id in args.cases:
        try:
            res = run_case(case_id, args.case_root, work, monitor_rows, args.rho,
                           args.target_m3s, args.seed_time_dir, args.end_time,
                           args.write_interval, args.p_tol_pa, args.max_evals)
            out["cases"][case_id] = res
        except Exception as exc:  # noqa: BLE001
            out["cases"][case_id] = {"status": "error", "error": repr(exc)}
        (work / "patient_split_ratio_report.json").write_text(
            json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
