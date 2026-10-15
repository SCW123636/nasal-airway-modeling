"""T-042: dP monitor stability + mass-imbalance history for the b15 maxh1 S-A run.

Implements the CONTRACT's operational definition of `monitor_relative_change`
verbatim from `work/lib/openfoam_pressure_adapter.py::solver_diagnostics`
(T-008 diagnostic basis):

    dP = area-weighted mean nostril static pressure - nasopharynx outlet
         static pressure          (kinematic -> Pa via rho = 1.2)
    tail = last 40% of monitor samples
    windows = consecutive NON-OVERLAPPING 20-sample window means
    monitor_relative_change = max successive |b-a|/max(|b|,eps)

Dual-end script (standard library only): run it on Windows and it copies
itself into WSL, runs the analysis there (case lives on the native Linux FS),
and fetches the JSON back. `python3 monitor_stability_b15.py --out <json>`
inside WSL does the analysis directly.

Restarted-case caveat (documented)
----------------------------------
This case was killed at Time=317 and resumed from Time=200, so its
function-object history lives in two directories: `postProcessing/<fn>/0/`
(pre-kill, 316 rows) and `postProcessing/<fn>/200/` (resume, 400 rows,
times 201..600). The adapter concatenates all time dirs (designed for fresh
single-segment runs); for this restarted case that path is NOT COMPUTABLE:
the pre-kill `pressureOut/0/surfaceFieldValue.dat` is EMPTY (the killed run's
controlDict differed), so no aligned pre-kill dP series exists. The monitor
is therefore computed on the resume segment only -- which is also the
defensible reading for a restarted case, since the superseded pre-kill
segment is not part of the final solve. This deviation from the adapter's
concatenation is recorded here rather than silently absorbed.

Also reports, per the T-008 diagnostic basis:
  * mass-imbalance history (max over the run vs final steady value), so the
    startup transient is separated from the steady segment instead of hidden
  * the per-patch flow monitor (two 10-sample window means, adapter formula)
  * solver-log continuity errors (first/last/max) for context
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

CASE = Path("/home/lenovo2/patient_cfd/b15_maxh1")
PP = CASE / "postProcessing"
LOG = CASE / "log.simpleFoam_resume"
A_L = 8.205240363280577e-05      # nostril_L area, m2 (from metrics_b15_maxh1.json)
A_R = 8.115320486652986e-05      # nostril_R area, m2
RHO = 1.20
WINDOW = 20


def read_rows(path):
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) != 2:
            raise ValueError("bad row in %s: %r" % (path, line))
        rows.append((float(parts[0]), float(parts[1])))
    return rows


def series(name, only_dir=None):
    """(time, value) rows for a function object; only_dir restricts to one
    time directory (e.g. '200' for the resumed segment)."""
    files = sorted((PP / name).glob("*/surfaceFieldValue.dat"),
                   key=lambda p: float(p.parent.name))
    if only_dir is not None:
        files = [p for p in files if p.parent.name == only_dir]
    if not files:
        raise ValueError("no dat for " + name)
    rows = []
    for p in files:
        rows.extend(read_rows(p))
    return rows


def monitor_change(dp):
    """Contract definition: last 40%, non-overlapping 20-sample window means,
    max successive relative change."""
    tail = dp[int(len(dp) * 0.6):]
    if len(tail) < 2 * WINDOW:
        raise ValueError("not enough samples for two windows: %d" % len(tail))
    windows = [sum(tail[i:i + WINDOW]) / WINDOW
               for i in range(0, len(tail) - WINDOW + 1, WINDOW)]
    if len(windows) < 2:
        raise ValueError("fewer than two windows")
    change = max(abs(b - a) / max(abs(b), 1e-30) for a, b in zip(windows, windows[1:]))
    return {"monitor_relative_change": change,
            "n_samples": len(dp), "n_tail": len(tail),
            "n_windows": len(windows),
            "window_means_pa": windows}


def flow_monitor(name, only_dir="200"):
    """Adapter flow monitor: mean of last 10 vs previous 10 signed-phi samples."""
    rows = series(name, only_dir)
    if len(rows) < 20:
        raise ValueError("flow monitor needs 20 samples: " + name)
    prior = sum(r[1] for r in rows[-20:-10]) / 10.0
    latest = sum(r[1] for r in rows[-10:]) / 10.0
    return {"patch": name, "prior_mean": prior, "latest_mean": latest,
            "relative_change": abs(latest - prior) / max(abs(latest), 1e-30)}


def analyze():
    # Pre-kill segment (0-dir) is incomplete (pressureOut/0 is empty), so the
    # concatenated variant is not computable; only the resume segment is used.
    pL = series("pressureInL", "200")
    pR = series("pressureInR", "200")
    pO = series("pressureOut", "200")
    if not (len(pL) == len(pR) == len(pO)):
        raise ValueError("pressure monitors have mismatched sample counts: %d/%d/%d"
                         % (len(pL), len(pR), len(pO)))

    def dp_of(rows_l, rows_r, rows_o):
        return [((l[1] * A_L + r[1] * A_R) / (A_L + A_R) - o[1]) * RHO
                for l, r, o in zip(rows_l, rows_r, rows_o)]

    dp_resume = dp_of(pL, pR, pO)

    res = {
        "case": str(CASE),
        "rho_kg_m3": RHO,
        "areas_m2": {"nostril_L": A_L, "nostril_R": A_R},
        "dp_definition": ("area-weighted mean nostril static pressure minus "
                          "nasopharmacy outlet static pressure, x rho"),
        "resume_only": monitor_change(dp_resume),
        "concatenated": {
            "status": "not_computable",
            "reason": ("pre-kill pressureOut/0/surfaceFieldValue.dat is empty; "
                       "no aligned pre-kill dP series exists (adapter's "
                       "concatenation path assumes a fresh single-segment run)"),
        },
        "final_dp_pa": dp_resume[-1],
        "final_nostril_p_kinematic": {"L": pL[-1][1], "R": pR[-1][1]},
        "flow_monitors": [flow_monitor("flowInL"), flow_monitor("flowInR"),
                          flow_monitor("flowOut")],
    }

    # mass-imbalance history from boundary flows (startup vs steady separation)
    fL, fR, fO = (series("flowInL", "200"), series("flowInR", "200"),
                  series("flowOut", "200"))
    imb = [abs((-l[1]) + (-r[1]) - o[1]) / max(abs((-l[1]) + (-r[1])), 1e-30)
           for l, r, o in zip(fL, fR, fO)]
    res["mass_imbalance"] = {
        "final": imb[-1],
        "max_over_resume": max(imb),
        "max_time": fL[imb.index(max(imb))][0],
        "n_samples": len(imb),
        "definition": "|q_in - q_out| / q_in from per-patch sum(phi) dats, signed",
    }

    # solver-log continuity errors (context; NOT the boundary-flow measure)
    txt = LOG.read_text(encoding="utf-8", errors="replace")
    glob = [float(x) for x in
            __import__("re").findall(r"global = ([\deE+.-]+)", txt)]
    res["log_continuity_global"] = {
        "n": len(glob), "first": glob[0] if glob else None,
        "last": glob[-1] if glob else None,
        "max_abs": max(abs(g) for g in glob) if glob else None,
        "note": ("per-time-step predictor continuity error from the solver log; "
                 "distinct from the boundary-flow imbalance above"),
    }
    return res


def main(argv):
    if os.name == "nt":
        repo = Path(__file__).resolve().parents[2]
        wsl = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
        src = "/mnt/d" + Path(__file__).resolve().as_posix()[2:]
        dst = "/home/lenovo2/t042_monitor.json"
        r = subprocess.run(wsl + ["bash", "-c",
                                  "cp %s /home/lenovo2/t042_monitor.py && "
                                  "cd /home/lenovo2 && python3 t042_monitor.py "
                                  "--out %s 2>&1 | tail -3" % (src, dst)],
                           capture_output=True, text=True, timeout=600)
        print(r.stdout + r.stderr)
        if r.returncode != 0:
            return 2
        back = subprocess.run(wsl + ["bash", "-c",
                                     "cp %s '%s' && echo COPIED"
                                     % (dst, "/mnt/d" + (repo / "outputs" / "T-042").as_posix()[2:] + "/monitor_stability_b15.json")],
                              capture_output=True, text=True, timeout=300)
        print(back.stdout + back.stderr)
        return 0 if "COPIED" in back.stdout else 2
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    result = analyze()
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(json.dumps({"out": args.out,
                      "resume_only_change": result["resume_only"]["monitor_relative_change"],
                      "concatenated_status": result["concatenated"]["status"],
                      "final_dp_pa": result["final_dp_pa"],
                      "mass_imbalance_final": result["mass_imbalance"]["final"],
                      "mass_imbalance_max": result["mass_imbalance"]["max_over_resume"],
                      }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
