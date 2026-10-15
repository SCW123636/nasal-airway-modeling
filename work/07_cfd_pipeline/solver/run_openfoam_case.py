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

Engineering bonuses (all opt-in, default behaviour unchanged):
    --status-file <name>     stream run_status.json after every sub-step so long
                             runs are observable (defaults to run_status.json)
    --archive-before-run     move stale numeric time dirs + prior manifests into
                             .archive/<utc>/ so a previous latestTime is never
                             reused as a starting solution
    --parallel N             run snappyHexMesh and simpleFoam under MPI with N
                             ranks (needs mpirun/decomposePar/reconstructPar;
                             auto-falls back to serial if any is missing)
    --skip-mesh-if-cached    reuse a previously checked mesh when its content
                             signature still matches (drops blockMesh/snappyHexMesh,
                             keeps checkMesh for revalidation)

No patient data: this executor is geometry-agnostic.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "solver_reference"))
from run_reference import foam_list_text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mesh_cache

# --- contract gate (T-003 R10) ------------------------------------------------
# The contract module lives in work/lib; on WSL `Path(__file__).resolve().
# parents[2] / "lib"` resolves there. Imported up front so a missing module
# fails loudly and clearly instead of surfacing as a bare ImportError traceback.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
try:
    import cfd_contract
except ImportError as exc:
    _lib_dir = Path(__file__).resolve().parents[2] / "lib"
    print("run_openfoam_case error: cannot import contract module 'cfd_contract' "
          "from %s: %s" % (_lib_dir, exc), file=sys.stderr)
    raise SystemExit(2)


class ContractRefusal(Exception):
    """Raised when a --config is supplied but is not execution-allowed."""

    def __init__(self, reasons):
        super().__init__("unsanctioned configuration")
        self.reasons = list(reasons)


def evaluate_contract(args):
    """Load + validate the optional --config and return run_manifest['contract'].

    Returns a dict with ``checked`` set False when no --config is given (so the
    script keeps running exactly as before). Raises ``ContractRefusal`` -- before
    any solver step runs -- when ``execution_allowed`` is False and
    --force-unsanctioned was not supplied. The refusal message names the concrete
    blocking reasons (they live in the contract ``warnings`` for our 8 configs).
    """
    if not args.config:
        return {"config_id": None, "checked": False}
    path = Path(args.config)
    if not path.is_file():
        raise ContractRefusal(["--config file not found: %s" % path])
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractRefusal(["--config is not readable/valid JSON (%s): %s" % (path, exc)])
    report = cfd_contract.validate_config(cfg)
    contract = {
        "config_id": cfg.get("config_id"),
        "execution_allowed": bool(report["execution_allowed"]),
        "errors": report["errors"],
        "warnings": report["warnings"],
        "forced": bool(args.force_unsanctioned),
        "checked": True,
    }
    engineering_path = getattr(args, 'engineering_authorization', None)
    if engineering_path:
        try:
            from patient_cfd_admission import validate_engineering_authorization
            contract['bound_engineering_authorization'] = validate_engineering_authorization(args.case, path, engineering_path)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            raise ContractRefusal(['bound engineering authorization refused: ' + str(exc)])
    if not report["execution_allowed"] and not args.force_unsanctioned and not engineering_path:
        # Concrete blocking reasons: errors first, then readiness warnings
        # (e.g. "solver adapter has not been implemented and verified ...").
        raise ContractRefusal(list(report["errors"]) + list(report["warnings"]))
    return contract


SCRIPT_VERSION = "1.2.1"
ENV_OVERRIDES = {"WM_PROJECT_DIR": "/usr/share/openfoam",
                 "FOAM_ETC": "/usr/share/openfoam/etc",
                 "WM_PROJECT_VERSION": "v1912"}
ALL_STEPS = ["blockMesh", "snappyHexMesh", "checkMesh", "simpleFoam", "foamToVTK"]
TOOLS = ["blockMesh", "snappyHexMesh", "checkMesh", "simpleFoam", "foamToVTK", "postProcess"]
REQUIRED_COMMON = ["0/p", "0/U", "constant/transportProperties", "constant/turbulenceProperties",
                   "system/controlDict", "system/fvSchemes", "system/fvSolution"]
REQUIRED_SST = ["0/k", "0/omega", "0/nut"]
MESH_STEPS = ["blockMesh", "snappyHexMesh", "checkMesh"]


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CommandExecutionError(RuntimeError):
    """Preserve the actual subprocess record before aborting the sequence."""
    def __init__(self, record):
        self.record = record
        super().__init__(f'{record["command"][0]} failed: {record["log"]}')


def execute(args, case, environment, logname):
    begin = time.perf_counter()
    record = {'command': args, 'exit_code': None, 'log': str(case / logname),
              'started_at': utc_now()}
    try:
        with (case / logname).open('w', encoding='utf-8') as output:
            process = subprocess.run(args, cwd=case, env=environment,
                                     stdout=output, stderr=subprocess.STDOUT)
        record['exit_code'] = process.returncode
    except OSError as exc:
        record['launch_error'] = repr(exc)
    record.update(elapsed_seconds=time.perf_counter() - begin, finished_at=utc_now())
    print(json.dumps(record), flush=True)
    if record['exit_code'] != 0:
        raise CommandExecutionError(record)
    return record


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


# --- engineering-bonus helpers -------------------------------------------------

def write_status(path, payload):
    """Atomic status write so a poller never reads a half-written JSON file."""
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    temp.write_text(text, encoding="utf-8")
    for delay in (0.03, 0.08, 0.18):
        try:
            temp.replace(path)
            return
        except PermissionError:
            time.sleep(delay)
    temp.unlink(missing_ok=True)


def _ensure_decompose_par_dict(case, nproc):
    """Write (or repair) a decomposeParDict usable on this machine.

    Two environment facts drive the content:
      * OpenFOAM's default ``method scotch`` aborts here -- this v1912 build ships a
        dummy scotchDecomp stub, so it raises "Attempted to use <scotch> without the
        scotchDecomp library loaded". ``hierarchical`` is built in and needs no library.
      * ``hierarchical`` reads the vector entry ``n``, not just ``numberOfSubdomains``;
        without ``n`` it aborts with "Entry 'n' not found in dictionary".
    Splitting along x suits the long thin duct cases (length >> cross-section).
    An existing dictionary is only touched when it is one of those two broken forms.
    """
    path = case / "system" / "decomposeParDict"
    header = ("FoamFile\n{\n version 2.0;\n format ascii;\n class dictionary;\n"
              " object decomposeParDict;\n}\n")
    body = (f"numberOfSubdomains {nproc};\n"
            f"n ({nproc} 1 1);\n"
            "method hierarchical;\ndistributed no;\nroots ();\n")
    if not path.is_file():
        path.write_text(header + body, encoding="ascii")
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if re.search(r"\bmethod\s+scotch\s*;", text, re.I):
        fixed = re.sub(r"\bmethod\s+scotch\s*;", "method hierarchical;", text, flags=re.I)
        if not re.search(r"^\s*n\s*\(", fixed, re.M | re.I):
            fixed = re.sub(r"(numberOfSubdomains\s+\d+\s*;)", r"\1\nn (%d 1 1);" % nproc,
                           fixed, count=1, flags=re.I)
        path.write_text(fixed, encoding="ascii")
        print("run_openfoam_case note: system/decomposeParDict selected scotch, but this OpenFOAM "
              "build has no libscotch.so; rewritten to hierarchical with an explicit n vector.",
              file=sys.stderr)
        return
    if re.search(r"\bmethod\s+hierarchical\s*;", text, re.I) and not re.search(r"^\s*n\s*\(", text, re.M | re.I):
        fixed = re.sub(r"(numberOfSubdomains\s+\d+\s*;)", r"\1\nn (%d 1 1);" % nproc,
                       text, count=1, flags=re.I)
        path.write_text(fixed, encoding="ascii")
        print("run_openfoam_case note: system/decomposeParDict used hierarchical without an n "
              "vector; added n (%d 1 1)." % nproc, file=sys.stderr)


def _archive_before_run(case):
    """Move stale numeric time dirs + prior manifests so no old latestTime is reused.

    The ``0/`` initial-conditions directory is preserved (it is solver input,
    not a previous solution); only strictly-positive time directories and the
    prior run manifests are moved under ``.archive/<utc>/``.
    """
    stamp = utc_now().replace(":", "").replace("-", "").replace("+", "Z")
    dest = case / ".archive" / stamp
    moved = []
    for child in sorted(case.iterdir()):
        if child.name in ("0", "constant", "system", ".archive"):
            continue
        if child.is_dir() and re.fullmatch(r"\d+(\.\d+)?", child.name) and float(child.name) > 0:
            dest.mkdir(parents=True, exist_ok=True)
            child.replace(dest / child.name)
            moved.append(child.name)
        elif child.name in ("run_manifest.json", "run_status.json"):
            # mesh_cache.json is deliberately NOT archived: it is the cross-run
            # mesh-reuse record, and archiving it would defeat --skip-mesh-if-cached.
            dest.mkdir(parents=True, exist_ok=True)
            child.replace(dest / child.name)
            moved.append(child.name)
    return {"archived_to": str(dest), "moved": moved}


def _effective_sequence(step, commands, parallel, nproc):
    """Expand a requested step into the actual command sequence.

    Parallel mode injects decomposePar / reconstructPar around the two
    mesh-heavy tools. Serial mode is a single pass-through (default behaviour).
    """
    if not parallel:
        return [(step, commands[step])]
    if step == "snappyHexMesh":
        return [("decomposePar", ["decomposePar", "-force", "-noFields"]),
                ("snappyHexMesh", ["mpirun", "-np", str(nproc), "snappyHexMesh", "-parallel", "-overwrite"]),
                ("reconstructPar", ["reconstructPar", "-constant", "-noFields", "-time", "0"])]
    if step == "simpleFoam":
        return [("decomposePar", ["decomposePar", "-force", "-time", "0"]),
                ("simpleFoam", ["mpirun", "-np", str(nproc), "simpleFoam", "-parallel"]),
                ("reconstructPar", ["reconstructPar", "-latestTime"])]
    return [(step, commands[step])]


def _expanded_total(steps, commands, parallel, nproc):
    return sum(len(_effective_sequence(s, commands, parallel, nproc)) for s in steps)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="case directory produced by surface_to_case.py")
    parser.add_argument("--steps", default=",".join(ALL_STEPS),
                        help="ordered comma subset of " + ",".join(ALL_STEPS))
    parser.add_argument("--env-check", action="store_true",
                        help="only verify environment variables and tool availability")
    parser.add_argument('--allow-failed-mesh-for-diagnostic', action='store_true',
                        help='Allow failed mesh checks only for synthetic tube.stl diagnostics; never mark engineering acceptance')
    parser.add_argument('--status-file', default='run_status.json',
                        help='streaming status file name written after each sub-step')
    parser.add_argument('--archive-before-run', action='store_true',
                        help='archive stale time dirs + prior manifests before running')
    parser.add_argument('--parallel', type=int, default=0,
                        help='MPI ranks for snappyHexMesh/simpleFoam (>=2 enables; 0/1 = serial)')
    parser.add_argument('--skip-mesh-if-cached', action='store_true',
                        help='reuse a previously checked mesh when its content signature matches')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the planned command sequence and exit without executing or writing')
    parser.add_argument('--config', default=None,
                        help='path to a nasal_cfd_config/v1 json; enforces the contract gate '
                             '(refuses to run unless execution_allowed, override with --force-unsanctioned)')
    parser.add_argument('--force-unsanctioned', action='store_true',
                        help='explicitly run an execution_allowed=false config anyway; '
                             'recorded in run_manifest.contract.forced for audit (never lifts engineering_acceptance)')
    parser.add_argument('--engineering-authorization', default=None,
                        help='strictly case-bound, content-fingerprinted engineering allowance; '
                             'requires --config and never grants clinical or numerical acceptance')
    args = parser.parse_args(argv)
    if args.env_check:
        return env_check(build_environment())
    if args.engineering_authorization and not args.config:
        print('run_openfoam_case error: --engineering-authorization requires --config', file=sys.stderr)
        return 3
    # --- contract gate (T-003 R10): evaluate before any step executes ---------
    try:
        contract = evaluate_contract(args)
    except ContractRefusal as ref:
        print("run_openfoam_case error: refusing to run an unsanctioned configuration "
              "(pass --force-unsanctioned to override explicitly, recorded for audit):",
              file=sys.stderr)
        for reason in ref.reasons:
            print("  - " + str(reason), file=sys.stderr)
        return 3
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

    backend_identity = mesh_cache.detect_backend_identity()
    mesh_requested = any(s in MESH_STEPS for s in steps)
    signature = (mesh_cache.mesh_inputs_signature(case, backend_identity)
                 if mesh_requested else {"valid": False, "reason": "no mesh steps requested"})
    skipped_mesh = False
    if args.skip_mesh_if_cached and mesh_requested and signature.get("valid"):
        reuse = mesh_cache.inspect_reuse(case, signature)
        if reuse.get("reusable"):
            steps = [s for s in steps if s not in ("blockMesh", "snappyHexMesh")]
            skipped_mesh = True

    parallel = args.parallel >= 2
    nproc = args.parallel if parallel else 0
    parallel_missing = []
    if parallel:
        # shutil.which has no env parameter: pass the OpenFOAM PATH explicitly so the
        # preflight searches the same directories the solver will use.
        search_path = environment.get("PATH") or os.environ.get("PATH")
        parallel_missing = [t for t in ("mpirun", "decomposePar", "reconstructPar")
                            if not shutil.which(t, path=search_path)]
        if parallel_missing:
            print("run_openfoam_case warning: --parallel requested but missing tools %s; "
                  "falling back to serial" % ", ".join(parallel_missing), file=sys.stderr)
            parallel = False

    if args.dry_run:
        plan = {"schema": "nasal_cfd_dry_run/v1", "case": str(case), "steps": steps,
                "parallel": parallel, "nproc": nproc,
                "parallel_missing_tools": parallel_missing,
                "would_write_decomposeParDict": bool(parallel and not (case / "system" / "decomposeParDict").is_file()),
                "mesh_skipped": skipped_mesh,
                "archive_before_run": bool(args.archive_before_run),
                "signature_valid": bool(signature.get("valid")),
                "signature": signature.get("signature"),
                "signature_reason": signature.get("reason"),
                "commands": []}
        for s in steps:
            for subname, cmd in _effective_sequence(s, commands, parallel, nproc):
                plan["commands"].append({"step": s, "sub_step": subname, "command": cmd})
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    archived = None
    if args.archive_before_run:
        archived = _archive_before_run(case)
    if parallel:
        _ensure_decompose_par_dict(case, nproc)

    status_path = case / args.status_file
    total = _expanded_total(steps, commands, parallel, nproc)
    run_manifest = {"schema": "nasal_cfd_run/v1",
                    "script": {"name": "run_openfoam_case.py", "version": SCRIPT_VERSION},
                    "started_at": utc_now(), "finished_at": None,
                    "case": str(case),
                    "openfoam_version": ENV_OVERRIDES["WM_PROJECT_VERSION"],
                    "environment_overrides": dict(ENV_OVERRIDES),
                    "steps": [], "case_manifest": case_manifest,
                    "execution_status": None,
                    "parallel": parallel, "nproc": nproc,
                    "mesh_signature": signature if signature.get("valid") else None,
                    "mesh_skipped": skipped_mesh,
                    "archived_before_run": archived,
                    "contract": contract}
    run_manifest['engineering_acceptance'] = False
    write_status(status_path, {"schema": "nasal_cfd_run_status/v1", "case": str(case),
                              "started_at": run_manifest["started_at"], "status": "running",
                              "current_step_index": 0, "total_steps": total,
                              "current_command": None, "last_log_tail": None, "updated_at": utc_now()})
    profile_done = False
    mesh_completed = []
    current_command = None
    current_log = None
    try:
        idx = 0
        for step in steps:
            current_command, current_log = None, None
            if step == 'simpleFoam':
                quality = mesh_quality(case)
                run_manifest['mesh_quality'] = quality
                bound_engineering = bool(contract.get('bound_engineering_authorization', {}).get('allowed'))
                run_manifest['failed_mesh_diagnostic_override'] = bool(not quality['passed'] and args.allow_failed_mesh_for_diagnostic)
                run_manifest['failed_mesh_bound_engineering_trial'] = bool(not quality['passed'] and bound_engineering)
                if not quality['passed'] and not args.allow_failed_mesh_for_diagnostic and not bound_engineering:
                    raise RuntimeError('Mesh quality did not pass; refusing to solve (see log.checkMesh)')
            if step == "simpleFoam" and parabolic and not profile_done:
                begin = utc_now()
                record = set_parabolic_inlet(case, case_manifest)
                run_manifest["steps"].append({"command": ["internal:set_parabolic_inlet_profile"],
                                              "exit_code": 0, "started_at": begin,
                                              "finished_at": utc_now(), "patches": record})
                profile_done = True
            for subname, cmd in _effective_sequence(step, commands, parallel, nproc):
                idx += 1
                log_name = "log." + subname
                current_command, current_log = cmd, str(case / log_name)
                tail = None
                if (case / log_name).is_file():
                    tail = "".join((case / log_name).read_text(encoding="utf-8", errors="replace").splitlines()[-8:])
                write_status(status_path, {"schema": "nasal_cfd_run_status/v1", "case": str(case),
                                          "started_at": run_manifest["started_at"], "status": "running",
                                          "current_step_index": idx, "total_steps": total,
                                          "current_command": cmd, "last_log_tail": tail,
                                          "updated_at": utc_now()})
                try:
                    run_manifest["steps"].append(execute(cmd, case, environment, log_name))
                except CommandExecutionError as exc:
                    run_manifest["steps"].append(exc.record)
                    raise
                write_status(status_path, {"schema": "nasal_cfd_run_status/v1", "case": str(case),
                                          "started_at": run_manifest["started_at"], "status": "completed",
                                          "current_step_index": idx, "total_steps": total,
                                          "current_command": cmd, "last_log_tail": tail,
                                          "updated_at": utc_now()})
                # mesh_cache.record_mesh requires the sequence it receives to END with
                # checkMesh. Passing the full step list can never satisfy that (it ends
                # with foamToVTK, or reconstructPar in parallel mode), so freeze the
                # steps completed up to and including checkMesh. Snapshotted here rather
                # than filtered later because parallel reconstruction of simpleFoam also
                # emits reconstructPar, which must not be mistaken for mesh generation.
                if step == "checkMesh":
                    mesh_completed = [{"name": s["command"][0],
                                       "returncode": s.get("exit_code", 0),
                                       "timed_out": False}
                                      for s in run_manifest["steps"]]
        run_manifest["execution_status"] = "completed"
    except Exception as exc:
        run_manifest["execution_status"] = "failed"
        run_manifest["error"] = repr(exc)
        write_status(status_path, {"schema": "nasal_cfd_run_status/v1", "case": str(case),
                                  "started_at": run_manifest["started_at"], "status": "failed",
                                  "current_step_index": idx, "total_steps": total,
                                  "current_command": current_command,
                                  "failed_step": current_command[0] if current_command else None,
                                  "exit_code": exc.record['exit_code'] if isinstance(exc, CommandExecutionError) else None,
                                  "log": current_log,
                                  "last_log_tail": None, "updated_at": utc_now(), "error": repr(exc)})
        raise
    finally:
        run_manifest["finished_at"] = utc_now()
        (case / "run_manifest.json").write_text(
            json.dumps(run_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        final_status = {"schema": "nasal_cfd_run_status/v1", "case": str(case),
                                  "started_at": run_manifest["started_at"],
                                  "status": run_manifest["execution_status"],
                                  "current_step_index": idx, "total_steps": total,
                                  "current_command": None, "last_log_tail": None,
                                  "updated_at": utc_now()}
        if run_manifest['execution_status'] == 'failed':
            final_status.update(current_command=current_command,
                                failed_step=current_command[0] if current_command else None,
                                log=current_log, error=run_manifest.get('error'))
            if run_manifest['steps'] and run_manifest['steps'][-1]['command'] == current_command:
                final_status['exit_code'] = run_manifest['steps'][-1].get('exit_code')
        write_status(status_path, final_status)
    # Record a mesh cache entry only after a complete, checked mesh this run.
    if mesh_requested and run_manifest["execution_status"] == "completed":
        # mesh_completed freezes the step list at checkMesh; fall back to the mesh steps
        # only so a caller that skipped checkMesh still gets a coherent (and rejected)
        # sequence rather than one ending in foamToVTK.
        completed = mesh_completed or [{"name": s["command"][0],
                                        "returncode": s.get("exit_code", 0), "timed_out": False}
                                       for s in run_manifest["steps"]
                                       if s["command"][0] in mesh_cache.MESH_STEPS]
        check_log = case / "log.checkMesh"
        if check_log.is_file():
            output = check_log.read_text(encoding="utf-8", errors="replace")
            rec = mesh_cache.record_mesh(
                case, signature, run_manifest.get("started_at") or utc_now(),
                check_result={"returncode": 0, "output": output, "timed_out": False},
                completed_steps=completed,
                generation={"mode": "parallel" if parallel else "serial", "nproc": nproc})
            run_manifest["mesh_cache"] = rec
            (case / "run_manifest.json").write_text(
                json.dumps(run_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"case": str(case), "execution_status": run_manifest["execution_status"],
                      "steps": [s["command"][0] for s in run_manifest["steps"]],
                      "mesh_skipped": skipped_mesh, "parallel": parallel}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
