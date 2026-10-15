"""Synthetic circular-tube 9-grid matrix for the M3 pure-numerical-axis triage (T-036).

Purpose: isolate the numerical axis (solver settings + mesh resolution) from the
patient-specific mesh-defect axis, to discriminate the four candidate causes
(H1-H4) of the patient b15 residual floor, WITHOUT depending on the p0/N6 gate
or any patient geometry.

The tube has a known analytic solution (Hagen-Poiseuille), Re ~ 5300 (same
regime as patient b15). Three clean meshes (refine "0 0" -> Mesh OK, no sliver)
times two solver presets give 9 cases. Each case runs the full
surface_to_case -> run_openfoam_case chain.

Presets (both keep `consistent yes` + `residualControl { p 1e-10; U 1e-8; }`):
  t006       : nNonOrth 2, U 0.7, fields{p 0.3}, grad(U) cellLimited   (mirrors T-006 Run 1)
  aggressive : nNonOrth 3, U 0.5, fields{p 0.3}, grad(U) cellLimited   (H3 "settings still tunable")

This script ONLY writes its own case directories and `outputs/T-036/`. It does
not modify surface_to_case.py / run_openfoam_case.py / mesh_cache.py /
extract_cfd_metrics.py.

NOTE on filesystem: cases are staged under C:\\ts_work\\t036_phantom (reached via
/mnt/c), reusing the same path pattern as the repo's phantom_validation.py
reference. The tube cases are tiny (<= ~1M cells), so the cross-FS overhead is
negligible; this is a recorded deviation from the "native WSL FS preferred"
guideline (see tasks/T-036.md).

Subcommands:
  --prepare    generate tube.stl + patch_map, build 3 base cases, copy+patch 6 preset cases
  --run        run the full chain per case (idempotent: skips completed cases)
  --collect    run extract_cfd_metrics + parse residual floor, write matrix.json
  --analyze    read matrix.json, print structured H1-H4 discriminants (author judgment in analysis.md)
  --prepare-degrade / --run-degrade / --collect-degrade   T-037 positive-control mode
               (wavy-wall tube, 3 amplitudes, 0.4mm, t006) -> matrix_degrade.json
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parent
REPO_WORK = LIB.parent
SURFACE_TO_CASE = LIB / "surface_to_case.py"
REPO_SOLVER = REPO_WORK / "07_cfd_pipeline" / "solver" / "run_openfoam_case.py"
EXTRACT = LIB / "extract_cfd_metrics.py"
WORK_DIR_DEFAULT = r"C:\ts_work\t036_phantom"

L_MM, D_MM = 40.0, 4.0
RHO, MU = 1.20, 1.81e-5
Q_M3_S = 2.5e-4
MESH_SIZES_MM = (0.4, 0.2, 0.1)
PRESETS = {
    "t006": {"nnonorth": 2, "u_relax": 0.7},
    "aggressive": {"nnonorth": 3, "u_relax": 0.5},
}
END_TIME_CAP = 800


def generate_tube_stl(path, segments=64):
    """Programmatic ASCII STL: straight tube along +z, solids inlet/outlet/wall (mm)."""
    radius = D_MM / 2.0
    ring = [(radius * math.cos(2 * math.pi * i / segments),
             radius * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
    solids = {"inlet": [], "outlet": [], "wall": []}
    for i in range(segments):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % segments]
        solids["inlet"].append([(0.0, 0.0, 0.0), (x1, y1, 0.0), (x0, y0, 0.0)])
        solids["outlet"].append([(0.0, 0.0, L_MM), (x0, y0, L_MM), (x1, y1, L_MM)])
        a, b = (x0, y0, 0.0), (x1, y1, 0.0)
        c, d = (x1, y1, L_MM), (x0, y0, L_MM)
        solids["wall"] += [[a, b, c], [a, c, d]]
    lines = []
    for name in ("inlet", "outlet", "wall"):
        lines.append("solid " + name)
        for tri in solids[name]:
            lines.append(" facet normal 0 0 0")
            lines.append("  outer loop")
            for v in tri:
                lines.append("   vertex %.17g %.17g %.17g" % v)
            lines.append("  endloop")
            lines.append(" endfacet")
        lines.append("endsolid " + name)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def analytic_solution():
    area = math.pi * (D_MM / 2.0 * 1e-3) ** 2
    u_mean = Q_M3_S / area
    delta_p = 128.0 * MU * (L_MM * 1e-3) * Q_M3_S / (math.pi * (D_MM * 1e-3) ** 4)
    return {"delta_p_pa": delta_p, "u_mean_m_s": u_mean, "u_peak_m_s": 2.0 * u_mean,
            "reynolds": RHO * u_mean * (D_MM * 1e-3) / MU}


def wsl_path(path):
    text = str(Path(path).resolve())
    drive, rest = text[0], text[2:].lstrip("\\/")
    return "/mnt/" + drive.lower() + "/" + rest.replace("\\", "/")


def wsl_solver_command(case):
    # IMPORTANT: pass argv as a list and run with shell=False. A shell string
    # through Git Bash mangles the Chinese /mnt/d repo path into the wsl argv
    # (observed: a PortableGit prefix got prepended). A list avoids shell quoting
    # entirely; CreateProcess delivers the Unicode path to wsl.exe correctly.
    return ["wsl.exe", "-d", "Ubuntu-22.04", "--", "env",
            "WM_PROJECT_DIR=/usr/share/openfoam", "FOAM_ETC=/usr/share/openfoam/etc",
            "WM_PROJECT_VERSION=v1912", "python3", wsl_path(REPO_SOLVER),
            "--case", wsl_path(case),
            "--steps", "blockMesh,snappyHexMesh,checkMesh,simpleFoam,foamToVTK"]


def case_name(size, preset):
    return ("case_h%g_%s" % (size, preset)).replace(".", "p")


def patch_fv_solution(case, preset):
    p = case / "system" / "fvSolution"
    t = p.read_text(encoding="ascii", errors="replace")
    t = t.replace("nNonOrthogonalCorrectors 0;",
                  "nNonOrthogonalCorrectors %d;" % preset["nnonorth"])
    t = t.replace("relaxationFactors { equations { U 0.9; } }",
                  "relaxationFactors { equations { U %s; } fields { p 0.3; } }"
                  % ("%g" % preset["u_relax"]))
    p.write_text(t, encoding="ascii")


def patch_fv_schemes(case):
    p = case / "system" / "fvSchemes"
    t = p.read_text(encoding="ascii", errors="replace")
    t = t.replace("default         Gauss linear;",
                  "default         Gauss linear;\n    grad(U) cellLimited Gauss linear 1;")
    p.write_text(t, encoding="ascii")


def patch_control_dict(case, end_time=END_TIME_CAP):
    p = case / "system" / "controlDict"
    t = p.read_text(encoding="ascii", errors="replace")
    t = t.replace("endTime 4000;", "endTime %d;" % end_time)
    p.write_text(t, encoding="ascii")


def prepare(work_dir):
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    tube = work_dir / "tube.stl"
    generate_tube_stl(tube)
    (work_dir / "patch_map.json").write_text(
        json.dumps({"inlet": "inlet", "outlet": "outlet", "wall": "wall"}, indent=2) + "\n",
        encoding="utf-8")
    base_cases = {}
    for size in MESH_SIZES_MM:
        base = work_dir / ("base_h%g" % size).replace(".", "p")
        if base.exists():
            shutil.rmtree(base)
        result = subprocess.run([sys.executable, str(SURFACE_TO_CASE),
                                 "--surface", str(tube), "--patch-map", str(work_dir / "patch_map.json"),
                                 "--out", str(base), "--cell-size", str(size), "--refine-level", "0 0",
                                 "--location-in-mesh", "0 0 %g" % (L_MM / 2.0),
                                 "--inlet-profile", "parabolic", "--flow-rate-m3s", "2.5e-4",
                                 "--solver", "laminar"])
        if result.returncode != 0:
            print("phantom_matrix error: surface_to_case failed for h=%g" % size, file=sys.stderr)
            return 2
        base_cases[size] = base
    for size, base in base_cases.items():
        for preset_name, preset in PRESETS.items():
            case = work_dir / case_name(size, preset_name)
            if case.exists():
                shutil.rmtree(case)
            shutil.copytree(base, case)
            patch_fv_solution(case, preset)
            patch_fv_schemes(case)
            patch_control_dict(case)
            (case / "preset_applied.json").write_text(
                json.dumps({"preset": preset_name, "nnonorth": preset["nnonorth"],
                            "u_relax": preset["u_relax"],
                            "fields_p": 0.3, "gradU": "cellLimited Gauss linear 1",
                            "consistent": True, "end_time_cap": END_TIME_CAP}, indent=2) + "\n",
                encoding="utf-8")
    print(json.dumps({"work_dir": str(work_dir),
                      "tube_sha256": __import__("hashlib").sha256(tube.read_bytes()).hexdigest(),
                      "cases": [case_name(s, p) for s in MESH_SIZES_MM for p in PRESETS],
                      "next": "run with --run"}, indent=2))
    return 0


def run_cases(work_dir):
    work_dir = Path(work_dir)
    outcomes = {}
    for size in MESH_SIZES_MM:
        for preset_name in PRESETS:
            case = work_dir / case_name(size, preset_name)
            rm = case / "run_manifest.json"
            if rm.is_file():
                try:
                    if json.loads(rm.read_text(encoding="utf-8")).get("execution_status") == "completed":
                        outcomes[case.name] = {"status": "skipped_completed"}
                        continue
                except Exception:
                    pass
            command = wsl_solver_command(case)
            try:
                proc = subprocess.run(command, shell=False)
                outcomes[case.name] = {"returncode": proc.returncode, "command": command}
            except OSError as exc:
                outcomes[case.name] = {"status": "wsl_unavailable", "error": repr(exc),
                                       "command": command}
    print(json.dumps(outcomes, indent=2))
    return 0 if all(o.get("returncode") == 0 for o in outcomes.values()) else 1


def parse_residuals(log_path):
    if not log_path.is_file():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    parts = text.split("Time = ")
    p_finals, ux_finals, p_inits = [], [], []
    for chunk in parts[1:]:
        pm = re.findall(r"Solving for p, Initial residual = ([0-9.eE+-]+), Final residual = ([0-9.eE+-]+)",
                        chunk)
        um = re.findall(r"Solving for Ux, Initial residual = [0-9.eE+-]+, Final residual = ([0-9.eE+-]+)",
                        chunk)
        if pm:
            p_inits.append(float(pm[-1][0]))
            p_finals.append(float(pm[-1][1]))
        if um:
            ux_finals.append(float(um[-1]))
    if not p_finals:
        return None
    floor_idx0 = 10 if len(p_finals) > 10 else 0
    floor_p = min(p_finals[floor_idx0:])
    floor_p_init = p_inits[floor_idx0:][p_finals[floor_idx0:].index(floor_p)]
    last_p = p_finals[-1]
    rose = (last_p - floor_p) / floor_p if (floor_p > 0 and last_p > floor_p * 1.1) else 0.0
    floor_ux = min(ux_finals[floor_idx0:]) if ux_finals else None
    return {
        "n_steps": len(p_finals),
        "floor_p_final": floor_p,
        "floor_p_initial": floor_p_init,
        "last_p_final": last_p,
        "floor_rise_ratio": rose,
        "floor_ux_final": floor_ux,
        "converged_token": "SIMPLE solution converged" in text,
    }


def collect(work_dir, out_dir):
    work_dir = Path(work_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    analytic = analytic_solution()
    rows = []
    for size in MESH_SIZES_MM:
        for preset_name in PRESETS:
            case = work_dir / case_name(size, preset_name)
            rm = case / "run_manifest.json"
            if not rm.is_file():
                print("phantom_matrix error: %s missing run_manifest" % case, file=sys.stderr)
                return 2
            manifest = json.loads(rm.read_text(encoding="utf-8"))
            if manifest.get("execution_status") != "completed":
                print("phantom_matrix error: %s not completed: %r"
                      % (case, manifest.get("error")), file=sys.stderr)
                return 2
            metrics_path = case / "metrics.json"
            res = subprocess.run([sys.executable, str(EXTRACT), "--case", str(case),
                                  "--out", str(metrics_path)])
            if res.returncode != 0:
                print("phantom_matrix error: extract failed for " + str(case), file=sys.stderr)
                return 2
            m = json.loads(metrics_path.read_text(encoding="utf-8"))["metrics"]
            dp = m["delta_p_pa"]["value"]
            peak = m["max_velocity_mps"]["value"]
            resd = parse_residuals(case / "log.simpleFoam")
            rows.append({
                "cell_size_mm": size, "preset": preset_name,
                "case": case.name,
                "delta_p_numeric_pa": dp, "delta_p_analytic_pa": analytic["delta_p_pa"],
                "delta_p_rel_error": abs(dp - analytic["delta_p_pa"]) / analytic["delta_p_pa"],
                "peak_velocity_numeric_mps": peak,
                "peak_velocity_analytic_mps": analytic["u_peak_m_s"],
                "peak_velocity_rel_error": abs(peak - analytic["u_peak_m_s"]) / analytic["u_peak_m_s"],
                "mass_imbalance_frac": m["mass_imbalance_frac"],
                "converged_extract": m["converged"],
                "residuals": resd,
            })
    out = out_dir / "matrix.json"
    payload = {
        "schema": "nasal_cfd_phantom_matrix/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "geometry": {"kind": "straight_circular_tube", "L_mm": L_MM, "D_mm": D_MM,
                     "Q_m3_s": Q_M3_S, "reynolds": analytic["reynolds"],
                     "note": "Re same regime as patient b15 (~5300); laminar solver validates chain vs analytic; not a physical-regime claim"},
        "meshes_mm": list(MESH_SIZES_MM), "presets": PRESETS,
        "analytic": analytic, "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"matrix": str(out), "rows": len(rows)}, indent=2))
    return 0


def analyze(work_dir, out_dir):
    out_dir = Path(out_dir)
    matrix_path = out_dir / "matrix.json"
    if not matrix_path.is_file():
        print("phantom_matrix error: run --collect first", file=sys.stderr)
        return 2
    data = json.loads(matrix_path.read_text(encoding="utf-8"))
    rows = data["rows"]
    # group by preset/mesh for discriminants
    by_preset = {}
    for r in rows:
        by_preset.setdefault(r["preset"], []).append(r)
    print("=== matrix summary ===")
    for r in rows:
        resd = r["residuals"] or {}
        print("h%-4g %-11s dp_err=%7.3f%% floor_p=%.3e rise=%.3f steps=%d conv=%s imb=%.2e"
              % (r["cell_size_mm"], r["preset"], r["delta_p_rel_error"] * 100,
                 resd.get("floor_p_final", float("nan")), resd.get("floor_rise_ratio", 0.0),
                 resd.get("n_steps", -1), resd.get("converged_token", False),
                 r["mass_imbalance_frac"] or 0))
    # crude discriminants (author judgment lives in analysis.md)
    print("\n=== H1-H4 crude discriminants (raw; author judgment in analysis.md) ===")
    floors = [(r["preset"], r["cell_size_mm"], (r["residuals"] or {}).get("floor_p_final"))
              for r in rows]
    print("floors:", floors)
    return 0


# ---------------------------------------------------------------------------
# T-037 degrade mode: positive control for H1 (patient residual floor = mesh defects)
# ---------------------------------------------------------------------------
# Degraded tube = straight tube whose wall radius is perturbed by a tapered
# angular wave. The taper sin(pi*z/L) forces r -> R at both ends, so the inlet
# and outlet disks stay planar (clean BCs); only the mid-wall is distorted, which
# is exactly where snappyHexMesh produces non-orthogonal near-wall cells. This
# mimics the patient b15 defect class (198 severe non-orth cells) in a controlled,
# single-variable way.
DEGRADE_AMPS_MM = (0.05, 0.15, 0.30)
DEGRADE_KTH = 6
DEGRADE_KZ = 3
DEGRADE_NZ = 48
DEGRADE_SEG = 64
DEGRADE_SIZE_MM = 0.4
DEGRADE_PRESET = "t006"


def generate_degraded_tube_stl(path, amp_mm, kth=DEGRADE_KTH, kz=DEGRADE_KZ,
                              nz=DEGRADE_NZ, seg=DEGRADE_SEG):
    """Wavy-wall tube (mm). r(z,theta)=R + amp*sin(pi*z/L)*sin(kth*theta)*sin(kz*2pi*z/L)."""
    R = D_MM / 2.0
    zs = [L_MM * i / (nz - 1) for i in range(nz)]
    rings = []
    for z in zs:
        taper = math.sin(math.pi * z / L_MM)
        rad = []
        for j in range(seg):
            theta = 2.0 * math.pi * j / seg
            rr = R + amp_mm * taper * math.sin(kth * theta) * math.sin(kz * 2.0 * math.pi * z / L_MM)
            rad.append((rr * math.cos(theta), rr * math.sin(theta), z))
        rings.append(rad)
    solids = {"inlet": [], "outlet": [], "wall": []}
    # inlet fan at z=0 (planar disk at R), outlet fan at z=L (planar disk at R)
    for name, ring in (("inlet", rings[0]), ("outlet", rings[-1])):
        for j in range(seg):
            a = ring[j]
            b = ring[(j + 1) % seg]
            solids[name].append([(0.0, 0.0, a[2]), b, a])
    # wall quads between consecutive rings
    for i in range(nz - 1):
        for j in range(seg):
            a = rings[i][j]
            b = rings[i][(j + 1) % seg]
            c = rings[i + 1][(j + 1) % seg]
            d = rings[i + 1][j]
            solids["wall"] += [[a, b, c], [a, c, d]]
    lines = []
    for name in ("inlet", "outlet", "wall"):
        lines.append("solid " + name)
        for tri in solids[name]:
            lines.append(" facet normal 0 0 0")
            lines.append("  outer loop")
            for v in tri:
                lines.append("   vertex %.17g %.17g %.17g" % v)
            lines.append("  endloop")
            lines.append(" endfacet")
        lines.append("endsolid " + name)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def degrade_case_name(amp):
    return "deg_%.3g_t006" % amp


def prepare_degrade(work_dir):
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "patch_map.json").write_text(
        json.dumps({"inlet": "inlet", "outlet": "outlet", "wall": "wall"}, indent=2) + "\n",
        encoding="utf-8")
    built = []
    for amp in DEGRADE_AMPS_MM:
        tube = work_dir / ("tube_deg_%.3g.stl" % amp)
        generate_degraded_tube_stl(tube, amp)
        base = work_dir / ("base_deg_%.3g" % amp)
        if base.exists():
            shutil.rmtree(base)
        res = subprocess.run([sys.executable, str(SURFACE_TO_CASE),
                              "--surface", str(tube), "--patch-map", str(work_dir / "patch_map.json"),
                              "--out", str(base), "--cell-size", str(DEGRADE_SIZE_MM),
                              "--refine-level", "0 0",
                              "--location-in-mesh", "0 0 %g" % (L_MM / 2.0),
                              "--inlet-profile", "parabolic", "--flow-rate-m3s", "2.5e-4",
                              "--solver", "laminar"])
        if res.returncode != 0:
            print("phantom_matrix error: surface_to_case failed for deg amp=%g" % amp, file=sys.stderr)
            return 2
        case = work_dir / degrade_case_name(amp)
        if case.exists():
            shutil.rmtree(case)
        shutil.copytree(base, case)
        patch_fv_solution(case, PRESETS[DEGRADE_PRESET])
        patch_fv_schemes(case)
        patch_control_dict(case)
        (case / "degrade_applied.json").write_text(
            json.dumps({"amp_mm": amp, "kth": DEGRADE_KTH, "kz": DEGRADE_KZ,
                        "preset": DEGRADE_PRESET, "cell_size_mm": DEGRADE_SIZE_MM,
                        "taper": "sin(pi*z/L) -> ends planar",
                        "intent": "positive control for H1: inject near-wall distortion"}, indent=2) + "\n",
            encoding="utf-8")
        built.append(case.name)
    print(json.dumps({"work_dir": str(work_dir), "cases": built, "next": "run with --run-degrade"}, indent=2))
    return 0


def run_degrade(work_dir):
    work_dir = Path(work_dir)
    outcomes = {}
    for amp in DEGRADE_AMPS_MM:
        case = work_dir / degrade_case_name(amp)
        rm = case / "run_manifest.json"
        if rm.is_file():
            try:
                if json.loads(rm.read_text(encoding="utf-8")).get("execution_status") == "completed":
                    outcomes[case.name] = {"status": "skipped_completed"}
                    continue
            except Exception:
                pass
        command = wsl_solver_command(case)
        try:
            proc = subprocess.run(command, shell=False)
            outcomes[case.name] = {"returncode": proc.returncode}
        except OSError as exc:
            outcomes[case.name] = {"status": "wsl_unavailable", "error": repr(exc)}
    print(json.dumps(outcomes, indent=2))
    return 0 if all(o.get("returncode") == 0 for o in outcomes.values()) else 1


def parse_checkmesh(log_path):
    if not log_path.is_file():
        return None
    t = log_path.read_text(encoding="utf-8", errors="replace")
    def grab(pat):
        m = re.search(pat, t)
        return float(m.group(1)) if m else None
    # OpenFOAM prints "Mesh non-orthogonality Max: 45.7 average: 7.4"
    max_no = grab(r"Mesh non-orthogonality Max:\s*([0-9.eE+-]+)")
    severe = grab(r"Number of severely non-orthogonal\s*\([^)]*\)\s*faces\s*=\s*([0-9.eE+-]+)")
    det_bad_count = grab(r"determinant less than 0\.001 = ([0-9.eE+-]+)")
    concave = grab(r"Concave cells \(using face planes\) found, number of cells:\s*([0-9.eE+-]+)")
    bounded = "Mesh OK" in t
    failed = "Failed" in t
    return {"max_non_ortho_deg": max_no, "severe_non_ortho_faces": severe,
            "det_lt_001_cells": det_bad_count, "concave_cells": concave,
            "mesh_ok": bounded, "failed_any_check": failed}


def collect_degrade(work_dir, out_dir):
    work_dir = Path(work_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    analytic = analytic_solution()
    rows = []
    for amp in DEGRADE_AMPS_MM:
        case = work_dir / degrade_case_name(amp)
        rm = case / "run_manifest.json"
        if not rm.is_file():
            print("phantom_matrix error: %s missing run_manifest" % case, file=sys.stderr)
            return 2
        manifest = json.loads(rm.read_text(encoding="utf-8"))
        cm = parse_checkmesh(case / "log.checkMesh")
        if manifest.get("execution_status") != "completed":
            # Tolerate mesh-gate refusals: the refusal itself is a result (records
            # that this distortion level exceeds the pipeline's own quality gate).
            err = manifest.get("error")
            rejected = bool(err) and ("Mesh quality" in str(err) or "refusing to solve" in str(err))
            rows.append({
                "amp_mm": amp, "preset": DEGRADE_PRESET, "cell_size_mm": DEGRADE_SIZE_MM,
                "case": case.name, "status": "rejected_mesh_gate" if rejected else "incomplete",
                "reject_reason": str(err) if rejected else repr(err),
                "delta_p_numeric_pa": None, "delta_p_rel_error": None,
                "mass_imbalance_frac": None, "converged_extract": None,
                "residuals": None, "checkmesh": cm,
            })
            continue
        metrics_path = case / "metrics.json"
        res = subprocess.run([sys.executable, str(EXTRACT), "--case", str(case), "--out", str(metrics_path)])
        if res.returncode != 0:
            print("phantom_matrix error: extract failed for " + str(case), file=sys.stderr)
            return 2
        m = json.loads(metrics_path.read_text(encoding="utf-8"))["metrics"]
        dp = m["delta_p_pa"]["value"]
        resd = parse_residuals(case / "log.simpleFoam")
        rows.append({
            "amp_mm": amp, "preset": DEGRADE_PRESET, "cell_size_mm": DEGRADE_SIZE_MM,
            "case": case.name, "status": "completed",
            "delta_p_numeric_pa": dp, "delta_p_analytic_pa": analytic["delta_p_pa"],
            "delta_p_rel_error": abs(dp - analytic["delta_p_pa"]) / analytic["delta_p_pa"],
            "mass_imbalance_frac": m["mass_imbalance_frac"],
            "converged_extract": m["converged"],
            "residuals": resd, "checkmesh": cm,
        })
    out = out_dir / "matrix_degrade.json"
    # Attach the T-036 clean-tube (same 0.4mm / t006 baseline) as reference so the
    # matrix is a self-contained clean-vs-degraded comparison.
    ref_case = Path(WORK_DIR_DEFAULT) / "case_h0p4_t006"
    if ref_case.is_dir():
        try:
            rm = json.loads((ref_case / "run_manifest.json").read_text(encoding="utf-8"))
            ref_m = json.loads((ref_case / "metrics.json").read_text(encoding="utf-8"))["metrics"] \
                if (ref_case / "metrics.json").is_file() else None
            ref_resd = parse_residuals(ref_case / "log.simpleFoam")
            ref_cm = parse_checkmesh(ref_case / "log.checkMesh")
            rows.append({
                "amp_mm": 0.0, "preset": DEGRADE_PRESET, "cell_size_mm": DEGRADE_SIZE_MM,
                "case": ref_case.name, "status": "reference_clean",
                "delta_p_numeric_pa": ref_m["delta_p_pa"]["value"] if ref_m else None,
                "delta_p_analytic_pa": analytic["delta_p_pa"],
                "delta_p_rel_error": (abs(ref_m["delta_p_pa"]["value"] - analytic["delta_p_pa"]) / analytic["delta_p_pa"]) if ref_m else None,
                "mass_imbalance_frac": ref_m["mass_imbalance_frac"] if ref_m else None,
                "converged_extract": ref_m["converged"] if ref_m else None,
                "residuals": ref_resd, "checkmesh": ref_cm,
            })
        except Exception as exc:
            print("phantom_matrix warn: reference_clean skipped: %r" % exc, file=sys.stderr)
    payload = {
        "schema": "nasal_cfd_phantom_degrade/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "geometry": {"kind": "wavy_wall_tube", "L_mm": L_MM, "D_mm": D_MM, "R_mm": D_MM / 2.0,
                     "Q_m3_s": Q_M3_S, "reynolds": analytic["reynolds"],
                     "amps_mm": list(DEGRADE_AMPS_MM), "kth": DEGRADE_KTH, "kz": DEGRADE_KZ,
                     "intent": "positive control for H1: inject controlled near-wall distortion"},
        "analytic": analytic, "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"matrix": str(out), "rows": len(rows)}, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=WORK_DIR_DEFAULT)
    parser.add_argument("--out-dir", default=None, help="collect/analyze output dir (default <work-dir>)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--collect", action="store_true")
    mode.add_argument("--analyze", action="store_true")
    mode.add_argument("--prepare-degrade", action="store_true")
    mode.add_argument("--run-degrade", action="store_true")
    mode.add_argument("--collect-degrade", action="store_true")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or args.work_dir
    if args.prepare:
        return prepare(args.work_dir)
    if args.run:
        return run_cases(args.work_dir)
    if args.collect:
        return collect(args.work_dir, out_dir)
    if args.prepare_degrade:
        return prepare_degrade(args.work_dir)
    if args.run_degrade:
        return run_degrade(args.work_dir)
    if args.collect_degrade:
        return collect_degrade(args.work_dir, out_dir)
    return analyze(args.work_dir, out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
