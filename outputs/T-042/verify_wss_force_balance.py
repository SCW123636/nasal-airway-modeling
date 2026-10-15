"""T-042 known-answer verification for the wallShearStress extraction path.

Why this exists
---------------
`work/lib/extract_cfd_metrics.py` has its delta_p / flow / mass-imbalance path
verified against an analytic Poiseuille reference case
(`test_extract_cfd_metrics.py::test_verified_case_regression`, 1% tolerance).
Its **wallShearStress path has never been verified**: the reference case carries
no wallShearStress field at all, so `wall_shear_force_n` has never been checked
against anything. Per project rule 3 ("every criterion is first verified against
a known answer with a source"), we do not use it on a patient case until it is.

Known answer (axial force balance, grid-independent)
----------------------------------------------------
Steady fully-developed flow between parallel plates: the streamwise pressure
force on the cross-section is balanced exactly by the total wall shear force.

    F_wall_total  =  delta_p  *  A_cross          (in Pa * m^2 = N)

extract_cfd_metrics integrates rho * |wallShearStress| * dA over wall patches,
where OpenFOAM's wallShearStress is kinematic (m^2/s^2), so the equivalent
kinematic identity is:

    sum(|tau_kin| * dA)  =  delta_p_kin * A_cross

Both delta_p_kin and the integral come from the same script, so the check is
independent of rho.

Geometry (from system/blockMeshDict of the verified reference case)
-------------------------------------------------------------------
  L = 0.040 m (streamwise, x)
  h = 0.002 m (plate gap, y)
  w = 0.001 m (spanwise, z; frontAndBack is `empty` -> 2-D)
  A_cross = h * w = 2.0e-6 m^2

  => this is PLANE Poiseuille (two parallel plates), NOT a circular tube.
     tau_wall = delta_p * h / (2 L)  would be the per-wall value; we check the
     cleaner integral form instead, which needs no assumption about which walls
     are counted.

Output
------
Writes `outputs/T-042/wss_force_balance_verification.json` with pass/fail,
both values, the relative error, and the exact commands used. Exit code 0 on
pass, 1 on fail, 2 on infrastructure error.
"""
import json
import subprocess
import sys
from pathlib import Path

WSL = ["wsl.exe", "-d", "Ubuntu-22.04", "--"]
SRC_REL = ("work/07_cfd_pipeline/solver_reference/results/"
           "poiseuille_v1912_verified/medium")
WSL_CASE = "/home/lenovo2/t042_wss_verify"
A_CROSS = 0.002 * 0.001          # h * w, m^2  (from blockMeshDict, see docstring)
TOL = 0.02                       # 2% -- CFD wall-gradient extraction, not analytic

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "outputs" / "T-042" / "wss_force_balance_verification.json"
METRIC_JSON = REPO / "outputs" / "T-042" / "wss_verify_metrics.json"
# Work on a COPY under this card's outputs: the shared reference case must stay clean.
WORK = REPO / "outputs" / "T-042" / "poiseuille_ref"


def wsl_path(p):
    """Windows Path (D:/x) -> WSL mount path (/mnt/d/x)."""
    posix = p.as_posix()
    return "/mnt/" + posix[0].lower() + posix[2:]


def sh(args, timeout=1200):
    r = subprocess.run(WSL + args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


def main():
    steps = []

    # 0. copy the shared reference case into this card's own output dir
    src = REPO / SRC_REL
    if not src.is_dir():
        finish(steps, "error", "reference case missing: " + str(src))
        return 2
    if WORK.exists():
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(WORK)], capture_output=True)
    subprocess.run(["robocopy", str(src), str(WORK), "/E"], capture_output=True)
    if not (WORK / "log.simpleFoam").is_file():
        finish(steps, "error", "case copy incomplete")
        return 2
    steps.append({"step": "copy_reference_case_to_T-042", "rc": 0,
                  "note": "shared reference case left untouched"})

    # 1. copy to native Linux FS (never run OpenFOAM on /mnt)
    rc, out = sh(["bash", "-c",
                  "rm -rf %s && cp -r '%s' %s && echo COPIED"
                  % (WSL_CASE, wsl_path(WORK), WSL_CASE)])
    steps.append({"step": "copy_case_to_native_fs", "rc": rc, "tail": out[-300:]})
    if rc != 0:
        finish(steps, "error", "case copy failed")
        return 2

    # 2. produce the wallShearStress field (no re-solve; pure post-processing)
    #    NOTE: the standalone `postProcess` utility dies with
    #    "Unable to find turbulence model in the database" because wallShearStress
    #    needs the turbulenceModel object; the solver-wrapped form
    #    `simpleFoam -postProcess` builds it (laminar -> Stokes) and then only
    #    post-processes. Same for the patient case (see extract_b15_metrics.py).
    rc, out = sh(["bash", "-c",
                  "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
                  "&& simpleFoam -postProcess -func wallShearStress -latestTime "
                  "> log.postProcess 2>&1; echo RC=$?" % WSL_CASE], 3600)
    steps.append({"step": "postProcess -func wallShearStress", "rc": rc, "tail": out[-600:]})

    # 3. export ascii VTK the extractor can parse
    rc, out = sh(["bash", "-c",
                  "cd %s && source /usr/share/openfoam/etc/bashrc >/dev/null 2>&1 "
                  "&& foamToVTK -ascii > log.foamToVTK 2>&1; echo RC=$?"
                  % WSL_CASE])
    steps.append({"step": "foamToVTK -ascii", "rc": rc, "tail": out[-600:]})
    if rc != 0:
        finish(steps, "error", "foamToVTK failed")
        return 2

    # 4. copy VTK + postProcess log back into this card's working case
    rc, out = sh(["bash", "-c",
                  "rm -rf '%s/VTK' && cp -r %s/VTK '%s/' "
                  "&& cp %s/log.postProcess '%s/' && echo CPOUT"
                  % (wsl_path(WORK), WSL_CASE, wsl_path(WORK),
                     WSL_CASE, wsl_path(WORK))])
    steps.append({"step": "copy_vtk_back", "rc": rc, "tail": out[-300:]})
    if rc != 0:
        finish(steps, "error", "copy back failed")
        return 2

    # 5. run the extractor on this card's copy (pure stdlib, runs on Windows python)
    proc = subprocess.run(
        [sys.executable, "-m", "extract_cfd_metrics",
         "--case", str(WORK), "--out", str(METRIC_JSON)],
        cwd=str(REPO / "work" / "lib"), capture_output=True, text=True)
    steps.append({"step": "extract_cfd_metrics", "rc": proc.returncode,
                  "tail": (proc.stdout + proc.stderr)[-600:]})
    if rc != 0 or not METRIC_JSON.is_file():
        finish(steps, "error", "extractor failed")
        return 2

    metrics = json.loads(METRIC_JSON.read_text(encoding="utf-8"))["metrics"]
    wall = metrics["wall_shear_force_n"]
    if wall.get("status") == "not_computed":
        finish(steps, "fail", "wallShearStress still absent: " + str(wall.get("reason")))
        return 1

    delta_p_pa = metrics["delta_p_pa"]["value"]
    rho = json.loads(METRIC_JSON.read_text(encoding="utf-8"))["rho_kg_m3"]
    delta_p_kin = delta_p_pa / rho

    expected_kin_integral = delta_p_kin * A_CROSS      # sum(|tau_kin| * dA)
    computed_kin_integral = wall["value_n"] / rho
    rel_err = abs(computed_kin_integral - expected_kin_integral) / abs(expected_kin_integral)

    result = {
        "verdict": "PASS" if rel_err <= TOL else "FAIL",
        "tolerance_rel": TOL,
        "rel_error": rel_err,
        "known_answer": {
            "identity": "sum(|tau_kin| * dA) = delta_p_kin * A_cross (axial force balance)",
            "source": "steady fully-developed plane Poiseuille; grid-independent",
            "A_cross_m2": A_CROSS,
            "delta_p_pa": delta_p_pa,
            "delta_p_kinematic": delta_p_kin,
            "expected_kinematic_integral": expected_kin_integral,
        },
        "computed": {
            "wall_shear_force_n": wall["value_n"],
            "kinematic_integral": computed_kin_integral,
        },
        "case": {"delta_p_pa": delta_p_pa,
                 "mass_imbalance_frac": metrics["mass_imbalance_frac"],
                 "converged": metrics["converged"]},
        "steps": steps,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"], "rel_error": rel_err,
                      "expected": expected_kin_integral,
                      "computed": computed_kin_integral}, indent=2))
    return 0 if result["verdict"] == "PASS" else 1


def finish(steps, verdict, reason):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"verdict": verdict, "reason": reason, "steps": steps},
                              ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": reason}, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
