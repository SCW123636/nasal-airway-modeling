"""T-042: wall shear stress DISTRIBUTION for the b15 maxh1 run.

The verified extraction path (`extract_cfd_metrics.py`, checked against the
plane-Poiseuille axial force balance at 0.087%) reports the wall-shear FORCE
INTEGRAL. This script adds the distribution: |tau| per wall face, summary
statistics and a histogram, from the same wallShearStress field.

Source: the patched copy `/home/lenovo2/t042_b15_wssfix` (wall patch typed
`wall`; the live case's wall patch is typed `patch`, for which the
wallShearStress function object silently writes an all-zero field -- see the
T-042 conclusion card). The mesh geometry is identical (checkMesh counts
verified); only the patch TYPE differs, which does not enter the WSS maths.

Dual-end script (standard library only): run on Windows to copy itself into
WSL and fetch the JSON back; `python3 wss_distribution_b15.py --out <json>`
inside WSL analyses directly.

Output: outputs/T-042/wss_distribution_b15.json
"""
import json
import math
import os
import subprocess
import sys
from pathlib import Path

VTP = Path("/home/lenovo2/t042_b15_wssfix/VTK/t042_b15_wssfix_600/boundary/wall.vtp")
RHO = 1.20
HIST_EDGES = [0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 1e9]  # Pa


def read_wss_magnitudes(path):
    """|wallShearStress| in Pa per face, parsed from the ascii VTP DataArray."""
    text = path.read_text(encoding="utf-8", errors="replace")
    key = "Name='wallShearStress'"
    i = text.find(key)
    if i < 0:
        raise ValueError("no wallShearStress DataArray in " + str(path))
    start = text.find(">", i) + 1
    end = text.find("</DataArray>", start)
    body = text[start:end]
    vals = [float(x) for x in body.split()]
    if len(vals) % 3 != 0:
        raise ValueError("WSS array not a multiple of 3: %d" % len(vals))
    return [RHO * math.sqrt(vals[3 * i] ** 2 + vals[3 * i + 1] ** 2 + vals[3 * i + 2] ** 2)
            for i in range(len(vals) // 3)]


def analyze():
    mags = read_wss_magnitudes(VTP)
    n = len(mags)
    if n == 0:
        raise ValueError("empty WSS array")
    mags_sorted = sorted(mags)

    def pct(p):
        k = min(n - 1, max(0, int(round(p / 100.0 * (n - 1)))))
        return mags_sorted[k]

    hist = []
    for lo, hi in zip(HIST_EDGES, HIST_EDGES[1:]):
        c = sum(1 for m in mags if lo <= m < hi)
        hist.append({"lo_pa": lo, "hi_pa": hi, "faces": c, "fraction": c / n})
    return {
        "source_vtp": str(VTP),
        "rho_kg_m3": RHO,
        "n_faces": n,
        "tau_min_pa": mags_sorted[0],
        "tau_max_pa": mags_sorted[-1],
        "tau_mean_pa": sum(mags) / n,
        "tau_median_pa": pct(50),
        "tau_p90_pa": pct(90),
        "tau_p99_pa": pct(99),
        "all_zero": mags_sorted[-1] == 0.0,
        "histogram_pa": hist,
        "force_integral_n": None,  # filled by extract_cfd_metrics (area-weighted)
    }


def main(argv):
    if os.name == "nt":
        repo = Path(__file__).resolve().parents[2]
        wsl = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
        src = "/mnt/d" + Path(__file__).resolve().as_posix()[2:]
        dst = "/home/lenovo2/t042_wssdist.json"
        r = subprocess.run(wsl + ["bash", "-c",
                                  "cp %s /home/lenovo2/t042_wssdist.py && "
                                  "cd /home/lenovo2 && python3 t042_wssdist.py "
                                  "--out %s 2>&1 | tail -3" % (src, dst)],
                           capture_output=True, text=True, timeout=600)
        print(r.stdout + r.stderr)
        if r.returncode != 0:
            return 2
        back = subprocess.run(wsl + ["bash", "-c",
                                     "cp %s '%s' && echo COPIED"
                                     % (dst, "/mnt/d" + (repo / "outputs" / "T-042").as_posix()[2:] + "/wss_distribution_b15.json")],
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
    print(json.dumps({"out": args.out, "n_faces": result["n_faces"],
                      "tau_mean_pa": result["tau_mean_pa"],
                      "tau_max_pa": result["tau_max_pa"],
                      "all_zero": result["all_zero"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
