"""Complete the three missing project masks with TotalSegmentator.

The public NasalSeg labels remain untouched. TotalSegmentator outputs are
staged in an ASCII workspace, geometry-checked against the staged CT, then
copied into each case as supplemental, unvalidated project references.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import SimpleITK as sitk


ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "work" / "10_nasalseg_intake" / "cases"
STAGE = Path(r"C:\ts_work\nasalseg_completion")
PYTHON = Path(r"C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Scripts\python.exe")
TS_EXE = PYTHON.parent / "TotalSegmentator.exe"
TASK = "head_glands_cavities"
LABELS = ("oropharynx", "hard_palate", "soft_palate")
SOURCE_NOTE = {
    "tool": "TotalSegmentator",
    "version": "2.18.0",
    "task": TASK,
    "labels": list(LABELS),
    "command_template": "TotalSegmentator -i <staged_ct> -o <staged_masks> -ta head_glands_cavities -d cpu",
    "interpretation": "supplemental semantic references; not physician-validated and not a CFD boundary",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def geometry(image: sitk.Image) -> dict:
    return {
        "size_xyz": list(image.GetSize()),
        "spacing_xyz_mm": list(image.GetSpacing()),
        "origin_xyz_mm": list(image.GetOrigin()),
        "direction": list(image.GetDirection()),
    }


def same_geometry(a: sitk.Image, b: sitk.Image, tolerance: float = 1e-5) -> bool:
    return (
        a.GetSize() == b.GetSize()
        and all(abs(x - y) <= tolerance for x, y in zip(a.GetSpacing(), b.GetSpacing()))
        and all(abs(x - y) <= tolerance for x, y in zip(a.GetOrigin(), b.GetOrigin()))
        and all(abs(x - y) <= tolerance for x, y in zip(a.GetDirection(), b.GetDirection()))
    )


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                    prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temp = Path(stream.name)
    os.replace(temp, path)


def update_case_manifest(case_dir: Path, supplemental: dict) -> None:
    path = case_dir / "case_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    semantic = manifest.setdefault("semantic_mapping", {})
    semantic["supplemental_masks"] = supplemental
    semantic["missing_project_labels"] = []
    semantic["status"] = "supplemental_project_label_completion_unvalidated"
    semantic["mapping_does_not_claim_medical_accuracy"] = True
    manifest["status"] = "supplemental_project_label_completion_unvalidated"
    manifest["downstream"] = {
        "landmark_pipeline": "available_for_provisional_qc; blocked_until_manual_review",
        "geometry": "blocked_until_boundary_review_and_mesh_gates",
        "cfd": "blocked",
    }
    atomic_json(path, manifest)


def run_one(case: str, device: str) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    case_dir = CASES / case
    stage_dir = STAGE / "cases" / case
    stage_masks = stage_dir / "masks"
    project_masks = case_dir / "masks"
    completion_path = case_dir / "ts_completion.json"
    required_project = [project_masks / f"{name}.nii.gz" for name in LABELS]

    if completion_path.is_file() and all(path.is_file() for path in required_project):
        try:
            prior = json.loads(completion_path.read_text(encoding="utf-8"))
            if prior.get("status") == "pass" and all(
                prior.get("masks", {}).get(name, {}).get("sha256") == sha256(path)
                for name, path in zip(LABELS, required_project)
            ):
                return {"case": case, "status": "skipped_existing", "completion": str(completion_path)}
        except (OSError, ValueError, KeyError):
            pass

    stage_dir.mkdir(parents=True, exist_ok=True)
    stage_masks.mkdir(parents=True, exist_ok=True)
    staged_ct = stage_dir / "ct.nii.gz"
    source_ct = case_dir / "ct.nii.gz"
    shutil.copy2(source_ct, staged_ct)
    command = [str(TS_EXE), "-i", str(staged_ct), "-o", str(stage_masks),
               "-ta", TASK, "-d", device]
    log_path = stage_dir / "ts_run.log"
    env = os.environ.copy()
    env.update({
        "HF_ENDPOINT": "https://hf-mirror.com",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTHONIOENCODING": "utf-8",
        "OMP_NUM_THREADS": "4",
        "MKL_NUM_THREADS": "4",
    })
    with log_path.open("w", encoding="utf-8") as log:
        log.write("CMD: " + " ".join(command) + "\n")
        log.write("SOURCE_CASE: " + str(case_dir.resolve()) + "\n")
        log.flush()
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                 env=env, timeout=7200, check=False)

    result = {
        "case": case,
        "status": "fail",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_case": str(case_dir.resolve()),
        "staged_ct": str(staged_ct),
        "staged_mask_dir": str(stage_masks),
        "log": str(log_path),
        "command": command,
        "returncode": process.returncode,
        "tool": SOURCE_NOTE,
        "masks": {},
        "errors": [],
    }
    if process.returncode != 0:
        result["errors"].append("TotalSegmentator returned non-zero exit code")
        atomic_json(completion_path, result)
        return result

    try:
        ct = sitk.ReadImage(str(staged_ct))
        for name in LABELS:
            staged_mask = stage_masks / f"{name}.nii.gz"
            if not staged_mask.is_file():
                raise FileNotFoundError(f"missing output: {staged_mask.name}")
            mask = sitk.ReadImage(str(staged_mask))
            if not same_geometry(ct, mask):
                raise ValueError(f"geometry mismatch: {name}")
            target = project_masks / staged_mask.name
            shutil.copy2(staged_mask, target)
            result["masks"][name] = {
                "path": str(target.resolve()),
                "sha256": sha256(target),
                "staged_sha256": sha256(staged_mask),
                "voxels": int(sitk.GetArrayFromImage(mask).astype(bool).sum()),
                "geometry": geometry(mask),
            }
        update_case_manifest(case_dir, result["masks"])
        result["status"] = "pass"
    except Exception as exc:
        result["errors"].append(str(exc))
    atomic_json(completion_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    global STAGE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patients", nargs="+", default=None)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--stage", type=Path, default=STAGE)
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    STAGE = args.stage
    patients = args.patients or sorted(
        path.name for path in CASES.iterdir() if path.is_dir() and path.name.startswith("P")
    )
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, case, args.device): case for case in patients}
        for future in as_completed(futures):
            case = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"case": case, "status": "fail", "errors": [repr(exc)]}
            results.append(result)
            print(f"{case}: {result['status']}", flush=True)
    results.sort(key=lambda item: item["case"])
    summary = {
        "schema": "nasalseg_ts_completion/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tool": SOURCE_NOTE,
        "workers": args.workers,
        "device": args.device,
        "cases": results,
        "passed": sum(item["status"] in ("pass", "skipped_existing") for item in results),
        "failed": sum(item["status"] == "fail" for item in results),
    }
    atomic_json(STAGE / "nasalseg_ts_completion_manifest.json", summary)
    print(json.dumps({"passed": summary["passed"], "failed": summary["failed"]}, ensure_ascii=False))
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
