"""Probe a circular tube with the OpenFOAM v1912 wedge topology.

The case is a 5-degree axisymmetric wedge with an exact blockMesh arc.  A
known pressure drop drives the sector; the measured sector flux is scaled to
the full circle and compared with Hagen-Poiseuille.  The result is a
non-patient solver diagnostic: a passing case establishes only this generated
circular-tube chain and does not certify a patient mesh or unlock patient CFD.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import importlib.util
import math
from pathlib import Path
import re
import subprocess
import sys

RHO = 1.20
MU = 1.81e-5
NU = MU / RHO
L_M = 0.16
R_M = 0.002
Q_TARGET = 2.5e-4


def analytic_pressure_drop(length):
    """Hagen-Poiseuille pressure drop in Pa for the requested tube length."""
    # Hagen-Poiseuille in radius form: delta-p = 8 mu L Q / (pi R^4).
    return 8.0 * MU * length * Q_TARGET / (math.pi * R_M ** 4)
LIB = Path(__file__).resolve().parent
SOLVER = LIB.parent / "07_cfd_pipeline" / "solver" / "run_openfoam_case.py"


def header(name, cls="dictionary"):
    return ("FoamFile\n{\n version 2.0;\n format ascii;\n class %s;\n object %s;\n}\n"
            % (cls, name))


def write_case(case: Path, end_time=3000, nx=320, nr=32, length=L_M,
               mode="pressure", side_boundary="wedge", sector_degrees=5.0):
    case.mkdir(parents=True, exist_ok=False)
    for folder in ("0", "constant", "system"):
        (case / folder).mkdir()
    # x is the pipe axis; y/z span an axisymmetric wedge.  This is
    # The collapsed hex has local axes: axial, azimuthal, radial.
    half = 0.5 * sector_degrees
    y = R_M * math.sin(math.radians(half))
    z = R_M * math.cos(math.radians(half))
    pts = [
        (0, 0, 0), (length, 0, 0), (length, 0, 0), (0, 0, 0),
        (0, -y, z), (length, -y, z), (length, y, z), (0, y, z),
    ]
    coords = "\n".join("(%.16g %.16g %.16g)" % p for p in pts)
    if side_boundary == "wedge":
        side1 = "side1 { type wedge; faces ((0 1 5 4)); }"
        side2 = "side2 { type wedge; faces ((7 6 2 3)); }"
    elif side_boundary == "cyclicAMI":
        side1 = """side1
    {
        type cyclicAMI;
        neighbourPatch side2;
        faces ((0 1 5 4));
        transform rotational;
        rotationAxis (1 0 0);
        rotationCentre (0 0 0);
    }"""
        side2 = """side2
    {
        type cyclicAMI;
        neighbourPatch side1;
        faces ((7 6 2 3));
        transform rotational;
        rotationAxis (1 0 0);
        rotationCentre (0 0 0);
    }"""
    else:
        raise ValueError("unsupported side boundary: " + side_boundary)
    angular_cells = 1 if side_boundary == "wedge" else 5
    blockmesh = header("blockMeshDict") + f"""
scale 1;
vertices ( {coords} );
blocks ( hex (0 1 2 3 4 5 6 7) ({nx} {angular_cells} {nr}) simpleGrading (1 1 1) );
edges
(
 arc 4 7 (0 0 {R_M:.16g})
 arc 5 6 ({length:.16g} 0 {R_M:.16g})
);
boundary
(
 inlet {{ type patch; faces ((0 4 7 3)); }}
 outlet {{ type patch; faces ((1 2 6 5)); }}
 {side1}
 {side2}
 walls {{ type wall; faces ((4 5 6 7) (3 2 1 0)); }}
);
mergePatchPairs ();
"""
    (case / "system/blockMeshDict").write_text(blockmesh, encoding="ascii")
    dp_target = analytic_pressure_drop(length)
    p = header("p", "volScalarField") + f"""
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{{
 inlet {{ type fixedValue; value uniform {dp_target / RHO:.16g}; }}
 outlet {{ type fixedValue; value uniform 0; }}
 side1 {{ type {side_boundary}; }}
 side2 {{ type {side_boundary}; }}
 walls {{ type zeroGradient; }}
}}
"""
    if mode == "developed-flow":
        p = p.replace(f"type fixedValue; value uniform {dp_target / RHO:.16g};",
                      "type fixedFluxPressure;")
    u = header("U", "volVectorField") + """
dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{
 inlet { type pressureInletOutletVelocity; value uniform (0 0 0); }
 outlet { type zeroGradient; }
 side1 { type SIDE_BOUNDARY; }
 side2 { type SIDE_BOUNDARY; }
 walls { type noSlip; }
}
"""
    u = u.replace("SIDE_BOUNDARY", side_boundary)
    # Start from the analytic mean velocity to avoid spending thousands of
    # SIMPLE iterations growing the flow from an all-zero field. This is only
    # an initial guess; pressure-driven cases still determine the final flux.
    u = u.replace("internalField uniform (0 0 0);",
                  "internalField uniform (%.16g 0 0);" %
                  (Q_TARGET / (math.pi * R_M ** 2)))
    (case / "0/p").write_text(p, encoding="ascii")
    (case / "0/U").write_text(u, encoding="ascii")
    (case / "constant/transportProperties").write_text(
        header("transportProperties") + f"\ntransportModel Newtonian;\nnu {NU:.16g};\n", encoding="ascii")
    (case / "constant/turbulenceProperties").write_text(
        header("turbulenceProperties") + "\nsimulationType laminar;\n", encoding="ascii")
    schemes = (LIB.parent / "07_cfd_pipeline" / "solver_reference" / "results" /
               "poiseuille_v1912_verified" / "medium" / "system" / "fvSchemes").read_text(encoding="ascii")
    # Keep the v1912 reference discretisation.  Upwind was an earlier
    # stabilisation experiment, but it adds avoidable axial diffusion in this
    # laminar tube and changes the pressure/flow comparison.
    (case / "system/fvSchemes").write_text(schemes, encoding="ascii")
    # Use absolute linear-solver tolerances so the reported final residual is
    # not merely the 1% relative stopping point allowed by relTol 0.01.
    # This tightens the solve; the acceptance thresholds below are unchanged.
    (case / "system/fvSolution").write_text(header("fvSolution") + """
solvers
{
 p { solver GAMG; tolerance 1e-12; relTol 0; smoother GaussSeidel; }
 U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0; }
}
SIMPLE
{
 nNonOrthogonalCorrectors 0;
 consistent yes;
 residualControl { p 1e-10; U 1e-8; }
}
relaxationFactors { equations { U 0.9; } }
""", encoding="ascii")
    functions = []
    for name in ("inlet", "outlet"):
        functions.append(f"""flow_{name}
{{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name {name};
 operation sum;
 fields (phi);
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}}""")
        functions.append(f"""pressure_{name}
{{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name {name};
 operation areaAverage;
 fields (p);
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}}""")
    control = header("controlDict") + f"""
application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime {end_time};
deltaT 1;
writeControl timeStep;
writeInterval {end_time};
purgeWrite 1;
writeFormat ascii;
writePrecision 12;
writeCompression off;
timeFormat general;
timePrecision 10;
runTimeModifiable false;
functions
{{
{"".join(functions)}
}}
"""
    (case / "system/controlDict").write_text(control, encoding="ascii")
    (case / "case_manifest.json").write_text(json.dumps({
        "schema": "nasal_cfd_wedge_tube/v1", "patient_data": False,
        "geometry": {"length_m": length, "radius_m": R_M, "sector_degrees": sector_degrees,
                     "mesh_cells": [nx, 1, nr],
                     "topology": "blockMesh arc + " + side_boundary},
        "physics": {"rho_kg_m3": RHO, "mu_Pa_s": MU},
        "boundary": {"mode": mode,
                     "inlet_static_pressure_Pa_gauge": dp_target if mode == "pressure" else None,
                     "outlet_static_pressure_Pa_gauge": 0.0,
                     "sector_flux_multiplier": 360.0 / (2.0 * half)},
    }, indent=2) + "\n", encoding="utf-8")


def wsl_path(path: Path):
    text = str(path.resolve())
    return "/mnt/" + text[0].lower() + "/" + text[2:].replace("\\", "/")


def quality(log):
    finals = [float(v) for v in re.findall(r"Final residual = ([0-9.eE+-]+)", log)]
    globals_ = [float(v) for v in re.findall(r"global = ([0-9.eE+-]+)", log)]
    return (len(finals) >= 3 and bool(globals_) and max(finals[-3:]) <= 1e-5
            and abs(globals_[-1]) <= 1e-6)


def last(case, name):
    path = sorted((case / "postProcessing" / name).glob("*/surfaceFieldValue.dat"))[-1]
    rows = [line.split() for line in path.read_text(errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    return float(rows[-1][1])


def set_developed_profile(case, sector_degrees=5.0):
    sys.path.insert(0, str(SOLVER.parent.parent / "solver_reference"))
    spec = importlib.util.spec_from_file_location("tube_executor", SOLVER)
    executor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(executor)
    centers, areas = executor.patch_faces(case, "inlet")
    mean = Q_TARGET / (math.pi * R_M ** 2)
    speeds = [2.0 * mean * (1.0 - (c[1] ** 2 + c[2] ** 2) / R_M ** 2)
              for c in centers]
    sector_q = Q_TARGET / (360.0 / sector_degrees)
    scale = sector_q / sum(-a[0] * u for a, u in zip(areas, speeds))
    values = "\n".join(f"({u * scale:.16g} 0 0)" for u in speeds)
    u_text = (case / "0/U").read_text(encoding="ascii")
    u_text = u_text.replace("inlet { type pressureInletOutletVelocity; value uniform (0 0 0); }",
        f"inlet {{ type fixedValue; value nonuniform List<vector> {len(speeds)} ( {values} ); }}")
    u_text = u_text.replace("internalField uniform (0 0 0);",
                           f"internalField uniform ({mean:.16g} 0 0);")
    (case / "0/U").write_text(u_text, encoding="ascii")
    manifest = json.loads((case / "case_manifest.json").read_text())
    manifest["boundary"].update({"target_full_flow_m3_s": Q_TARGET,
        "imposed_sector_flow_m3_s": sector_q, "profile_normalization": scale,
        "profile": "area-normalized developed parabolic samples"})
    (case / "case_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def run(work_dir: Path, end_time=3000, nx=320, nr=32, length=L_M,
        mode="pressure", side_boundary="wedge", sector_degrees=5.0):
    if work_dir.exists() and any(work_dir.iterdir()):
        raise RuntimeError("work directory is not empty: " + str(work_dir))
    work_dir.mkdir(parents=True)
    case = work_dir / "case"
    write_case(case, end_time, nx, nr, length, mode, side_boundary, sector_degrees)
    solver_dir = work_dir / "_solver"
    solver_dir.mkdir()
    solver = solver_dir / "run_openfoam_case.py"
    solver.write_bytes(SOLVER.read_bytes())
    reference_dir = work_dir / "solver_reference"
    reference_dir.mkdir()
    (reference_dir / "run_reference.py").write_bytes(
        (LIB.parent / "07_cfd_pipeline" / "solver_reference" / "run_reference.py").read_bytes())
    cmd = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "env",
           "WM_PROJECT_DIR=/usr/share/openfoam", "FOAM_ETC=/usr/share/openfoam/etc",
           "WM_PROJECT_VERSION=v1912", "python3", wsl_path(solver), "--case", wsl_path(case),
           "--steps", "blockMesh,checkMesh"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")
    if proc.returncode == 0:
        if mode == "developed-flow":
            set_developed_profile(case, sector_degrees)
        cmd[-1] = "simpleFoam,foamToVTK"
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace")
    mesh_path = case / "log.checkMesh"
    mesh = mesh_path.read_text(errors="replace") if mesh_path.is_file() else ""
    log_path = case / "log.simpleFoam"
    log = log_path.read_text(errors="replace") if log_path.is_file() else ""
    if proc.returncode:
        report = {
            "schema": "nasal_cfd_wedge_tube_validation/v1",
            "status": "fail", "patient_data": False,
            "execution_status": "failed_before_solver" if not log else "solver_failed",
            "case": str(case), "pressure_drop_pa": analytic_pressure_drop(length),
            "target_flow_m3_s": Q_TARGET, "mesh_quality_passed": "Mesh OK." in mesh and "Failed " not in mesh,
            "residual_quality_passed": quality(log),
            "mesh_log": str(mesh_path), "solver_log": str(log_path),
            "solver_output_tail": proc.stdout[-5000:],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (work_dir / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return report
    signed_in = last(case, "flow_inlet")
    signed_out = last(case, "flow_outlet")
    q_sector = -signed_in
    multiplier = 360.0 / sector_degrees
    q_full = q_sector * multiplier
    imbalance = abs(q_full - signed_out * multiplier) / q_full
    from extract_cfd_metrics import extract
    metrics = extract(case)["metrics"]
    dp_pa = metrics["delta_p_pa"]["value"]
    dp_analytic = analytic_pressure_drop(length)
    peak = metrics["max_velocity_mps"]["value"]
    peak_analytic = 2.0 * Q_TARGET / (math.pi * R_M ** 2)
    checks = {"mesh_quality_passed": "Mesh OK." in mesh and "Failed " not in mesh,
        "residual_quality_passed": quality(log),
        # v1912 simpleFoam terminates with `End`; it does not emit a
        # "SIMPLE solution converged" banner.  Pair normal termination with
        # the residual/continuity checks above so a truncated log cannot pass.
        "simple_converged": bool(re.search(r"(?:^|\n)End\s*$", log)),
        "mass_imbalance_below_1e-6": imbalance < 1e-6,
        "no_reverse_flow": signed_in < 0 < signed_out,
        "flow_error_below_1pct": abs(q_full-Q_TARGET)/Q_TARGET < .01,
        "pressure_error_below_2pct": abs(dp_pa-dp_analytic)/dp_analytic < .02,
        "peak_error_below_5pct": abs(peak-peak_analytic)/peak_analytic < .05}
    report = {
        "schema": "nasal_cfd_wedge_tube_validation/v1",
        "status": "pass" if all(checks.values()) else "fail",
        "patient_data": False, "execution_status": "completed", "case": str(case),
        "analytic_pressure_drop_pa": dp_analytic, "measured_pressure_drop_pa": dp_pa,
        "relative_pressure_error": abs(dp_pa-dp_analytic)/dp_analytic,
        "analytic_peak_velocity_mps": peak_analytic, "measured_peak_velocity_mps": peak,
        "relative_peak_error": abs(peak-peak_analytic)/peak_analytic, "checks": checks,
        "target_flow_m3_s": Q_TARGET, "measured_flow_m3_s": q_full,
        "relative_flow_error": abs(q_full-Q_TARGET)/Q_TARGET,
        "mass_imbalance_frac": imbalance, "mesh_quality_passed": "Mesh OK." in mesh and "Failed " not in mesh,
        "residual_quality_passed": quality(log), "signed_sector_flux_m3_s": {"inlet": signed_in, "outlet": signed_out},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (work_dir / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", default=r"C:\ts_work\wedge_tube_validation_20261004")
    parser.add_argument("--mode", choices=("pressure", "developed-flow"), default="pressure")
    parser.add_argument("--side-boundary", choices=("wedge", "cyclicAMI"), default="wedge")
    parser.add_argument("--sector-degrees", type=float, default=5.0)
    parser.add_argument("--length-m", type=float, default=L_M)
    parser.add_argument("--nx", type=int, default=320)
    parser.add_argument("--nr", type=int, default=32)
    parser.add_argument("--end-time", type=int, default=3000)
    args = parser.parse_args(argv)
    report = run(Path(args.work_dir), args.end_time, args.nx, args.nr, args.length_m,
                 args.mode, args.side_boundary, args.sector_degrees)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
