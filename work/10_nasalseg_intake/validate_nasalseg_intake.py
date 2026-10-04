"""Validate the NasalSeg import and emit the project pipeline bridge receipt.

The check compares source NRRD arrays with the converted NIfTI arrays, checks
physical geometry and recorded hashes, and keeps semantic mapping as an
explicit gate. It does not infer anatomy from numeric label ids.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import SimpleITK as sitk


PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT / "NasalSeg_按患者"
DEFAULT_OUTPUT = PROJECT / "work" / "10_nasalseg_intake" / "cases"
DEFAULT_BATCH = PROJECT / "work" / "10_nasalseg_intake" / "nasalseg_intake_manifest.json"
DEFAULT_VALIDATION = PROJECT / "work" / "10_nasalseg_intake" / "nasalseg_validation_report.json"
DEFAULT_BRIDGE = PROJECT / "work" / "10_nasalseg_intake" / "nasalseg_pipeline_bridge.json"
DEFAULT_SEMANTIC = PROJECT / "work" / "10_nasalseg_intake" / "nasalseg_semantic_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def float_list(image: sitk.Image, getter: str) -> list[float]:
    return [float(value) for value in getattr(image, getter)()]


def geometry_delta(image: sitk.Image, other: sitk.Image) -> dict[str, float]:
    return {
        "spacing_max_abs_mm": max(abs(a - b) for a, b in zip(image.GetSpacing(), other.GetSpacing())),
        "origin_max_abs_mm": max(abs(a - b) for a, b in zip(image.GetOrigin(), other.GetOrigin())),
        "direction_max_abs": max(abs(a - b) for a, b in zip(image.GetDirection(), other.GetDirection())),
    }


def geometry_matches(image: sitk.Image, other: sitk.Image, tolerance: float = 1e-5) -> bool:
    delta = geometry_delta(image, other)
    return all(value <= tolerance for value in delta.values()) and image.GetSize() == other.GetSize()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_image(path: Path) -> sitk.Image:
    """Read source NRRD even when SimpleITK truncates Unicode Windows paths."""
    try:
        return sitk.ReadImage(str(path))
    except RuntimeError:
        if all(ord(char) < 128 for char in str(path)):
            raise
        with tempfile.TemporaryDirectory(prefix="nasalseg_read_") as temp_dir:
            staged = Path(temp_dir) / path.name
            shutil.copyfile(path, staged)
            return sitk.ReadImage(str(staged))


def validate_case(case: str, source_root: Path, output_root: Path, record: dict) -> dict:
    failures: list[str] = []
    warnings: list[str] = []
    source_image = source_root / case / f"{case}_img.nrrd"
    source_label = source_root / case / f"{case}_seg.nrrd"
    output_case = output_root / case
    output_image = output_case / "ct.nii.gz"
    output_label = output_case / "masks" / "nasalseg_labelmap.nii.gz"
    for path in (source_image, source_label, output_image, output_label):
        if not path.is_file():
            failures.append(f"missing file: {path}")
    if failures:
        return {"case": case, "status": "fail", "failures": failures, "warnings": warnings}

    try:
        src_ct = read_image(source_image)
        src_label = read_image(source_label)
        out_ct = read_image(output_image)
        out_label = read_image(output_label)
    except Exception as exc:
        return {"case": case, "status": "fail", "failures": [f"read failed: {exc}"], "warnings": warnings}

    src_ct_array = sitk.GetArrayFromImage(src_ct)
    src_label_array = sitk.GetArrayFromImage(src_label)
    out_ct_array = sitk.GetArrayFromImage(out_ct)
    out_label_array = sitk.GetArrayFromImage(out_label)
    if src_ct_array.shape != src_label_array.shape:
        failures.append("source image/label array shapes differ")
    if out_ct_array.shape != out_label_array.shape:
        failures.append("converted CT/label array shapes differ")
    if not np.array_equal(src_ct_array, out_ct_array):
        failures.append("converted CT voxel array differs from source")
    if not np.array_equal(src_label_array, out_label_array):
        failures.append("converted label voxel array differs from source")
    if not geometry_matches(src_ct, out_ct):
        failures.append("converted CT physical geometry differs from source CT")
    if not geometry_matches(out_ct, out_label):
        failures.append("converted CT and label physical geometry differ")

    values = np.unique(src_label_array)
    expected_values = np.arange(6, dtype=values.dtype)
    if not np.array_equal(values, expected_values):
        failures.append(f"unexpected source label values: {values.tolist()}")
    if not np.isfinite(src_ct_array).all():
        failures.append("source CT contains non-finite values")
    if float(src_ct_array.min()) >= -300 or float(src_ct_array.max()) <= 100:
        warnings.append("CT intensity range should be reviewed as HU before segmentation")

    recorded = record.get("geometry_reconciliation", {})
    if recorded.get("status") == "repaired_from_image_geometry":
        foreground = src_label_array != 0
        air_fraction = float(np.mean(src_ct_array[foreground] < -300)) if foreground.any() else 0.0
        if air_fraction < 0.90:
            failures.append(f"recorded geometry repair lacks same-index air evidence: {air_fraction:.4f}")
    elif recorded.get("status") != "exact":
        failures.append("unknown geometry reconciliation status")

    expected_hashes = {
        source_image: record.get("source", {}).get("image_sha256"),
        source_label: record.get("source", {}).get("label_sha256"),
        output_image: record.get("converted", {}).get("ct_sha256"),
        output_label: record.get("converted", {}).get("labelmap_sha256"),
    }
    for path, expected in expected_hashes.items():
        if not expected or sha256(path) != expected:
            failures.append(f"hash mismatch: {path.name}")

    if record.get("status") != "needs_semantic_mapping":
        failures.append("case status is not needs_semantic_mapping")
    if record.get("cfd_eligible") is not False:
        failures.append("case is incorrectly marked CFD eligible")
    mapping = record.get("semantic_mapping", {})
    if mapping.get("status") != "unknown" or mapping.get("mapping") is not None:
        failures.append("semantic mapping gate was changed without an explicit reviewed mapping")
    return {
        "case": case,
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "warnings": warnings,
        "size_xyz": list(out_ct.GetSize()),
        "spacing_xyz_mm": float_list(out_ct, "GetSpacing"),
        "label_values": [int(value) for value in values],
        "geometry_reconciliation": recorded.get("status"),
        "arrays_equal_to_source": not failures or not any("array" in item for item in failures),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-manifest", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--semantic-manifest", type=Path, default=DEFAULT_SEMANTIC)
    args = parser.parse_args()

    batch = load_json(args.batch_manifest)
    records = {entry["case"]: entry for entry in batch.get("cases", [])}
    case_names = sorted(path.name for path in args.output.iterdir() if path.is_dir() and path.name.startswith("P"))
    failures = []
    results = []
    for case in case_names:
        if case not in records:
            result = {"case": case, "status": "fail", "failures": ["case absent from batch manifest"], "warnings": []}
        else:
            result = validate_case(case, args.source, args.output, records[case])
        results.append(result)
        failures.extend(result.get("failures", []))
    missing = sorted(set(records) - set(case_names))
    for case in missing:
        failures.append(f"manifest case has no output directory: {case}")
    if batch.get("failures"):
        failures.append(f"batch manifest contains {len(batch['failures'])} import failures")

    passed = sum(result["status"] == "pass" for result in results)
    repaired = sum(result.get("geometry_reconciliation") == "repaired_from_image_geometry" for result in results)
    semantic_manifest = load_json(args.semantic_manifest) if args.semantic_manifest.is_file() else None
    semantic_status = (semantic_manifest or {}).get("overall_status", "not_run")
    report = {
        "schema": "nasalseg_intake_validation/v1",
        "source_root": str(args.source.resolve()),
        "output_root": str(args.output.resolve()),
        "batch_manifest": str(args.batch_manifest.resolve()),
        "case_count": len(case_names),
        "passed_cases": passed,
        "failed_cases": len(results) - passed,
        "geometry_repairs": repaired,
        "batch_failures": len(batch.get("failures", [])),
        "overall_status": "pass" if not failures and len(case_names) == 130 else "fail",
        "semantic_mapping_status": semantic_status,
        "semantic_mapping_manifest": str(args.semantic_manifest.resolve()) if semantic_manifest else None,
        "medical_or_cfd_validation_pass": False,
        "cases": results,
        "failures": failures,
        "acceptance": {
            "source_and_converted_arrays_equal": True,
            "converted_ct_and_label_geometry_match": True,
            "label_values_exactly_0_to_5": True,
            "numeric_ids_not_mapped_to_project_anatomy": True,
        },
    }
    args.validation.parent.mkdir(parents=True, exist_ok=True)
    args.validation.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    partial_mapping = semantic_status == "partial_project_mapping"
    bridge = {
        "schema": "nasalseg_pipeline_bridge/v1",
        "dataset": "NasalSeg",
        "source_record": "https://zenodo.org/records/13893419",
        "validation_report": str(args.validation.resolve()),
        "validation_summary": {
            "case_count": report["case_count"],
            "passed_cases": report["passed_cases"],
            "failed_cases": report["failed_cases"],
            "geometry_repairs": report["geometry_repairs"],
            "semantic_mapping_status": report["semantic_mapping_status"],
        },
        "semantic_mapping_manifest": str(args.semantic_manifest.resolve()) if semantic_manifest else None,
        "input_contract": {
            "coordinate_system": "LPS",
            "unit": "mm",
            "ct": "ct.nii.gz",
            "source_labelmap": "masks/nasalseg_labelmap.nii.gz",
            "source_label_values": [0, 1, 2, 3, 4, 5],
        },
        "project_label_contract": [
            "nasal_cavity_left", "nasal_cavity_right", "nasopharynx",
            "oropharynx", "hard_palate", "soft_palate",
        ],
        "stages": {
            "S01_input_identity_and_case_freeze": {
                "status": "verified", "evidence": "source/output hashes and per-case manifests"
            },
            "S02_ct_import_and_physical_space": {
                "status": "verified", "evidence": "array-preserving NRRD to NIfTI conversion and LPS/mm geometry"
            },
            "S03_segmentation_and_qc": {
                "status": "partial_verified_missing_project_labels" if partial_mapping else "needs_semantic_mapping",
                "evidence": (
                    "published label ids mapped to five named structures; oropharynx, hard_palate and soft_palate are absent"
                    if partial_mapping else
                    "multi-class labelmap imported; numeric ids have no assumed anatomy"
                ),
                "geometry_repairs": repaired,
                "semantic_mapping_status": semantic_status,
            },
            "S04_coarse_localization": {"status": "blocked", "reason": "three project semantic masks are missing" if partial_mapping else "project semantic masks are not available"},
            "S05_landmark_review": {"status": "blocked", "reason": "three project semantic masks are missing" if partial_mapping else "project semantic masks are not available"},
            "S06_boundary_review_and_preview": {"status": "blocked", "reason": "project semantic masks and reviewed boundaries are not available"},
            "S07_geometry_mesh": {"status": "blocked", "reason": "semantic mapping and boundary review required"},
            "S08_non_patient_cfd_validation": {"status": "independent", "note": "does not authorize patient cases"},
            "S09_patient_cfd_and_batch": {"status": "blocked", "reason": "semantic mapping, review, geometry and mesh gates required"},
        },
        "overall_status": "needs_project_label_completion" if partial_mapping and report["overall_status"] == "pass" else ("needs_semantic_mapping" if report["overall_status"] == "pass" else "intake_validation_failed"),
        "cfd_eligible_cases": 0,
        "next_action": ("Provide or annotate oropharynx, hard_palate and soft_palate masks, then rerun S03 QC."
                        if partial_mapping else
                        "Obtain authoritative NasalSeg class names or annotate a mapping review, then produce six project masks and rerun S03 QC."),
    }
    args.bridge.write_text(json.dumps(bridge, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"overall_status": report["overall_status"], "cases": len(case_names), "passed": passed,
                      "failed": len(results) - passed, "geometry_repairs": repaired}, ensure_ascii=False))
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
