"""Build a complete OpenFOAM v1912 case from a named-solid surface (STL/VTP).

Windows-side script (run with the nasal-cfd Python). Reads a surface whose
solids carry names, requires every solid to be mapped by --patch-map, splits
the surface into one STL per patch under constant/triSurface (METRES; snappy
does no unit conversion), writes all case dictionaries, and records a
deterministic case_manifest.json (byte-identical across runs except the
timestamp).

Unit contract: blockMeshDict vertices stay in mm with `convertToMeters 0.001;`
(acceptance requires the visible marker); triSurface STLs are written in m.

Batch-1 scope: the common-inlet-pressure outer feedback loop is NOT
implemented (recorded as status not_implemented). Inlets get
flowRateInletVelocity; with multiple inlets the total flow is split equally,
which is an imposed baseline and never a patient flow split. No patient data
is accessed and no solver is run by this script.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "07_cfd_pipeline" / "solver_reference"))
from run_reference import header, write  # reuse the verified dictionary helpers

SCRIPT_VERSION = "1.0.0"
RHO, MU = 1.20, 1.81e-5
NU = MU / RHO
CONVERT_TO_METERS = 0.001
DEFAULT_FLOW_M3_S = 2.5e-4
FVSCHEMES_SOURCE = ("/usr/share/doc/openfoam-examples/examples/incompressible/"
                    "simpleFoam/pitzDaily/system/fvSchemes")
FVSCHEMES_SHA256 = "7cee2e02eda29bb04f5052080e27187f1745c16c52ad755ab21d56c083965135"
# Byte-exact copy of the pitzDaily v1912 fvSchemes (verified against the
# reference manifest SHA-256 above). Embedded because this Windows-side script
# cannot read the WSL filesystem, and hand-writing v1912 scheme names is an
# error source. Do not reformat.
FVSCHEMES_TEXT = '/*--------------------------------*- C++ -*----------------------------------*\\\n| =========                 |                                                 |\n| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |\n|  \\\\    /   O peration     | Version:  v1912                                 |\n|   \\\\  /    A nd           | Website:  www.openfoam.com                      |\n|    \\\\/     M anipulation  |                                                 |\n\\*---------------------------------------------------------------------------*/\nFoamFile\n{\n    version     2.0;\n    format      ascii;\n    class       dictionary;\n    location    "system";\n    object      fvSchemes;\n}\n// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\nddtSchemes\n{\n    default         steadyState;\n}\n\ngradSchemes\n{\n    default         Gauss linear;\n}\n\ndivSchemes\n{\n    default         none;\n    div(phi,U)      bounded Gauss linearUpwind grad(U);\n    div(phi,k)      bounded Gauss limitedLinear 1;\n    div(phi,epsilon) bounded Gauss limitedLinear 1;\n    div(phi,omega)  bounded Gauss limitedLinear 1;\n    div(phi,v2)     bounded Gauss limitedLinear 1;\n    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n    div(nonlinearStress) Gauss linear;\n}\n\nlaplacianSchemes\n{\n    default         Gauss linear corrected;\n}\n\ninterpolationSchemes\n{\n    default         linear;\n}\n\nsnGradSchemes\n{\n    default         corrected;\n}\n\nwallDist\n{\n    method meshWave;\n}\n\n\n// ************************************************************************* //\n'

PATCH_ROLES = ("inlet", "outlet", "wall")
PATCH_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def fail(message):
    print("surface_to_case error: " + message, file=sys.stderr)
    raise SystemExit(2)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def fmt(value):
    return "%.16g" % float(value)


def parse_stl_ascii(path):
    """Parse an ASCII STL into {solid_name: [(v1, v2, v3), ...]} (mm)."""
    raw = path.read_bytes()
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        fail(f"{path} is a binary STL; binary STL carries no named solids. "
             "Provide an ASCII STL with named solids or a VTP with a named region array.")
    if "facet" not in text:
        fail(f"{path}: no facet records found; not an ASCII STL with solids.")
    solids = {}
    for match in re.finditer(r"solid[ \t]+([^\r\n]+?)[ \t]*\r?\n(.*?)endsolid[ \t]+([^\r\n]+?)[ \t]*\r?\n",
                             text, re.DOTALL):
        name, body, closing = match.group(1), match.group(2), match.group(3)
        if name != closing:
            fail(f"solid name mismatch: '{name}' vs endsolid '{closing}'")
        if name in solids:
            fail(f"duplicate solid name '{name}'")
        vertices = [(float(a), float(b), float(c)) for a, b, c in
                    re.findall(r"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", body)]
        if not vertices or len(vertices) % 3:
            fail(f"solid '{name}': vertex count {len(vertices)} is not a positive multiple of 3")
        solids[name] = [tuple(vertices[i:i + 3]) for i in range(0, len(vertices), 3)]
    if not solids:
        fail(f"{path}: no named solid blocks found")
    return solids


def parse_vtp_regions(path):
    """Read a VTP with a string cell array ('solid'/'region'/'patch') into named triangles."""
    try:
        import vtk
    except ImportError:
        fail("VTP input requires VTK (available in the nasal-cfd Python env)")
    reader = vtk.vtkXMLPolyDataReader()
    reader.SetFileName(str(path))
    reader.Update()
    data = reader.GetOutput()
    cell_data = data.GetCellData()
    names = None
    for index in range(cell_data.GetNumberOfArrays()):
        array = cell_data.GetAbstractArray(index)
        if array.GetName() and array.GetName().lower() in ("solid", "region", "patch"):
            names = array
            break
    if names is None:
        fail(f"{path}: VTP needs a string cell array named solid/region/patch to identify regions")
    points = data.GetPoints()
    polys = data.GetPolys()
    polys.InitTraversal()
    ids = vtk.vtkIdList()
    solids = {}
    for cell in range(polys.GetNumberOfCells()):
        if not polys.GetNextCell(ids):
            break
        if ids.GetNumberOfIds() != 3:
            fail(f"{path}: cell {cell} is not a triangle; triangulate the VTP first")
        name = names.GetValue(cell)
        triangle = tuple(tuple(points.GetPoint(ids.GetId(k))) for k in range(3))
        solids.setdefault(name, []).append(triangle)
    if not solids:
        fail(f"{path}: no cells read from VTP")
    return solids


def parse_surface(path):
    if path.suffix.lower() == ".stl":
        return parse_stl_ascii(path)
    if path.suffix.lower() == ".vtp":
        return parse_vtp_regions(path)
    fail(f"unsupported surface extension {path.suffix}; use .stl or .vtp")


def tri_normal_area(triangle):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = triangle
    ux, uy, uz = bx - ax, by - ay, bz - az
    vx, vy, vz = cx - ax, cy - ay, cz - az
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm == 0.0:
        fail("degenerate zero-area triangle in surface")
    return (nx / norm, ny / norm, nz / norm), 0.5 * norm


def write_patch_stl(path, name, triangles_mm):
    """Write one ASCII STL in METRES (snappyHexMesh performs no unit scaling)."""
    lines = ["solid " + name]
    for triangle in triangles_mm:
        normal, _ = tri_normal_area(triangle)
        lines.append(" facet normal %s %s %s" % tuple(fmt(v) for v in normal))
        lines.append("  outer loop")
        for vertex in triangle:
            lines.append("   vertex %s %s %s" % tuple(fmt(CONVERT_TO_METERS * v) for v in vertex))
        lines.append("  endloop")
        lines.append(" endfacet")
    lines.append("endsolid " + name)
    write(path, "\n".join(lines) + "\n")


def bounding_box(solids):
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for triangles in solids.values():
        for triangle in triangles:
            for vertex in triangle:
                for axis in range(3):
                    lo[axis] = min(lo[axis], vertex[axis])
                    hi[axis] = max(hi[axis], vertex[axis])
    return lo, hi


def write_blockmesh_dict(case, lo, hi, cell_size):
    margin = 2.0 * cell_size
    box_lo = [v - margin for v in lo]
    box_hi = [v + margin for v in hi]
    cells = [max(1, int(round((box_hi[a] - box_lo[a]) / cell_size))) for a in range(3)]
    x0, y0, z0 = box_lo
    x1, y1, z1 = box_hi
    vertices = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    coords = "\n".join("(" + " ".join(fmt(v) for v in p) + ")" for p in vertices)
    write(case / "system/blockMeshDict", header("blockMeshDict") + f"""
convertToMeters {fmt(CONVERT_TO_METERS)};
vertices ( {coords} );
blocks ( hex (0 1 2 3 4 5 6 7) ({cells[0]} {cells[1]} {cells[2]}) simpleGrading (1 1 1) );
edges ();
boundary
(
 box {{ type patch; faces ((0 4 7 3) (1 2 6 5) (0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)); }}
);
mergePatchPairs ();
""")
    return {"min_mm": box_lo, "max_mm": box_hi}, cells


def write_snappy_dict(case, patches, refine, location_m):
    geometry = "\n".join(f' {p} {{ type triSurfaceMesh; file "{p}.stl"; }}' for p in patches)
    refinement = "\n".join(f"  {p} {{ level ({refine[0]} {refine[1]}); }}" for p in patches)
    write(case / "system/snappyHexMeshDict", header("snappyHexMeshDict") + f"""
castellatedMesh true;
snap true;
addLayers false;
geometry
{{
{geometry}
}};
castellatedMeshControls
{{
 maxLocalCells 1000000;
 maxGlobalCells 5000000;
 minRefinementCells 10;
 maxLoadUnbalance 0.10;
 nCellsBetweenLevels 2;
 features ();
 refinementSurfaces
 {{
{refinement}
 }}
 resolveFeatureAngle 30;
 refinementRegions {{}}
 locationInMesh ({' '.join(fmt(v) for v in location_m)});
 allowFreeStandingZoneFaces true;
}}
snapControls
{{
 nSmoothPatch 3;
 tolerance 2.0;
 nSolveIter 30;
 nRelaxIter 5;
 nFeatureSnapIter 10;
 implicitFeatureSnap false;
 explicitFeatureSnap true;
 multiRegionFeatureSnap false;
}}
addLayersControls
{{
 relativeSizes true;
 layers {{}}
 expansionRatio 1.0;
 finalLayerThickness 0.3;
 minThickness 0.1;
 nGrow 0;
 featureAngle 30;
 nRelaxIter 3;
 nSmoothSurfaceNormals 1;
 nSmoothNormals 3;
 nSmoothThickness 10;
 maxFaceThicknessRatio 0.5;
 maxThicknessToMedialRatio 0.3;
 minMedialAxisAngle 90;
 nBufferCellsNoExtrude 0;
 nLayerIter 50;
}}
meshQualityControls
{{
 maxNonOrtho 65;
 maxBoundarySkewness 20;
 maxInternalSkewness 4;
 maxConcave 80;
 minVol 1e-13;
 minTetQuality 1e-15;
 minArea -1;
 minTwist 0.02;
 minDeterminant 0.001;
 minFaceWeight 0.05;
 minVolRatio 0.01;
 minTriangleTwist -1;
 nSmoothScale 4;
 errorReduction 0.75;
}}
mergeTolerance 1e-6;
""")


def write_fields(case, patches_by_role, solver, per_inlet_flow, inlet_areas_m2,
                 boundary_mode="flow_driven_total_flow", inlet_pressure_pa=0.0):
    """Write fields for either fixed-flow or common-static-pressure inlet mode.

    ``common_inlet_pressure`` deliberately leaves the total flow to the outer
    controller.  The inlet pressure is entered in Pa at the project boundary,
    then converted to OpenFOAM's kinematic pressure field using ``rho``.
    """
    boundary_p, boundary_u = [], []
    for patch in patches_by_role["inlet"]:
        if boundary_mode == "common_inlet_pressure":
            p_kin = inlet_pressure_pa / RHO
            boundary_p.append(f" {patch} {{ type fixedValue; value uniform {fmt(p_kin)}; }}")
            boundary_u.append(f" {patch} {{ type pressureInletOutletVelocity; value uniform (0 0 0); }}")
        else:
            boundary_p.append(f" {patch} {{ type zeroGradient; }}")
            boundary_u.append(f" {patch} {{ type flowRateInletVelocity; volumetricFlowRate constant {fmt(per_inlet_flow[patch])}; }}")
    for patch in patches_by_role["outlet"]:
        boundary_p.append(f" {patch} {{ type fixedValue; value uniform 0; }}")
        boundary_u.append(f" {patch} {{ type zeroGradient; }}")
    for patch in patches_by_role["wall"]:
        boundary_p.append(f" {patch} {{ type zeroGradient; }}")
        boundary_u.append(f" {patch} {{ type noSlip; }}")
    boundary_p.append(" box { type zeroGradient; }")
    boundary_u.append(" box { type zeroGradient; }")
    write(case / "0/p", header("p", "volScalarField") + """
dimensions [0 2 -2 0 0 0 0];
internalField uniform 0;
boundaryField
{
""" + "\n".join(boundary_p) + "\n}\n")
    write(case / "0/U", header("U", "volVectorField") + """
dimensions [0 1 -1 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{
""" + "\n".join(boundary_u) + "\n}\n")
    if solver == "kOmegaSST":
        intensity, length_fraction = 0.01, 0.1
        write(case / "0/k", header("k", "volScalarField") + """
dimensions [0 2 -2 0 0 0 0];
internalField uniform 1e-8;
boundaryField
{
""" + "\n".join(
            [f" {p} {{ type fixedValue; value uniform {fmt(1.5 * (intensity * per_inlet_flow[p] / inlet_areas_m2[p]) ** 2)}; }}"
             for p in patches_by_role["inlet"]]
            + [f" {p} {{ type zeroGradient; }}" for p in patches_by_role["outlet"]]
            + [f" {p} {{ type kqRWallFunction; value uniform 0; }}" for p in patches_by_role["wall"]]
            + [" box { type zeroGradient; }"]) + "\n}\n")
        omega_entries = []
        for p in patches_by_role["inlet"]:
            dh = 2.0 * math.sqrt(inlet_areas_m2[p] / math.pi)  # equivalent diameter convention
            k_in = 1.5 * (intensity * per_inlet_flow[p] / inlet_areas_m2[p]) ** 2
            omega_in = math.sqrt(k_in) / (0.09 ** 0.25 * length_fraction * dh)
            omega_entries.append(f" {p} {{ type fixedValue; value uniform {fmt(omega_in)}; }}")
        write(case / "0/omega", header("omega", "volScalarField") + """
dimensions [0 0 -1 0 0 0 0];
internalField uniform 1;
boundaryField
{
""" + "\n".join(omega_entries
                + [f" {p} {{ type zeroGradient; }}" for p in patches_by_role["outlet"]]
                + [f" {p} {{ type omegaWallFunction; value uniform 1; }}" for p in patches_by_role["wall"]]
                + [" box { type zeroGradient; }"]) + "\n}\n")
        write(case / "0/nut", header("nut", "volScalarField") + """
dimensions [0 2 -1 0 0 0 0];
internalField uniform 0;
boundaryField
{
""" + "\n".join([f" {p} {{ type calculated; value uniform 0; }}"
                 for p in patches_by_role["inlet"] + patches_by_role["outlet"]]
                + [f" {p} {{ type nutkWallFunction; value uniform 0; }}" for p in patches_by_role["wall"]]
                + [" box { type calculated; value uniform 0; }"]) + "\n}\n")


def write_constant(case, solver):
    write(case / "constant/transportProperties", header("transportProperties")
          + f"\ntransportModel Newtonian;\nnu {fmt(NU)};\n")
    if solver == "laminar":
        turbulence = "\nsimulationType laminar;\n"
    else:
        turbulence = """
simulationType RAS;
RAS
{
 RASModel kOmegaSST;
 turbulence on;
 printCoeffs on;
}
"""
    write(case / "constant/turbulenceProperties", header("turbulenceProperties") + turbulence)


def write_system(case, patches_by_role, solver):
    write(case / "system/fvSchemes", FVSCHEMES_TEXT)
    solvers = """
solvers
{
 p { solver GAMG; tolerance 1e-12; relTol 0.01; smoother GaussSeidel; }
 U { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
"""
    if solver == "kOmegaSST":
        solvers += """ k { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
 omega { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-12; relTol 0.01; }
"""
    solvers += """}
SIMPLE
{
 nNonOrthogonalCorrectors 0;
 consistent yes;
 residualControl { p 1e-10; U 1e-8; }
}
relaxationFactors { equations { U 0.9; } }
"""
    if solver == "kOmegaSST":
        solvers = solvers.replace("relaxationFactors { equations { U 0.9; } }",
                                  "relaxationFactors { equations { U 0.9; k 0.7; omega 0.7; } }")
    write(case / "system/fvSolution", header("fvSolution") + solvers)
    functions = []
    for role in ("inlet", "outlet"):
        for patch in patches_by_role[role]:
            functions.append(f"""flow_{patch}
{{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name {patch};
 operation sum;
 fields (phi);
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}}""")
            functions.append(f"""pressure_{patch}
{{
 type surfaceFieldValue;
 libs ("libfieldFunctionObjects.so");
 regionType patch;
 name {patch};
 operation areaAverage;
 fields (p);
 writeFields false;
 log false;
 writeControl timeStep;
 writeInterval 1;
}}""")
    write(case / "system/controlDict", header("controlDict") + """
application simpleFoam;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime 4000;
deltaT 1;
writeControl timeStep;
writeInterval 1000;
purgeWrite 2;
writeFormat ascii;
writePrecision 12;
writeCompression off;
timeFormat general;
timePrecision 10;
runTimeModifiable false;
functions
{
""" + "\n".join(functions) + "\n}\n")


def wsl_path(path):
    text = str(Path(path).resolve())
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if not match:
        return text
    return "/mnt/" + match.group(1).lower() + "/" + match.group(2).replace("\\", "/")


def build_case(args):
    if sha256_bytes(FVSCHEMES_TEXT.encode("ascii")) != FVSCHEMES_SHA256:
        fail("embedded fvSchemes constant is corrupted (SHA-256 mismatch)")
    surface = Path(args.surface)
    if not surface.is_file():
        fail(f"surface not found: {surface}")
    patch_map = json.loads(Path(args.patch_map).read_text(encoding="utf-8"))
    if not isinstance(patch_map, dict) or not patch_map:
        fail("--patch-map must be a non-empty JSON object {solid_name: role}")
    for name, role in patch_map.items():
        if role not in PATCH_ROLES:
            fail(f"patch '{name}' has unsupported role '{role}' (use inlet/outlet/wall)")
        if not PATCH_NAME_RE.match(name):
            fail(f"solid name '{name}' is not a valid OpenFOAM patch name")
    solids = parse_surface(surface)
    unmapped = sorted(set(solids) - set(patch_map))
    if unmapped:
        fail("surface solids missing from --patch-map (refusing to drop them silently): "
             + ", ".join(unmapped))
    unused = sorted(set(patch_map) - set(solids))
    if unused:
        fail("--patch-map names not present in the surface: " + ", ".join(unused))
    out = Path(args.out)
    if out.exists():
        fail(f"output directory already exists (overwrite protection): {out}")
    location_mm = [float(v) for v in args.location_in_mesh.split()]
    if len(location_mm) != 3:
        fail("--location-in-mesh needs exactly three numbers (mm)")
    refine = [int(v) for v in args.refine_level.split()]
    if len(refine) != 2 or min(refine) < 0:
        fail("--refine-level needs two non-negative integers, e.g. \"1 1\"")
    cell_size = float(args.cell_size)
    if not math.isfinite(cell_size) or cell_size <= 0:
        fail("--cell-size must be positive (mm)")
    total_flow = float(args.flow_rate_m3s)
    if not math.isfinite(total_flow) or total_flow <= 0:
        fail("--flow-rate-m3s must be positive")

    patches_by_role = {role: sorted(n for n, r in patch_map.items() if r == role) for role in PATCH_ROLES}
    if not patches_by_role["inlet"] or not patches_by_role["outlet"]:
        fail("patch-map must assign at least one inlet and one outlet")
    patches = sorted(patch_map)
    inlets = patches_by_role["inlet"]
    per_inlet_flow = {p: total_flow / len(inlets) for p in inlets}
    areas_mm2 = {name: sum(tri_normal_area(t)[1] for t in solids[name]) for name in patches}
    inlet_areas_m2 = {p: areas_mm2[p] * 1e-6 for p in inlets}
    for p in inlets:
        if inlet_areas_m2[p] <= 0:
            fail(f"inlet '{p}' has zero area")

    (out / "0").mkdir(parents=True)
    (out / "constant/triSurface").mkdir(parents=True)
    (out / "system").mkdir()
    for name in patches:
        write_patch_stl(out / f"constant/triSurface/{name}.stl", name, solids[name])
    lo, hi = bounding_box(solids)
    box, cells = write_blockmesh_dict(out, lo, hi, cell_size)
    location_m = [CONVERT_TO_METERS * v for v in location_mm]
    write_snappy_dict(out, patches, refine, location_m)
    write_constant(out, args.solver)
    write_fields(out, patches_by_role, args.solver, per_inlet_flow, inlet_areas_m2,
                 boundary_mode=args.boundary_mode, inlet_pressure_pa=args.inlet_pressure_pa)
    write_system(out, patches_by_role, args.solver)

    files_sha = {}
    for path in sorted(out.rglob("*")):
        if path.is_file():
            files_sha[str(path.relative_to(out)).replace("\\", "/")] = sha256_bytes(path.read_bytes())
    split_note = ("imposed_equal_split_baseline" if len(inlets) > 1 else None)
    manifest = {
        "schema": "nasal_cfd_case/v1",
        "script": {"name": "surface_to_case.py", "version": SCRIPT_VERSION},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "surface": {"source_file": surface.name, "source_sha256": sha256_bytes(surface.read_bytes()),
                    "units": "mm",
                    "solids": {n: {"triangles": len(solids[n]), "area_mm2": areas_mm2[n]} for n in patches}},
        "convertToMeters": CONVERT_TO_METERS,
        "surface_written_in_meters": True,
        "patch_map": {n: patch_map[n] for n in patches},
        "patches_by_role": patches_by_role,
        "bbox_mm": {"min": lo, "max": hi},
        "background_box_mm": box,
        "cell_size_mm": cell_size,
        "block_cells": cells,
        "refine_level": refine,
        "location_in_mesh_mm": location_mm,
        "location_in_mesh_m": location_m,
        "solver": args.solver,
        "physics": {"rho_kg_m3": RHO, "mu_Pa_s": MU, "nu_m2_s": NU},
        "boundary": {
            "mode": args.boundary_mode,
            "total_flow_m3_s": total_flow,
            "per_inlet_flow_m3_s": per_inlet_flow,
            "inlet_profile": args.inlet_profile,
            "split_note": split_note,
            "split_interpretation": ("imposed_baseline_not_patient_split" if split_note else None),
            "outlet_static_pressure_Pa_gauge": 0.0,
            "inlet_static_pressure_Pa_gauge": (args.inlet_pressure_pa
                                                if args.boundary_mode == "common_inlet_pressure"
                                                else None),
            "common_inlet_pressure_feedback": {
                "status": ("case_template_only" if args.boundary_mode == "common_inlet_pressure"
                            else "not_implemented"),
                "reason": ("outer controller is implemented separately; this case is one fixed "
                           "pressure evaluation" if args.boundary_mode == "common_inlet_pressure"
                           else "fixed flow inlet boundary conditions")}} ,
        "fvSchemes": {"source": FVSCHEMES_SOURCE, "sha256": FVSCHEMES_SHA256},
        "files_sha256": files_sha,
    }
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    (out / "case_manifest.json").write_text(text, encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, help="surface file (.stl ascii with named solids, or .vtp)")
    parser.add_argument("--patch-map", required=True, help='JSON {"nostril_L":"inlet",...,"wall":"wall"}')
    parser.add_argument("--out", required=True, help="output case directory (must not exist)")
    parser.add_argument("--cell-size", default=0.4, type=float, help="background mesh target size in mm")
    parser.add_argument("--refine-level", default="1 1", help='castellated refinement "min max"')
    parser.add_argument("--location-in-mesh", required=True, help="point inside the fluid domain, mm")
    parser.add_argument("--solver", choices=["laminar", "kOmegaSST"], default="laminar")
    parser.add_argument("--flow-rate-m3s", type=float, default=DEFAULT_FLOW_M3_S,
                        help="total inlet flow (default 2.5e-4 = 15 L/min)")
    parser.add_argument("--boundary-mode", choices=["flow_driven_total_flow", "common_inlet_pressure"],
                        default="flow_driven_total_flow",
                        help="fixed-flow baseline or one common static-pressure evaluation")
    parser.add_argument("--inlet-pressure-pa", type=float, default=0.0,
                        help="common inlet static gauge pressure in Pa for common_inlet_pressure")
    parser.add_argument("--inlet-profile", choices=["plug", "parabolic"], default="plug",
                        help="plug = flowRateInletVelocity; parabolic = S2 rewrites the inlet "
                             "after meshing into an area-normalized parabolic profile (circular patches)")
    parser.add_argument("--dry-run", action="store_true",
                        help="only write case files; do not print the follow-up WSL command")
    args = parser.parse_args(argv)
    manifest = build_case(args)
    summary = {"out": str(Path(args.out).resolve()), "patches": manifest["patches_by_role"],
               "block_cells": manifest["block_cells"],
               "split_note": manifest["boundary"]["split_note"]}
    if not args.dry_run:
        script = Path(__file__).resolve().parents[1] / "07_cfd_pipeline" / "solver" / "run_openfoam_case.py"
        summary["next_step_wsl_command"] = (
            "wsl.exe -d Ubuntu-22.04 -- env WM_PROJECT_DIR=/usr/share/openfoam "
            "FOAM_ETC=/usr/share/openfoam/etc WM_PROJECT_VERSION=v1912 python3 "
            + wsl_path(script) + " --case " + wsl_path(args.out))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
