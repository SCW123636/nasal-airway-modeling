"""Straight circular tube phantom end-to-end validation for the S1->S2->S3 chain.

No patient data, no human review needed: the phantom has a known analytic
solution (Hagen-Poiseuille), so this is the only batch-1 stage that can
self-certify a ground truth.

Subcommands (resumable; a blocked wsl.exe never strands the workflow):
    --prepare   generate the tube STL + patch map, build both cases via
                surface_to_case.py, stage the WSL solver scripts under
                <work-dir>/_wsl, and print the exact manual WSL commands
    --run       execute run_openfoam_case.py per case through wsl.exe
                (falls back to printing the manual commands)
    --collect   require completed run_manifest.json, run extract_cfd_metrics.py
                per case, reconcile against the analytic solution, and write
                validation.json with a pass/fail verdict (exit 1 on fail; the
                tolerances are never widened to force a pass)

Phantom: L=40 mm, D=4 mm straight tube along +z, named solids
inlet/outlet/wall, Q = 15 L/min = 2.5e-4 m3/s, mu = 1.81e-5 Pa s.
The inlet uses an area-normalized parabolic profile (applied by
run_openfoam_case.py after meshing), so the comparison target is the
fully-developed Hagen-Poiseuille solution:
    delta_p = 128 mu L Q / (pi D^4), peak velocity = 2 * U_mean.
Note: with laminar physics at Re ~ 5300 this validates the solver chain
against the laminar analytic solution; it is not a claim about the physical
flow regime.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

SCRIPT_VERSION = "1.1.0"
L_MM, D_MM = 40.0, 4.0
RHO, MU = 1.20, 1.81e-5
Q_M3_S = 2.5e-4
CELL_SIZES_MM = (0.4, 0.2)
TOL_COARSE, TOL_FINE, TOL_PEAK = 0.05, 0.02, 0.05
MAX_IMBALANCE = 1e-6
WORK_DIR_DEFAULT = r"C:\ts_work\phantom_validation"
LIB = Path(__file__).resolve().parent
REPO_WORK = LIB.parent
SOLVER_DIR = REPO_WORK / "07_cfd_pipeline"


def generate_tube_stl(path, segments=64):
    """Programmatic ASCII STL: straight tube along +z, solids inlet/outlet/wall (mm)."""
    radius = D_MM / 2.0
    ring = [(radius * math.cos(2 * math.pi * i / segments),
             radius * math.sin(2 * math.pi * i / segments)) for i in range(segments)]
    solids = {"inlet": [], "outlet": [], "wall": []}
    for i in range(segments):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % segments]
        # inlet disk at z=0, outward normal -z: (center, p_{i+1}, p_i)
        solids["inlet"].append([(0.0, 0.0, 0.0), (x1, y1, 0.0), (x0, y0, 0.0)])
        # outlet disk at z=L, outward normal +z: (center, p_i, p_{i+1})
        solids["outlet"].append([(0.0, 0.0, L_MM), (x0, y0, L_MM), (x1, y1, L_MM)])
        # wall quad -> two triangles, outward radial normal
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
            "reynolds": RHO * u_mean * (D_MM * 1e-3) / MU,
            "equation": "delta_p = 128 mu L Q / (pi D^4); u_peak = 2 u_mean (Hagen-Poiseuille)"}


def case_name(cell_size):
    return ("case_h%g" % cell_size).replace(".", "p")


def wsl_path(path):
    text = str(Path(path).resolve())
    drive, rest = text[0], text[2:].lstrip("\\/")
    return "/mnt/" + drive.lower() + "/" + rest.replace("\\", "/")


def wsl_command(work_dir, case):
    script = Path(work_dir) / "_wsl" / "solver" / "run_openfoam_case.py"
    return ("wsl.exe -d Ubuntu-22.04 -- env WM_PROJECT_DIR=/usr/share/openfoam "
            "FOAM_ETC=/usr/share/openfoam/etc WM_PROJECT_VERSION=v1912 python3 "
            + wsl_path(script) + " --case " + wsl_path(case))


def prepare(work_dir):
    work_dir = Path(work_dir)
    if work_dir.exists() and any(work_dir.iterdir()):
        print("phantom_validation error: work dir is not empty (choose a new directory): "
              + str(work_dir), file=sys.stderr)
        return 2
    (work_dir / "_wsl" / "solver").mkdir(parents=True)
    (work_dir / "_wsl" / "solver_reference").mkdir(parents=True)
    import shutil
    shutil.copy2(SOLVER_DIR / "solver" / "run_openfoam_case.py",
                 work_dir / "_wsl" / "solver" / "run_openfoam_case.py")
    shutil.copy2(SOLVER_DIR / "solver_reference" / "run_reference.py",
                 work_dir / "_wsl" / "solver_reference" / "run_reference.py")
    tube = work_dir / "tube.stl"
    generate_tube_stl(tube)
    patch_map = work_dir / "patch_map.json"
    patch_map.write_text(json.dumps({"inlet": "inlet", "outlet": "outlet", "wall": "wall"},
                                    indent=2) + "\n", encoding="utf-8")
    commands = []
    for cell_size in CELL_SIZES_MM:
        case = work_dir / case_name(cell_size)
        result = subprocess.run([sys.executable, str(LIB / "surface_to_case.py"),
                                 "--surface", str(tube), "--patch-map", str(patch_map),
                                 "--out", str(case), "--cell-size", str(cell_size),
                                 "--location-in-mesh", "0 0 %g" % (L_MM / 2.0),
                                 "--inlet-profile", "parabolic", "--dry-run"])
        if result.returncode != 0:
            print("phantom_validation error: surface_to_case failed for h=%g" % cell_size,
                  file=sys.stderr)
            return 2
        commands.append(wsl_command(work_dir, case))
    print(json.dumps({
        "work_dir": str(work_dir),
        "tube_sha256": hashlib.sha256(tube.read_bytes()).hexdigest(),
        "cases": [case_name(c) for c in CELL_SIZES_MM],
        "next": "run each command, or re-run this script with --run",
        "manual_wsl_commands": commands}, indent=2))
    return 0


def run_cases(work_dir):
    work_dir = Path(work_dir)
    outcomes = {}
    for cell_size in CELL_SIZES_MM:
        case = work_dir / case_name(cell_size)
        if not case.is_dir():
            print("phantom_validation error: missing case %s (run --prepare first)"
                  % case, file=sys.stderr)
            return 2
        command = wsl_command(work_dir, case)
        try:
            process = subprocess.run(command, shell=True)
            outcomes[case.name] = {"returncode": process.returncode, "command": command}
            if process.returncode != 0:
                outcomes[case.name]["status"] = "failed_run_manual_command_above"
        except OSError as exc:
            outcomes[case.name] = {"status": "wsl_unavailable_run_manually",
                                   "error": repr(exc), "command": command}
    print(json.dumps(outcomes, indent=2))
    return 0 if all(o.get("returncode") == 0 for o in outcomes.values()) else 1


def collect(work_dir):
    work_dir = Path(work_dir)
    analytic = analytic_solution()
    levels = []
    for cell_size in CELL_SIZES_MM:
        case = work_dir / case_name(cell_size)
        run_manifest_path = case / "run_manifest.json"
        if not run_manifest_path.is_file():
            print("phantom_validation error: %s has no run_manifest.json (run the solver first)"
                  % case, file=sys.stderr)
            return 2
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
        if run_manifest.get("execution_status") != "completed":
            print("phantom_validation error: %s run did not complete: %r"
                  % (case, run_manifest.get("error")), file=sys.stderr)
            return 2
        metrics_path = case / "metrics.json"
        result = subprocess.run([sys.executable, str(LIB / "extract_cfd_metrics.py"),
                                 "--case", str(case), "--out", str(metrics_path)])
        if result.returncode != 0:
            print("phantom_validation error: metric extraction failed for " + str(case),
                  file=sys.stderr)
            return 2
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))["metrics"]
        delta_p = metrics["delta_p_pa"]["value"]
        peak = metrics["max_velocity_mps"]["value"]
        mesh_log = (case / 'log.checkMesh').read_text(encoding='utf-8',errors='replace')
        mesh_passed = 'Mesh OK.' in mesh_log and 'Failed ' not in mesh_log and 'FOAM FATAL' not in mesh_log
        levels.append({
            "cell_size_mm": cell_size,
            "case": case.name,
            "delta_p_numeric_pa": delta_p,
            "delta_p_analytic_pa": analytic["delta_p_pa"],
            "delta_p_rel_error": abs(delta_p - analytic["delta_p_pa"]) / analytic["delta_p_pa"],
            "peak_velocity_numeric_mps": peak,
            "peak_velocity_analytic_mps": analytic["u_peak_m_s"],
            "peak_velocity_rel_error": abs(peak - analytic["u_peak_m_s"]) / analytic["u_peak_m_s"],
            "mass_imbalance_frac": metrics["mass_imbalance_frac"],
            "converged": metrics["converged"],
            "mesh_quality_passed": mesh_passed,
            "measured_flow_m3_s": metrics["total_flow_m3s"]["value"],
            "target_flow_m3_s": Q_M3_S,
            "target_flow_rel_error": abs(metrics["total_flow_m3s"]["value"] - Q_M3_S) / Q_M3_S,
            "source_sha256": {name: hashlib.sha256((case / name).read_bytes()).hexdigest()
                              for name in ("case_manifest.json", "run_manifest.json", "metrics.json",
                                           "log.checkMesh", "log.simpleFoam") if (case / name).is_file()}})
    coarse, fine = levels[0], levels[1]
    checks = {
        "delta_p_coarse_within_5pct": coarse["delta_p_rel_error"] < TOL_COARSE,
        "delta_p_fine_within_2pct": fine["delta_p_rel_error"] < TOL_FINE,
        "error_decreases_with_refinement": fine["delta_p_rel_error"] < coarse["delta_p_rel_error"],
        "mass_imbalance_below_1e-6": all(l["mass_imbalance_frac"] is not None
                                         and l["mass_imbalance_frac"] < MAX_IMBALANCE
                                         for l in levels),
        "converged": all(l["converged"] for l in levels),
        "peak_velocity_within_5pct": all(l["peak_velocity_rel_error"] < TOL_PEAK for l in levels),
        "mesh_quality_passed": all(l['mesh_quality_passed'] for l in levels),
    }
    verdict = "pass" if all(checks.values()) else "fail"
    tube = work_dir / "tube.stl"
    validation = {
        "schema": "nasal_cfd_phantom_validation/v1",
        "script": {"name": "phantom_validation.py", "version": SCRIPT_VERSION},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "phantom": {"kind": "straight_circular_tube", "L_mm": L_MM, "D_mm": D_MM,
                    "Q_m3_s": Q_M3_S, "stl_sha256": hashlib.sha256(tube.read_bytes()).hexdigest(),
                    "patch_map": {"inlet": "inlet", "outlet": "outlet", "wall": "wall"}},
        "physics": {"rho_kg_m3": RHO, "mu_Pa_s": MU,
                    "note": ("laminar solver at Re %.0f validates the chain against the laminar "
                             "analytic solution; not a physical-regime claim" % analytic["reynolds"])},
        "inlet_profile": ("area-normalized parabolic fixedValue imposed after meshing "
                          "(developed profile; no entrance-length approximation)"),
        "analytic": analytic,
        "acceptance_thresholds": {"delta_p_coarse_rel_error": TOL_COARSE,
                                  "delta_p_fine_rel_error": TOL_FINE,
                                  "peak_velocity_rel_error": TOL_PEAK,
                                  "mass_imbalance_frac": MAX_IMBALANCE},
        "levels": levels,
        "checks": checks,
        "verdict": verdict,
        "diagnostics": {
            "cause_status": "not_established",
            "note": "Computed checks establish this run's errors only. Entrance development, inlet profile and mesh resolution require independent controlled comparisons; no pressure-driven control is executed by this collector.",
        },
    }
    out = work_dir / "validation.json"
    out.write_text(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"validation": str(out), "verdict": verdict, "checks": checks}, indent=2))
    return 0 if verdict == "pass" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=WORK_DIR_DEFAULT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--collect", action="store_true")
    args = parser.parse_args(argv)
    if args.prepare:
        return prepare(args.work_dir)
    if args.run:
        return run_cases(args.work_dir)
    return collect(args.work_dir)


if __name__ == "__main__":
    raise SystemExit(main())
