"""Extract nasal-CFD metrics from a run case: foamToVTK XML output + solver log.

Dual-end script: standard library only (no VTK/NumPy), so it runs identically
with the Windows nasal-cfd Python and the WSL python3. v1912
`foamToVTK -ascii` writes XML VTP/VTU with DataArray format='ascii'; appended
or binary encodings are rejected with an explicit error.

Primary metric source is the VTK patch/internal fields (spec section 5.2);
when postProcessing surfaceFieldValue .dat files exist they are cross-checked
against the VTK-derived values and disagreements are reported as warnings.

Honesty rules (contract-aligned): metrics that cannot be computed from the
available inputs are reported as not_computed with a reason, never as 0;
laminar runs report turbulence_intensity_status not_applicable; anatomic
region flow fractions are never approximated by geometric proxies.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

SCRIPT_VERSION = "1.0.0"
RHO_DEFAULT = 1.20
LITERATURE_BAND_PA = (10.0, 20.0)
LITERATURE_NOTE = ("sentinel band 10-20 Pa derives from an ENS (low-resistance) cohort "
                   "(PMC8062271); it flags broken geometry/boundaries only and is NOT a "
                   "pass criterion")
CROSSCHECK_REL_TOL = 0.001


def fail(message):
    print("extract_cfd_metrics error: " + message, file=sys.stderr)
    raise SystemExit(2)


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_data_array(element):
    fmt = element.get("format", "ascii")
    if fmt != "ascii":
        fail("DataArray '%s' uses format='%s'; only format='ascii' is supported"
             % (element.get("Name"), fmt))
    components = int(element.get("NumberOfComponents", "1"))
    values = [float(v) for v in (element.text or "").split()]
    if components == 1:
        return values
    if len(values) % components:
        fail("DataArray '%s': %d values not divisible by %d components"
             % (element.get("Name"), len(values), components))
    return [tuple(values[i:i + components]) for i in range(0, len(values), components)]


def _piece(tree_root, dataset_tag):
    root = tree_root
    if root.tag != "VTKFile":
        fail("not a VTKFile: " + root.tag)
    piece = root.find(f".//{dataset_tag}/Piece")
    if piece is None:
        fail(f"no <{dataset_tag}><Piece> in file")
    return piece


def read_vtp(path):
    """Read an XML PolyData patch: points, polygons, CellData."""
    tree = ET.parse(str(path))
    piece = _piece(tree.getroot(), "PolyData")
    points = parse_data_array(piece.find("Points/DataArray"))
    polys = piece.find("Polys")
    connectivity, offsets = None, None
    for array in polys.findall("DataArray"):
        if array.get("Name") == "connectivity":
            connectivity = [int(v) for v in parse_data_array(array)]
        elif array.get("Name") == "offsets":
            offsets = [int(v) for v in parse_data_array(array)]
    if connectivity is None or offsets is None:
        fail(str(path) + ": Polys connectivity/offsets missing")
    faces, start = [], 0
    for end in offsets:
        faces.append(connectivity[start:end])
        start = end
    cell_data = {}
    for block in piece.findall("CellData"):
        for array in block.findall("DataArray"):
            cell_data[array.get("Name")] = parse_data_array(array)
    return {"points": points, "faces": faces, "cell_data": cell_data}


def read_vtu(path):
    """Read an XML UnstructuredGrid: points, cell connectivity, CellData."""
    tree = ET.parse(str(path))
    piece = _piece(tree.getroot(), "UnstructuredGrid")
    points = parse_data_array(piece.find("Points/DataArray"))
    cells_elem = piece.find("Cells")
    arrays = {a.get("Name"): parse_data_array(a) for a in cells_elem.findall("DataArray")}
    connectivity = [int(v) for v in arrays["connectivity"]]
    offsets = [int(v) for v in arrays["offsets"]]
    cells, start = [], 0
    for end in offsets:
        cells.append(connectivity[start:end])
        start = end
    cell_data = {}
    for block in piece.findall("CellData"):
        for array in block.findall("DataArray"):
            cell_data[array.get("Name")] = parse_data_array(array)
    return {"points": points, "cells": cells, "cell_data": cell_data}


def newell(points):
    nx = ny = nz = 0.0
    for i, p in enumerate(points):
        q = points[(i + 1) % len(points)]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    return (nx, ny, nz)


def patch_metrics(vtp):
    """Area, area-averaged p, signed outward flow, and optional WSS force per patch."""
    points, faces, data = vtp["points"], vtp["faces"], vtp["cell_data"]
    n = len(faces)
    for name in ("p", "U"):
        if name in data and len(data[name]) != n:
            fail("CellData '%s' has %d tuples for %d faces" % (name, len(data[name]), n))
    total_area = 0.0
    p_weighted = 0.0
    flow = 0.0
    wss_force = 0.0
    wss = data.get("wallShearStress")
    for i, face in enumerate(faces):
        pts = [points[j] for j in face]
        nv = newell(pts)
        area = 0.5 * math.sqrt(sum(c * c for c in nv))
        total_area += area
        if "p" in data:
            p_weighted += data["p"][i] * area
        if "U" in data:
            flow += 0.5 * sum(data["U"][i][a] * nv[a] for a in range(3))
        if wss is not None:
            magnitude = math.sqrt(sum(c * c for c in wss[i]))
            wss_force += magnitude * area  # kinematic m2/s2 * m2; multiplied by rho by caller
    return {"area_m2": total_area,
            "p_area_weighted": (p_weighted / total_area if total_area and "p" in data else None),
            "signed_flow_m3_s": flow,
            "wss_area_integral_kinematic": (wss_force if wss is not None else None)}


def latest_vtk_dir(case):
    vtk_root = case / "VTK"
    if not vtk_root.is_dir():
        fail("no VTK directory in case (run foamToVTK first): " + str(case))
    candidates = []
    for entry in vtk_root.iterdir():
        match = re.match(r".*_(\d+)$", entry.name)
        if entry.is_dir() and match:
            candidates.append((int(match.group(1)), entry))
    if not candidates:
        fail("no time-stamped VTK output directory found under " + str(vtk_root))
    return max(candidates)[1]


def infer_roles(patch_names, case_manifest):
    """Patch -> role. Prefer case_manifest patch_map; fall back to name heuristics."""
    if case_manifest and isinstance(case_manifest.get("patch_map"), dict):
        return dict(case_manifest["patch_map"])
    roles = {}
    for name in patch_names:
        low = name.lower()
        if "inlet" in low:
            roles[name] = "inlet"
        elif "outlet" in low:
            roles[name] = "outlet"
        else:
            roles[name] = "wall"
    return roles


def last_dat_value(case, function):
    folder = case / "postProcessing" / function
    if not folder.is_dir():
        return None
    files = sorted(folder.glob("*/surfaceFieldValue.dat"))
    if not files:
        return None
    rows = [r.split() for r in files[-1].read_text(encoding="utf-8", errors="replace").splitlines()
            if r.strip() and not r.startswith("#")]
    if not rows:
        return None
    return float(rows[-1][1])


def crosscheck(case, patch, kind, role, vtk_value, warnings):
    """Compare against surfaceFieldValue dat when present (flow_<p>/pressure_<p>;
    legacy single-patch names flowIn/flowOut/pressureIn/pressureOut per role)."""
    name, value = dat_value(case, patch, kind, role)
    if name is None:
        return None, None
    reference, actual = value, vtk_value  # both kinematic p, or both signed phi
    scale = max(abs(reference), 1e-30)
    if abs(actual - reference) / scale > CROSSCHECK_REL_TOL:
        warnings.append("crosscheck %s on patch %s: vtk=%r vs functionObject=%r (%s)"
                        % (kind, patch, actual, reference, name))
    return name, reference


def dat_value(case, patch, kind, role):
    """surfaceFieldValue dat for a patch: flow_<p>/pressure_<p> or legacy per-role names."""
    legacy = {"inlet": {"flow": "flowIn", "pressure": "pressureIn"},
              "outlet": {"flow": "flowOut", "pressure": "pressureOut"}}
    names = {"flow": ["flow_" + patch], "pressure": ["pressure_" + patch]}[kind]
    if role in legacy:
        names.append(legacy[role][kind])
    for name in names:
        value = last_dat_value(case, name)
        if value is not None:
            return name, value
    return None, None


def extract(case, valve_slice=None, valve_slab_mm=0.5, rho=RHO_DEFAULT):
    case = Path(case)
    if not case.is_dir():
        fail("case directory not found: " + str(case))
    log_path = case / "log.simpleFoam"
    if not log_path.is_file():
        fail("missing required solver log: " + str(log_path))
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    case_manifest = None
    if (case / "case_manifest.json").is_file():
        case_manifest = json.loads((case / "case_manifest.json").read_text(encoding="utf-8"))

    vtk_dir = latest_vtk_dir(case)
    boundary_dir = vtk_dir / "boundary"
    if not boundary_dir.is_dir():
        fail("no boundary patch VTK directory: " + str(boundary_dir))
    internal_path = vtk_dir / "internal.vtu"
    if not internal_path.is_file():
        fail("missing internal field: " + str(internal_path))

    patch_files = {p.stem: p for p in sorted(boundary_dir.glob("*.vtp"))}
    if not patch_files:
        fail("no patch VTP files under " + str(boundary_dir))
    roles = infer_roles(list(patch_files), case_manifest)
    patches = {}
    warnings = []
    inputs_sha = {}
    for name, path in patch_files.items():
        inputs_sha[str(path.relative_to(case)).replace("\\", "/")] = sha256_file(path)
        patches[name] = patch_metrics(read_vtp(path))
        patches[name]["role"] = roles.get(name, "wall")
    inputs_sha[str(internal_path.relative_to(case)).replace("\\", "/")] = sha256_file(internal_path)
    inputs_sha["log.simpleFoam"] = sha256_file(log_path)

    inlets = sorted(n for n in patches if patches[n]["role"] == "inlet")
    outlets = sorted(n for n in patches if patches[n]["role"] == "outlet")
    if not inlets or not outlets:
        fail("need at least one inlet and one outlet patch; got roles: " + repr(roles))

    # Pressures (kinematic) area-weighted across all inlet / all outlet faces.
    def combined(pnames, values):
        area = sum(patches[n]["area_m2"] for n in pnames)
        if area <= 0:
            fail("zero total area on patches: " + ", ".join(pnames))
        return sum(values[n] * patches[n]["area_m2"] for n in pnames) / area

    # Prefer double-precision functionObject dat (12 significant digits) when
    # available for every inlet/outlet patch; VTK Float32 is the fallback and
    # is always cross-checked against dat when both exist.
    dat_flow, dat_p = {}, {}
    for name in inlets + outlets:
        role = patches[name]["role"]
        _, dat_flow[name] = dat_value(case, name, "flow", role)
        _, dat_p[name] = dat_value(case, name, "pressure", role)
    boundary_source = "vtk_patch_fields"
    if all(dat_flow[n] is not None and dat_p[n] is not None for n in inlets + outlets):
        boundary_source = "function_object_dat"
        p_in = combined(inlets, dat_p)
        p_out = combined(outlets, dat_p)
        patch_flow = {n: abs(dat_flow[n]) for n in inlets + outlets}
    else:
        p_in = combined(inlets, {n: patches[n]["p_area_weighted"] for n in inlets})
        p_out = combined(outlets, {n: patches[n]["p_area_weighted"] for n in outlets})
        patch_flow = {n: abs(patches[n]["signed_flow_m3_s"]) for n in inlets + outlets}
    q_in = sum(patch_flow[n] for n in inlets)
    q_out = sum(patch_flow[n] for n in outlets)
    delta_p = rho * (p_in - p_out)

    crosschecks = {}
    for name in inlets + outlets:
        role = patches[name]["role"]
        fname, ref = crosscheck(case, name, "pressure", role, patches[name]["p_area_weighted"], warnings)
        gname, gref = crosscheck(case, name, "flow", role, patches[name]["signed_flow_m3_s"], warnings)
        if fname or gname:
            crosschecks[name] = {"pressure_function": fname, "flow_function": gname}

    # Bilateral split.
    def side_of(name):
        low = name.lower()
        if low.endswith("_l") or "left" in low:
            return "L"
        if low.endswith("_r") or "right" in low:
            return "R"
        return None

    if len(inlets) == 1:
        split_ratio = {"status": "not_applicable", "reason": "single inlet patch; bilateral split undefined"}
        symmetry_phi = {"status": "not_applicable", "reason": "single inlet patch; bilateral split undefined"}
    else:
        left = [n for n in inlets if side_of(n) == "L"]
        right = [n for n in inlets if side_of(n) == "R"]
        if len(left) == 1 and len(right) == 1:
            ql = patch_flow[left[0]]
            qr = patch_flow[right[0]]
            if ql + qr > 0:
                split_ratio = {"value": ql / (ql + qr), "left_patch": left[0], "right_patch": right[0]}
                symmetry_phi = {"value": (ql / qr if qr else None), "left_patch": left[0], "right_patch": right[0]}
            else:
                split_ratio = {"status": "not_computed", "reason": "zero total inlet flow"}
                symmetry_phi = {"status": "not_computed", "reason": "zero total inlet flow"}
        else:
            reason = ("inlet patches cannot be assigned to left/right by name; "
                      "rename patches with _L/_R suffixes")
            split_ratio = {"status": "not_computed", "reason": reason}
            symmetry_phi = {"status": "not_computed", "reason": reason}

    internal = read_vtu(internal_path)
    velocities = internal["cell_data"].get("U")
    if velocities is None:
        fail("internal.vtu has no CellData U")
    max_velocity = max(math.sqrt(sum(c * c for c in u)) for u in velocities)

    if valve_slice is None:
        valve = {"status": "not_computed",
                 "reason": "no --valve-slice given; nasal valve plane is case-specific"}
    else:
        axis, plane_m = valve_slice
        half = 0.5 * valve_slab_mm * 1e-3
        points = internal["points"]
        peak = 0.0
        count = 0
        for i, cell in enumerate(internal["cells"]):
            centroid = [sum(points[j][a] for j in cell) / len(cell) for a in range(3)]
            if abs(centroid[axis] - plane_m) <= half:
                count += 1
                peak = max(peak, math.sqrt(sum(c * c for c in velocities[i])))
        if count:
            valve = {"value_mps": peak, "cells_in_slab": count,
                     "slab_half_thickness_m": half}
        else:
            valve = {"status": "not_computed",
                     "reason": "no internal cells within the valve slab; adjust --valve-slab-mm"}

    walls = [n for n in patches if patches[n]["role"] == "wall"]
    wall_area = sum(patches[n]["area_m2"] for n in walls)
    zero_walls = sorted(n for n in walls
                        if patches[n]["wss_area_integral_kinematic"] == 0.0
                        and patches[n]["area_m2"] > 0)
    if any(patches[n]["wss_area_integral_kinematic"] is not None for n in walls):
        if zero_walls:
            # An exactly-zero integral over a nonzero-area wall patch cannot
            # happen in a real flow field (Float32 preserves any nonzero
            # value); it is the signature of a mesh with no patch typed
            # 'wall', for which the wallShearStress function object writes an
            # all-zero field SILENTLY (observed on the T-042 b15 maxh1 case:
            # the first extraction reported wall_shear_force_n = 0.0).
            # Honesty semantics: report not_computed, never a fabricated 0.
            wall_shear = {"status": "not_computed",
                          "reason": ("wallShearStress array present but integrates to "
                                     "exactly 0 on nonzero-area wall patch(es): %s "
                                     "(total wall area %.6g m2). Exactly-zero is the "
                                     "signature of a mesh with no patch typed 'wall' "
                                     "(the function object then writes an all-zero "
                                     "field silently). No value is fabricated."
                                     % (", ".join(zero_walls), wall_area))}
            warnings.append("all-zero wallShearStress on %s (area %.6g m2); "
                            "wall_shear_force_n reported not_computed, not 0"
                            % (", ".join(zero_walls), wall_area))
        else:
            wss_force = rho * sum(patches[n]["wss_area_integral_kinematic"] or 0.0 for n in walls)
            wall_shear = {"value_n": wss_force,
                          "note": "wallShearStress is kinematic (m2/s2); multiplied by rho"}
    else:
        wall_shear = {"status": "not_computed",
                      "reason": ("wallShearStress field absent; run "
                                 "`postProcess -func wallShearStress` before foamToVTK. "
                                 "No velocity-gradient substitute is fabricated.")}

    turbulence = case / "constant/turbulenceProperties"
    model = "laminar"
    if turbulence.is_file() and "kOmegaSST" in turbulence.read_text(encoding="ascii"):
        model = "kOmegaSST"
    if model == "laminar":
        turbulence_report = {"report_status": "not_applicable",
                             "reason": "laminar run; no modeled turbulence intensity exists (never report 0%)"}
    else:
        turbulence_report = {"report_status": "modeled_field",
                             "model": "kOmegaSST",
                             "note": "batch-1 metrics do not summarize the modeled TI field"}

    band_lo, band_hi = LITERATURE_BAND_PA
    magnitude = {"value": ("within_literature_band" if band_lo <= delta_p <= band_hi else "outside"),
                 "band_pa": [band_lo, band_hi], "warning": LITERATURE_NOTE}

    metrics = {
        "schema": "nasal_cfd_metrics/v1",
        "script": {"name": "extract_cfd_metrics.py", "version": SCRIPT_VERSION},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case": {"name": case.name},
        "source": {"vtk_time_dir": vtk_dir.name, "patches": sorted(patch_files),
                   "inputs_sha256": inputs_sha,
                   "run_manifest_present": (case / "run_manifest.json").is_file()},
        "solver": model,
        "rho_kg_m3": rho,
        "pressure_note": "OpenFOAM p is kinematic (m2/s2); Pa values multiplied by rho",
        "metrics": {
            "delta_p_pa": {"value": delta_p, "source": boundary_source,
                           "p_in_kinematic": p_in, "p_out_kinematic": p_out},
            "total_flow_m3s": {"value": q_in, "source": boundary_source},
            "outlet_flow_m3s": {"value": q_out},
            "split_ratio": split_ratio,
            "symmetry_phi": symmetry_phi,
            "max_velocity_mps": {"value": max_velocity, "source": "vtk_internal_cell_U"},
            "nasal_valve_peak_mps": valve,
            "wall_shear_force_n": wall_shear,
            "resistance_R": {"value_pa_s_m3": (delta_p / q_in if q_in > 0 else None),
                             "value_pa_s_ml": (delta_p / q_in / 1e6 if q_in > 0 else None)},
            "converged": "SIMPLE solution converged" in log_text,
            "mass_imbalance_frac": (abs(q_in - q_out) / q_in if q_in > 0 else None),
            "region_flow_fraction": {"status": "not_computed",
                                     "reason": ("requires verified anatomic region labels; "
                                                "not available. Geometric proxies (z-slices, "
                                                "largest-component) are falsified and forbidden.")},
            "turbulence_intensity": turbulence_report,
            "magnitude_check": magnitude,
        },
        "per_patch": {n: {"role": patches[n]["role"], "area_m2": patches[n]["area_m2"],
                          "p_area_weighted_kinematic": patches[n]["p_area_weighted"],
                          "signed_flow_m3_s": patches[n]["signed_flow_m3_s"]}
                      for n in sorted(patches)},
        "function_object_crosscheck": crosschecks,
        "warnings": warnings,
    }
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, help="run case directory (with VTK/ and log.simpleFoam)")
    parser.add_argument("--out", required=True, help="metrics JSON output path")
    parser.add_argument("--valve-slice", help='nasal valve plane, e.g. "z=12.5" (mm, surface units)')
    parser.add_argument("--valve-slab-mm", type=float, default=0.5,
                        help="slab thickness around the valve plane in mm (default 0.5)")
    parser.add_argument("--region-mask", help="optional region mask NIfTI (batch-1: still reports "
                                              "not_computed; anatomic attribution needs verified labels)")
    parser.add_argument("--rho", type=float, default=RHO_DEFAULT)
    args = parser.parse_args(argv)
    valve_slice = None
    if args.valve_slice:
        match = re.match(r"^\s*([xyzXYZ])\s*=\s*([-+0-9.eE]+)\s*$", args.valve_slice)
        if not match:
            fail('--valve-slice must look like "z=12.5" (mm)')
        valve_slice = ("xyz".index(match.group(1).lower()), float(match.group(2)) * 1e-3)
    metrics = extract(Path(args.case), valve_slice=valve_slice,
                      valve_slab_mm=args.valve_slab_mm, rho=args.rho)
    if args.region_mask:
        metrics["metrics"]["region_flow_fraction"] = {
            "status": "not_computed",
            "reason": ("region mask supplied but region-to-flow attribution requires verified "
                       "anatomic label semantics; deferred to batch 2 (no proxy is used)")}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps({"out": str(out), "delta_p_pa": metrics["metrics"]["delta_p_pa"]["value"],
                      "converged": metrics["metrics"]["converged"],
                      "mass_imbalance_frac": metrics["metrics"]["mass_imbalance_frac"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
