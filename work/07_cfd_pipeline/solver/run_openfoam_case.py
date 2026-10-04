"""Generic OpenFOAM v1912 case executor (generalized from run_reference.py).

Execute with the WSL python3, not the Windows Python:
    python3 run_openfoam_case.py --case /mnt/c/ts_work/<case> \
        --steps blockMesh,snappyHexMesh,checkMesh,simpleFoam,foamToVTK

The case directory path must be pure ASCII (OpenFOAM v1912 fails on
non-ASCII cwd). Each step is logged to <case>/log.<step>; the first non-zero
step raises immediately and all prior logs are preserved. A run_manifest.json
is always written, embedding case_manifest.json so results trace back to the
input geometry.

If case_manifest.json declares boundary.inlet_profile == "parabolic", the
inlet flowRateInletVelocity entries written by surface_to_case.py are replaced
(after meshing, before simpleFoam) by an area-normalized parabolic fixedValue
profile, using the same midpoint-normalization approach as run_reference.py.

No patient data: this executor is geometry-agnostic.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "solver_reference"))
from run_reference import execute, foam_list_text

SCRIPT_VERSION = "1.1.0"
ENV_OVERRIDES = {"WM_PROJECT_DIR": "/usr/share/openfoam",
                 "FOAM_ETC": "/usr/share/openfoam/etc",
                 "WM_PROJECT_VERSION": "v1912"}
ALL_STEPS = ["blockMesh", "snappyHexMesh", "checkMesh", "simpleFoam", "foamToVTK"]
TOOLS = ["blockMesh", "snappyHexMesh", "checkMesh", "simpleFoam", "foamToVTK", "postProcess"]
REQUIRED_COMMON = ["0/p", "0/U", "constant/transportProperties", "constant/turbulenceProperties",
                   "system/controlDict", "system/fvSchemes", "system/fvSolution"]
REQUIRED_SST = ["0/k", "0/omega", "0/nut"]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_environment():
    environment = os.environ.copy()
    environment.update(ENV_OVERRIDES)
    return environment


def env_check(environment):
    import subprocess
    report = {}
    for tool in TOOLS:
        process = subprocess.run([tool, "-help"], env=environment,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        report[tool] = {"exit_code": process.returncode}
    report["environment_overrides"] = ENV_OVERRIDES
    report["openfoam_version"] = ENV_OVERRIDES["WM_PROJECT_VERSION"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if all(report[tool]["exit_code"] == 0 for tool in TOOLS) else 1


def is_sst(case):
    text = (case / "constant/turbulenceProperties").read_text(encoding="ascii")
    return "kOmegaSST" in text


def check_case_complete(case, steps):
    required = list(REQUIRED_COMMON)
    if is_sst(case):
        required += REQUIRED_SST
    if "blockMesh" in steps:
        required.append("system/blockMeshDict")
    if "snappyHexMesh" in steps:
        required.append("system/snappyHexMeshDict")
    missing = [rel for rel in required if not (case / rel).is_file()]
    if "snappyHexMesh" in steps:
        tris = list((case / "constant/triSurface").glob("*.stl")) if (case / "constant/triSurface").is_dir() else []
        if not tris:
            missing.append("constant/triSurface/*.stl")
    if missing:
        print("run_openfoam_case error: case is incomplete, missing:\n  " + "\n  ".join(missing),
              file=sys.stderr)
        raise SystemExit(2)


def patch_faces(case, patch_name):
    """Return (centers, area_vectors) for a boundary patch from constant/polyMesh."""
    mesh = case / "constant/polyMesh"
    npoints, text = foam_list_text(mesh / "points")
    points = [tuple(float(v) for v in p.split()) for p in re.findall(r"\(([^()]*)\)", text)[:npoints]]
    nfaces, text = foam_list_text(mesh / "faces")
    faces = [[int(v) for v in f.split()] for f in re.findall(r"\d+\(([^()]*)\)", text)[:nfaces]]
    boundary = (mesh / "boundary").read_text(encoding="ascii")
    match = re.search(r"\b" + re.escape(patch_name) + r"\s*\{([^}]+)\}", boundary)
    if not match:
        raise ValueError("patch not found in polyMesh/boundary: " + patch_name)
    count = int(re.search(r"\bnFaces\s+(\d+)", match.group(1)).group(1))
    start = int(re.search(r"\bstartFace\s+(\d+)", match.group(1)).group(1))
    centers, area_vectors = [], []
    for face in faces[start:start + count]:
        pts = [points[i] for i in face]
        center = tuple(sum(p[a] for p in pts) / len(pts) for a in range(3))
        # Fan triangulation around pts[0]: sum of triangle area vectors.
        ax = ay = az = 0.0
        for k in range(1, len(pts) - 1):
            ux, uy, uz = (pts[k][a] - pts[0][a] for a in range(3))
            vx, vy, vz = (pts[k + 1][a] - pts[0][a] for a in range(3))
            ax += uy * vz - uz * vy
            ay += uz * vx - ux * vz
            az += ux * vy - uy * vx
        centers.append(center)
        area_vectors.append((ax / 2.0, ay / 2.0, az / 2.0))
    return centers, area_vectors


def circular_source_geometry(case, patch, inward_normal):
    """Recover the circular profile center/radius from source surface vertices.

    Face centroids lie inside the disk and systematically underestimate radius.
    The source STL is already in metres, per the S1 unit contract.
    """
    source = case / 'constant' / 'triSurface' / (patch + '.stl')
    text = source.read_text(encoding='ascii')
    vertices = [tuple(float(value) for value in xyz) for xyz in
                re.findall(r'vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)', text)]
    if not vertices or len(vertices) % 3:
        raise ValueError('Circular profile requires valid source STL: ' + patch)
    area_sum = 0.0
    center_sum = [0.0]*3
    normal_sum = [0.0]*3
    for i in range(0, len(vertices), 3):
        a, b, c = vertices[i:i+3]
        u, v = ([b[j]-a[j] for j in range(3)], [c[j]-a[j] for j in range(3)])
        cross = (u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])
        area = math.sqrt(sum(value*value for value in cross))/2
        area_sum += area
        for j in range(3):
            center_sum[j] += area*(a[j]+b[j]+c[j])/3
            normal_sum[j] += cross[j]/2
    if area_sum <= 0:
        raise ValueError('Circular source has zero area: ' + patch)
    center = tuple(value/area_sum for value in center_sum)
    normal_magnitude = math.sqrt(sum(v*v for v in normal_sum))
    if normal_magnitude <= 0:
        raise ValueError('Circular source has inconsistent normals: ' + patch)
    orientation = 1 if sum(normal_sum[j]*inward_normal[j] for j in range(3)) > 0 else -1
    normal = tuple(orientation*v/normal_magnitude for v in normal_sum)
    radius = 0.0
    max_plane_error = 0.0
    for vertex in vertices:
        delta = [vertex[j]-center[j] for j in range(3)]
        axial = sum(delta[j]*normal[j] for j in range(3))
        max_plane_error = max(max_plane_error,abs(axial))
        radius = max(radius,math.sqrt(max(0,sum(v*v for v in delta)-axial*axial)))
    if radius <= 0 or max_plane_error > radius*1e-6:
        raise ValueError('Circular source is degenerate or not planar: ' + patch)
    if abs(area_sum/(math.pi*radius**2)-1) > .02:
        raise ValueError('Parabolic inlet source must approximate a circular disk: ' + patch)
    return center, radius, normal


def mesh_quality(case):
    text = (case / 'log.checkMesh').read_text(encoding='utf-8',errors='replace')
    failed = re.search(r'Failed\s+(\d+)\s+mesh checks', text)
    passed = 'Mesh OK.' in text and not failed and 'FOAM FATAL' not in text
    return {'passed': passed, 'failed_checks': int(failed.group(1)) if failed else None,
            'log': 'log.checkMesh'}


def set_parabolic_inlet(case, manifest):
    """Replace inlet flowRateInletVelocity entries with area-normalized parabolic profiles."""
    per_inlet = manifest["boundary"]["per_inlet_flow_m3_s"]
    text = (case / "0/U").read_text(encoding="ascii")
    record = {}
    for patch, flow in sorted(per_inlet.items()):
        centers, area_vectors = patch_faces(case, patch)
        if not centers:
            raise ValueError("patch has no faces: " + patch)
        area = [math.sqrt(sum(c * c for c in av)) for av in area_vectors]
        total_area = sum(area)
        if total_area <= 0:
            raise ValueError("patch has zero area: " + patch)
        # Patch outward normal from the summed area vector; inflow is opposite.
        sx, sy, sz = (sum(av[a] for av in area_vectors) for a in range(3))
        norm = math.sqrt(sx * sx + sy * sy + sz * sz)
        if norm == 0.0:
            raise ValueError("patch has zero net normal (not planar?): " + patch)
        normal = (-sx / norm, -sy / norm, -sz / norm)
        center, radius, normal = circular_source_geometry(case, patch, normal)
        u_mean = flow / total_area
        speeds = []
        for face in centers:
            delta = [face[a]-center[a] for a in range(3)]
            axial = sum(delta[a]*normal[a] for a in range(3))
            radial_squared = max(0,sum(v*v for v in delta)-axial*axial)
            speeds.append(2.0*u_mean*max(0,1-radial_squared/radius**2))
        # Midpoint samples -> normalize to the exact imposed flow (run_reference pattern).
        projected_area = [-sum(av[j]*normal[j] for j in range(3)) for av in area_vectors]
        if any(value <= 0 for value in projected_area):
            raise ValueError('Circular inlet mesh faces have inconsistent orientation: ' + patch)
        sampled_flow = sum(speeds[i]*projected_area[i] for i in range(len(centers)))
        if sampled_flow <= 0:
            raise ValueError('Circular inlet has zero sampled flux: ' + patch)
        scale = flow / sampled_flow
        values = "\n".join("(%s %s %s)" % tuple("%.16g" % (speeds[i] * scale * normal[a])
                                                for a in range(3)) for i in range(len(centers)))
        entry = (" %s { type fixedValue; value nonuniform List<vector> %d ( %s ); }"
                 % (patch, len(centers), values))
        pattern = r" " + re.escape(patch) + r" \{ type flowRateInletVelocity;[^}]*\}"
        if not re.search(pattern, text):
            raise ValueError("0/U has no flowRateInletVelocity entry for patch: " + patch)
        text = re.sub(pattern, entry, text)
        record[patch] = {"inlet_faces": len(centers), "patch_area_m2": total_area,
                         "patch_radius_m": radius, "imposed_Q_m3_s": flow,
                         "radius_source": "source_STL_boundary_vertices", "profile_center_m": center,
                         "normal_source": "source_STL_area_vector", "flux_normalization": "projected_mesh_face_area",
                         "profile_midpoint_normalization": scale,
                         "u_mean_m_s": u_mean, "u_center_m_s": 2.0 * u_mean * scale}
    (case / "0/U").write_text(text, encoding="ascii")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="case directory produced by surface_to_case.py")
    parser.add_argument("--steps", default=",".join(ALL_STEPS),
                        help="ordered comma subset of " + ",".join(ALL_STEPS))
    parser.add_argument("--env-check", action="store_true",
                        help="only verify environment variables and tool availability")
    parser.add_argument('--allow-failed-mesh-for-diagnostic', action='store_true',
                        help='Allow failed mesh checks only for synthetic tube.stl diagnostics; never mark engineering acceptance')
    args = parser.parse_args(argv)
    if args.env_check:
        return env_check(build_environment())
    if not args.case:
        parser.error("--case is required unless --env-check")
    case = Path(args.case).resolve()
    if not str(case).isascii():
        print("run_openfoam_case error: case path must be pure ASCII for OpenFOAM v1912; "
              "move the case under /mnt/c/ts_work (got: %s)" % case, file=sys.stderr)
        return 2
    if not case.is_dir():
        print("run_openfoam_case error: case directory not found: %s" % case, file=sys.stderr)
        return 2
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    unknown = [s for s in steps if s not in ALL_STEPS]
    if unknown:
        print("run_openfoam_case error: unknown steps: " + ", ".join(unknown), file=sys.stderr)
        return 2
    check_case_complete(case, steps)
    environment = build_environment()
    sst = is_sst(case)
    manifest_path = case / "case_manifest.json"
    case_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else None
    if args.allow_failed_mesh_for_diagnostic and (
            not case_manifest or case_manifest.get('surface', {}).get('source_file') != 'tube.stl'
            or case_manifest.get('patch_map') != {'inlet':'inlet','outlet':'outlet','wall':'wall'}):
        parser.error('Failed-mesh diagnostic override is restricted to the synthetic tube.stl phantom')
    parabolic = (case_manifest or {}).get("boundary", {}).get("inlet_profile") == "parabolic"
    fields = "(p U k omega)" if sst else "(p U)"
    commands = {"blockMesh": ["blockMesh"],
                "snappyHexMesh": ["snappyHexMesh", "-overwrite"],
                "checkMesh": ["checkMesh", "-allGeometry", "-allTopology"],
                "simpleFoam": ["simpleFoam"],
                "foamToVTK": ["foamToVTK", "-latestTime", "-ascii", "-fields", fields]}
    run_manifest = {"schema": "nasal_cfd_run/v1",
                    "script": {"name": "run_openfoam_case.py", "version": SCRIPT_VERSION},
                    "started_at": utc_now(), "finished_at": None,
                    "case": str(case),
                    "openfoam_version": ENV_OVERRIDES["WM_PROJECT_VERSION"],
                    "environment_overrides": dict(ENV_OVERRIDES),
                    "steps": [], "case_manifest": case_manifest,
                    "execution_status": None}
    run_manifest['engineering_acceptance'] = False
    profile_done = False
    try:
        for step in steps:
            if step == 'simpleFoam':
                quality = mesh_quality(case)
                run_manifest['mesh_quality'] = quality
                run_manifest['failed_mesh_diagnostic_override'] = bool(not quality['passed'] and args.allow_failed_mesh_for_diagnostic)
                if not quality['passed'] and not args.allow_failed_mesh_for_diagnostic:
                    raise RuntimeError('Mesh quality did not pass; refusing to solve (see log.checkMesh)')
            if step == "simpleFoam" and parabolic and not profile_done:
                begin = utc_now()
                record = set_parabolic_inlet(case, case_manifest)
                run_manifest["steps"].append({"command": ["internal:set_parabolic_inlet_profile"],
                                              "exit_code": 0, "started_at": begin,
                                              "finished_at": utc_now(), "patches": record})
                profile_done = True
            run_manifest["steps"].append(execute(commands[step], case, environment, "log." + step))
            (case / "run_manifest.json").write_text(
                json.dumps(run_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        run_manifest["execution_status"] = "completed"
    except Exception as exc:
        run_manifest["execution_status"] = "failed"
        run_manifest["error"] = repr(exc)
        raise
    finally:
        run_manifest["finished_at"] = utc_now()
        (case / "run_manifest.json").write_text(
            json.dumps(run_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"case": str(case), "execution_status": run_manifest["execution_status"],
                      "steps": [s["command"][0] for s in run_manifest["steps"]]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
