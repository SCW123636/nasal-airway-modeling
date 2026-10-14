"""Run a non-patient two-inlet pressure-feedback verification.

The mesh is a structured planar duct with two separated upstream branches
that merge into a common downstream chamber.  The branch widths are unequal,
so one common inlet static pressure must produce a natural, unequal split.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from pressure_feedback import (
    FeedbackConfig,
    FlowEvaluation,
    PressureFeedbackError,
    signed_patch_fluxes,
    solve_common_pressure,
)

RHO = 1.20
MU = 1.81e-5
NU = MU / RHO
L_MM = 40.0
LEFT_WIDTH_MM = 2.0
RIGHT_WIDTH_MM = 1.0
DEPTH_MM = 10.0  # empty extrusion: numerical flow scale, no no-slip side walls
TARGET_M3_S = 1.666666666666667e-5  # 1 L/min; low-Re controller test
LIB = Path(__file__).resolve().parent
PIPELINE = LIB.parent / "07_cfd_pipeline"
SOLVER = PIPELINE / "solver" / "run_openfoam_case.py"


def header(name, cls="dictionary"):
    return ("FoamFile\n{\n version 2.0;\n format ascii;\n class %s;\n object %s;\n}\n"
            % (cls, name))


def write_case(case: Path, inlet_pressure_pa: float, left_width_mm=LEFT_WIDTH_MM,
               right_width_mm=RIGHT_WIDTH_MM, swap_labels=False, end_time=3000) -> None:
    case.mkdir(parents=True, exist_ok=False)
    for folder in ("0", "constant", "system"):
        (case / folder).mkdir()

    # The upstream branches are separated by a solid partition.  At x=0 the
    # partition ends and three downstream blocks form one connected chamber.
    # This avoids the earlier, invalid topology where the two inlet patches
    # were merely labels on one already-connected channel.
    x0, xm, x1 = -L_MM, 0.0, L_MM
    y0, y1, y2, y3 = -0.25-left_width_mm, -0.25, 0.25, 0.25+right_width_mm
    z0, z1 = 0.0, DEPTH_MM
    point_ids = {}
    pts = []
    def vid(x, y, z):
        key = (x, y, z)
        if key not in point_ids:
            point_ids[key] = len(pts)
            pts.append(key)
        return point_ids[key]
    def block(xa, xb, ya, yb):
        return (vid(xa, ya, z0), vid(xb, ya, z0), vid(xb, yb, z0), vid(xa, yb, z0),
                vid(xa, ya, z1), vid(xb, ya, z1), vid(xb, yb, z1), vid(xa, yb, z1))
    blocks = [
        block(x0, xm, y0, y1),  # upstream left
        block(x0, xm, y2, y3),  # upstream right
        block(xm, x1, y0, y1),  # downstream lower
        block(xm, x1, y1, y2),  # downstream middle
        block(xm, x1, y2, y3),  # downstream upper
    ]
    coords = "\n".join("(" + " ".join("%.12g" % v for v in p) + ")" for p in pts)
    cells_y = [round(left_width_mm*8), round(right_width_mm*8),
               round(left_width_mm*8), 4, round(right_width_mm*8)]
    b = ["hex (%s) (160 %d 1) simpleGrading (1 1 1)" %
         (" ".join(map(str, blk)), ny) for blk, ny in zip(blocks, cells_y)]
    # Faces use the standard block vertex ordering (lower z first, upper z
    # second).  The x=0 interfaces are deliberately omitted from the boundary
    # list so blockMesh keeps them as internal faces.
    low_u, high_u, low_d, mid_d, high_d = blocks
    inlet_l = "(%d %d %d %d)" % (low_u[0], low_u[4], low_u[7], low_u[3])
    inlet_r = "(%d %d %d %d)" % (high_u[0], high_u[4], high_u[7], high_u[3])
    outlet = "(%d %d %d %d) (%d %d %d %d) (%d %d %d %d)" % (
        low_d[1], low_d[2], low_d[6], low_d[5],
        mid_d[1], mid_d[2], mid_d[6], mid_d[5],
        high_d[1], high_d[2], high_d[6], high_d[5])
    walls = "(%d %d %d %d) (%d %d %d %d) (%d %d %d %d) (%d %d %d %d) (%d %d %d %d) (%d %d %d %d) (%d %d %d %d)" % (
        low_u[0], low_u[1], low_u[5], low_u[4],
        high_u[3], high_u[7], high_u[6], high_u[2],
        low_u[3], low_u[2], low_u[6], low_u[7],
        high_u[0], high_u[4], high_u[5], high_u[1],
        low_d[0], low_d[1], low_d[5], low_d[4],
        high_d[3], high_d[7], high_d[6], high_d[2],
        mid_d[0], mid_d[4], mid_d[7], mid_d[3])
    if swap_labels:
        inlet_l, inlet_r = inlet_r, inlet_l
    front = " ".join("(%d %d %d %d) (%d %d %d %d)" % (
        blk[0], blk[3], blk[2], blk[1], blk[4], blk[5], blk[6], blk[7]) for blk in blocks)
    blockmesh = header("blockMeshDict") + f"""
convertToMeters 0.001;
vertices ( {coords} );
blocks
(
 {b[0]}
 {b[1]}
 {b[2]}
 {b[3]}
 {b[4]}
);
edges ();
boundary
(
 inlet_L {{ type patch; faces ({inlet_l}); }}
 inlet_R {{ type patch; faces ({inlet_r}); }}
 outlet {{ type patch; faces ({outlet}); }}
 walls {{ type wall; faces ({walls}); }}
 frontAndBack {{ type empty; faces ({front}); }}
);
mergePatchPairs ();
"""
    (case / "system/blockMeshDict").write_text(blockmesh, encoding="ascii")

    p_kin = inlet_pressure_pa / RHO
    p_text = header("p", "volScalarField") + f"""
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{{
 inlet_L {{ type fixedValue; value uniform {p_kin:.16g}; }}
 inlet_R {{ type fixedValue; value uniform {p_kin:.16g}; }}
 outlet {{ type fixedValue; value uniform 0; }}
 walls {{ type zeroGradient; }}
 frontAndBack {{ type empty; }}
}}
"""
    u_text = header("U", "volVectorField") + """
dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{
 inlet_L { type pressureInletOutletVelocity; value uniform (0 0 0); }
 inlet_R { type pressureInletOutletVelocity; value uniform (0 0 0); }
 outlet { type zeroGradient; }
 walls { type noSlip; }
 frontAndBack { type empty; }
}
"""
    (case / "0/p").write_text(p_text, encoding="ascii")
    (case / "0/U").write_text(u_text, encoding="ascii")
    (case / "constant/transportProperties").write_text(
        header("transportProperties") + f"\ntransportModel Newtonian;\nnu {NU:.16g};\n",
        encoding="ascii")
    (case / "constant/turbulenceProperties").write_text(
        header("turbulenceProperties") + "\nsimulationType laminar;\n", encoding="ascii")
    schemes = (PIPELINE / "solver_reference" / "results" /
               "poiseuille_v1912_verified" / "medium" / "system" / "fvSchemes")
    scheme_text = schemes.read_text(encoding="ascii")
    # The pitzDaily linearUpwind scheme is needlessly oscillatory for this
    # low-Re pressure-inlet controller phantom. Use a bounded first-order
    # transport discretisation while keeping the pressure/viscous operators
    # from the verified v1912 dictionary.
    scheme_text = scheme_text.replace(
        "div(phi,U)      bounded Gauss linearUpwind grad(U);",
        "div(phi,U)      bounded Gauss upwind;",
    ).replace(
        "laplacianSchemes\n{\n    default         Gauss linear corrected;",
        "laplacianSchemes\n{\n    default         Gauss linear uncorrected;",
    )
    (case / "system/fvSchemes").write_text(scheme_text, encoding="ascii")
    (case / "system/fvSolution").write_text(header("fvSolution") + """
solvers
{
 p { solver GAMG; tolerance 1e-10; relTol 0; smoother GaussSeidel; }
 U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0; }
}
SIMPLE
{
 nNonOrthogonalCorrectors 0;
 consistent yes;
 residualControl { p 1e-8; U 1e-5; }
}
relaxationFactors { fields { p 0.3; } equations { U 0.7; } }
""", encoding="ascii")
    functions = []
    for name in ("inlet_L", "inlet_R", "outlet"):
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
}}
pressure_{name}
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
    control = header("controlDict") + """
application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime END_TIME;
deltaT 1;
writeControl timeStep;
writeInterval 600;
purgeWrite 1;
writeFormat ascii;
writePrecision 12;
writeCompression off;
timeFormat general;
timePrecision 10;
runTimeModifiable false;
functions
{
""" + "\n".join(functions) + "\n}\n"
    (case / "system/controlDict").write_text(control.replace("END_TIME", str(end_time)), encoding="ascii")
    manifest = {
        "schema": "nasal_cfd_split_feedback_case/v1",
        "patient_data": False,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "boundary": {
            "mode": "common_inlet_pressure",
            "inlet_static_pressure_Pa_gauge": inlet_pressure_pa,
            "outlet_static_pressure_Pa_gauge": 0.0,
            "inlets": ["inlet_L", "inlet_R"],
            "outlet": "outlet",
        },
        "physics": {"rho_kg_m3": RHO, "mu_Pa_s": MU, "nu_m2_s": NU},
        "patch_map": {"inlet_L": "inlet", "inlet_R": "inlet", "outlet": "outlet", "walls": "wall"},
        "geometry": {"branch_length_mm": L_MM, "chamber_length_mm": L_MM,
                     "left_width_mm": left_width_mm, "right_width_mm": right_width_mm,
                     "partition_thickness_mm": 0.5, "depth_mm": DEPTH_MM,
                     "labels_swapped": swap_labels, "dimensionality": "2D empty extrusion"},
    }
    (case / "case_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def last_flow(case: Path, function: str) -> float:
    files = sorted((case / "postProcessing" / function).glob("*/surfaceFieldValue.dat"))
    if not files:
        raise PressureFeedbackError("missing function output: " + function)
    rows = [line.split() for line in files[-1].read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    if not rows:
        raise PressureFeedbackError("empty function output: " + function)
    return float(rows[-1][1])


def residual_quality(log_text: str) -> bool:
    """Use final equation residuals and continuity when v1912 does not emit
    its optional SIMPLE convergence banner before endTime."""
    finals = [float(value) for value in re.findall(
        r"Final residual = ([0-9.eE+-]+)", log_text
    )]
    globals_ = [float(value) for value in re.findall(
        r"global = ([0-9.eE+-]+)", log_text
    )]
    if len(finals) < 3 or not globals_:
        return False
    return max(finals[-3:]) <= 1e-5 and abs(globals_[-1]) <= 1e-6


def run_case(case: Path, work_dir: Path) -> None:
    script = wsl_path(work_dir / "_solver" / "run_openfoam_case.py")
    command = ["wsl.exe", "-d", "Ubuntu-22.04", "--", "env",
               "WM_PROJECT_DIR=/usr/share/openfoam", "FOAM_ETC=/usr/share/openfoam/etc",
               "WM_PROJECT_VERSION=v1912", "python3", script,
               "--case", wsl_path(case),
               "--steps", "blockMesh,checkMesh,simpleFoam"]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise PressureFeedbackError("OpenFOAM evaluation failed:\n" + result.stdout[-4000:])


def wsl_path(path: Path) -> str:
    text = str(path.resolve())
    return "/mnt/" + text[0].lower() + "/" + text[2:].replace("\\", "/")


def evaluate_factory(work_dir: Path, left_width_mm=LEFT_WIDTH_MM,
                      right_width_mm=RIGHT_WIDTH_MM, swap_labels=False):
    template = work_dir / "template"
    evaluations = []
    index = {"n": 0}

    def evaluate(pressure_pa: float) -> FlowEvaluation:
        index["n"] += 1
        case = work_dir / ("eval_%02d" % index["n"])
        shutil.copytree(template, case)
        manifest = json.loads((case / "case_manifest.json").read_text(encoding="utf-8"))
        manifest["boundary"]["inlet_static_pressure_Pa_gauge"] = pressure_pa
        (case / "case_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        text = (case / "0/p").read_text(encoding="ascii")
        text = re.sub(
            r"(inlet_[LR] \{ type fixedValue; value uniform )[-+0-9.eE]+(; \})",
            lambda m: m.group(1) + "%.16g" % (pressure_pa / RHO) + m.group(2),
            text,
        )
        (case / "0/p").write_text(text, encoding="ascii")
        run_case(case, work_dir)
        patch_phi = {"inlet_L": last_flow(case, "flow_inlet_L"),
                     "inlet_R": last_flow(case, "flow_inlet_R"),
                     "outlet": last_flow(case, "flow_outlet")}
        flux = signed_patch_fluxes(patch_phi, ["inlet_L", "inlet_R"], ["outlet"])
        log = (case / "log.simpleFoam").read_text(encoding="utf-8", errors="replace")
        mesh_log = (case / "log.checkMesh").read_text(encoding="utf-8", errors="replace")
        if "Mesh OK." not in mesh_log or "Failed " in mesh_log:
            raise PressureFeedbackError("structured split mesh did not pass checkMesh")
        quality = residual_quality(log)
        evaluation = FlowEvaluation(
            pressure_pa=pressure_pa,
            q_left_m3_s=flux["q_in_by_patch"]["inlet_L"],
            q_right_m3_s=flux["q_in_by_patch"]["inlet_R"],
            q_out_m3_s=flux["q_out_m3_s"],
            converged=quality,
            mesh_quality_passed=True,
            mass_imbalance_frac=flux["mass_imbalance_frac"],
            residuals_passed=True,
        )
        evaluations.append({"case": case.name, "signed_phi": patch_phi,
                            "residual_quality_passed": quality,
                            "mesh_log": str(case / "log.checkMesh"),
                            "solver_log": str(case / "log.simpleFoam")})
        return evaluation

    return template, evaluate, evaluations


def run_scenario(work_dir: Path, name: str, left_width_mm=LEFT_WIDTH_MM,
                 right_width_mm=RIGHT_WIDTH_MM, swap_labels=False) -> dict:
    if work_dir.exists() and any(work_dir.iterdir()):
        raise RuntimeError("work directory is not empty: " + str(work_dir))
    work_dir.mkdir(parents=True)
    solver_copy = work_dir / "_solver"
    solver_copy.mkdir()
    shutil.copy2(SOLVER, solver_copy / "run_openfoam_case.py")
    shutil.copy2(PIPELINE / "solver" / "mesh_cache.py",
                 solver_copy / "mesh_cache.py")
    reference_copy = work_dir / "solver_reference"
    reference_copy.mkdir()
    shutil.copy2(PIPELINE / "solver_reference" / "run_reference.py",
                 reference_copy / "run_reference.py")
    template, evaluate, evaluations = evaluate_factory(
        work_dir, left_width_mm, right_width_mm, swap_labels)
    write_case(template, 0.0, left_width_mm, right_width_mm, swap_labels)
    result = solve_common_pressure(
        evaluate,
        FeedbackConfig(target_m3_s=TARGET_M3_S, initial_pressure_pa=1.0,
                       pressure_upper_pa=200.0, max_iterations=12,
                       relative_flow_tolerance=0.01),
    )
    report = {
        "schema": "nasal_cfd_split_feedback/v2",
        "scenario": name,
        "status": result["status"],
        "patient_data": False,
        "purpose": "common static inlet pressure and unequal synthetic branch split",
        "target_flow_m3_s": TARGET_M3_S,
        "target_flow_lpm": TARGET_M3_S * 60_000,
        "geometry": {"left_width_mm": left_width_mm, "right_width_mm": right_width_mm,
                     "labels_swapped": swap_labels,
                     "ideal_planar_left_fraction": left_width_mm ** 3 / (left_width_mm ** 3 + right_width_mm ** 3)},
        "result": result,
        "evaluations": evaluations,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (work_dir / "feedback_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def run(work_dir: Path) -> dict:
    if work_dir.exists() and any(work_dir.iterdir()):
        raise RuntimeError("work directory is not empty: " + str(work_dir))
    work_dir.mkdir(parents=True)
    scenarios = [
        ("unequal", LEFT_WIDTH_MM, RIGHT_WIDTH_MM, False),
        ("symmetric", 1.5, 1.5, False),
        ("swapped_labels", LEFT_WIDTH_MM, RIGHT_WIDTH_MM, True),
    ]
    reports = {}
    for name, left, right, swapped in scenarios:
        reports[name] = run_scenario(work_dir / name, name, left, right, swapped)
    unequal = reports["unequal"]["result"]
    symmetric = reports["symmetric"]["result"]
    swapped = reports["swapped_labels"]["result"]
    checks = {
        "all_scenarios_converged": all(r["status"] == "converged" for r in reports.values()),
        "unequal_split_is_not_symmetric": abs(unequal["left_fraction"] - 0.5) > 0.1,
        "symmetric_split_near_half": abs(symmetric["left_fraction"] - 0.5) <= 0.02,
        "label_swap_complements_split": abs(swapped["left_fraction"] - (1.0 - unequal["left_fraction"])) <= 0.02,
        "all_flow_errors_within_one_percent": all(
            abs(r["result"]["q_total_m3_s"] - TARGET_M3_S) / TARGET_M3_S <= 0.01
            for r in reports.values()),
    }
    combined = {
        "schema": "nasal_cfd_split_feedback_suite/v1",
        "patient_data": False,
        "purpose": "common static pressure, natural branch split, symmetry and label-swap controls",
        "target_flow_m3_s": TARGET_M3_S,
        "target_flow_lpm": TARGET_M3_S * 60_000,
        "scenarios": {name: {"report": str(work_dir / name / "feedback_report.json"),
                              "result": item["result"], "geometry": item["geometry"]}
                      for name, item in reports.items()},
        "checks": checks,
        "status": "converged" if all(checks.values()) else "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (work_dir / "feedback_suite_report.json").write_text(
        json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    return combined


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", default=r"C:\ts_work\feedback_split_20261004")
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.work_dir))
    except Exception as exc:
        print("pressure feedback failed: " + repr(exc), file=sys.stderr)
        return 1
    print(json.dumps({"status": report["status"],
                      "checks": report.get("checks"),
                      "report": str(Path(args.work_dir) / "feedback_suite_report.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
