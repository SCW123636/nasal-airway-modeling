"""Register NasalSeg cases without treating unknown class ids as project anatomy labels.

The bridge preserves the NRRD geometry and writes compressed NIfTI copies that
existing project tooling can inspect. Semantic class mapping remains an explicit
review gate, so these cases are not made CFD-ready by this import.
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


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "NasalSeg_按患者"
DEFAULT_OUTPUT = ROOT / "work" / "10_nasalseg_intake" / "cases"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    """Resolve junction aliases before writing provenance paths."""
    return str(path.resolve())


def read_image(path: Path) -> sitk.Image:
    """Read NRRD reliably when the native reader cannot handle Unicode paths."""
    try:
        return sitk.ReadImage(str(path))
    except RuntimeError:
        if all(ord(char) < 128 for char in str(path)):
            raise
        with tempfile.TemporaryDirectory(prefix="nasalseg_read_") as temp_dir:
            staged = Path(temp_dir) / path.name
            shutil.copyfile(path, staged)
            return sitk.ReadImage(str(staged))


def image_info(path: Path) -> tuple[sitk.Image, dict]:
    image = read_image(path)
    if image.GetDimension() != 3:
        raise ValueError(f"{path.name}: expected 3D image, got dimension {image.GetDimension()}")
    array = sitk.GetArrayViewFromImage(image)
    return image, {
        "size_xyz": list(image.GetSize()),
        "spacing_xyz_mm": [float(x) for x in image.GetSpacing()],
        "origin_xyz_mm": [float(x) for x in image.GetOrigin()],
        "direction_lps": [float(x) for x in image.GetDirection()],
        "dtype": str(array.dtype),
    }


def geometry_delta(image: sitk.Image, label: sitk.Image) -> dict:
    return {
        "spacing_max_abs_mm": max(abs(float(a) - float(b)) for a, b in zip(image.GetSpacing(), label.GetSpacing())),
        "origin_max_abs_mm": max(abs(float(a) - float(b)) for a, b in zip(image.GetOrigin(), label.GetOrigin())),
        "direction_max_abs": max(abs(float(a) - float(b)) for a, b in zip(image.GetDirection(), label.GetDirection())),
    }


def export_case(patient: str, source_root: Path, output_root: Path) -> dict:
    patient_dir = source_root / patient
    image_path = patient_dir / f"{patient}_img.nrrd"
    label_path = patient_dir / f"{patient}_seg.nrrd"
    if not image_path.is_file() or not label_path.is_file():
        raise FileNotFoundError(f"{patient}: image/label pair is incomplete")

    image, image_meta = image_info(image_path)
    label, label_meta = image_info(label_path)
    if image.GetSize() != label.GetSize():
        raise ValueError(f"{patient}: image and label sizes differ")

    label_array = sitk.GetArrayViewFromImage(label)
    image_array = sitk.GetArrayViewFromImage(image)
    values, counts = np.unique(label_array, return_counts=True)
    delta = geometry_delta(image, label)
    exact_geometry = (
        delta["spacing_max_abs_mm"] <= 1e-6
        and delta["origin_max_abs_mm"] <= 1e-6
        and delta["direction_max_abs"] <= 1e-6
    )
    geometry_reconciliation = {"status": "exact", "delta": delta}
    if not exact_geometry:
        foreground = label_array != 0
        if not np.any(foreground):
            raise ValueError(f"{patient}: label is empty; cannot reconcile geometry")
        low_hu_fraction = float(np.mean(image_array[foreground] < -300))
        # NasalSeg's label array is index-aligned with the CT in the affected
        # cases, while a subset of NRRD headers carries a bad z direction/origin.
        # Repair only when the same-index foreground is overwhelmingly air-like.
        if low_hu_fraction < 0.90:
            raise ValueError(
                f"{patient}: image/label geometry differs and index-alignment evidence is weak "
                f"(foreground HU<-300 fraction={low_hu_fraction:.3f})"
            )
        geometry_reconciliation = {
            "status": "repaired_from_image_geometry",
            "delta": delta,
            "evidence": {
                "same_index_foreground_hu_lt_minus300_fraction": low_hu_fraction,
                "threshold": 0.90,
                "source_label_geometry_preserved_in_manifest": True,
            },
        }
        label = sitk.Image(label)
        label.SetSpacing(image.GetSpacing())
        label.SetOrigin(image.GetOrigin())
        label.SetDirection(image.GetDirection())
    case_dir = output_root / patient
    mask_dir = case_dir / "masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    ct_out = case_dir / "ct.nii.gz"
    label_out = mask_dir / "nasalseg_labelmap.nii.gz"
    sitk.WriteImage(image, str(ct_out), useCompression=True)
    sitk.WriteImage(label, str(label_out), useCompression=True)

    return {
        "case": patient,
        "status": "needs_semantic_mapping",
        "cfd_eligible": False,
        "source": {
            "image_nrrd": display_path(image_path),
            "label_nrrd": display_path(label_path),
            "image_sha256": sha256(image_path),
            "label_sha256": sha256(label_path),
        },
        "converted": {
            "ct_nifti": display_path(ct_out),
            "labelmap_nifti": display_path(label_out),
            "ct_sha256": sha256(ct_out),
            "labelmap_sha256": sha256(label_out),
        },
        "geometry": image_meta,
        "label_geometry": label_meta,
        "geometry_reconciliation": geometry_reconciliation,
        "label_values": {str(int(value)): int(count) for value, count in zip(values, counts)},
        "semantic_mapping": {
            "status": "unknown",
            "source_label_name": f"{patient}_seg.nrrd",
            "mapping": None,
            "reason": "NasalSeg label ids are present, but class names were not assumed from numeric values.",
        },
        "downstream": {
            "landmark_pipeline": "blocked_until_six_project_label_masks_are_mapped",
            "geometry": "blocked_until_semantic_mapping_and_boundary_review",
            "cfd": "blocked",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Batch manifest path; set this explicitly when --output is a junction.",
    )
    parser.add_argument("--patients", nargs="+", default=None)
    args = parser.parse_args()

    patients = args.patients or sorted(p.name for p in args.source.iterdir() if p.is_dir() and p.name.startswith("P"))
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []
    for patient in patients:
        try:
            record = export_case(patient, args.source, args.output)
            (args.output / patient / "case_manifest.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            records.append(record)
            print(f"{patient}: imported; semantic mapping required", flush=True)
        except Exception as exc:  # keep a complete batch receipt without hiding failures
            failures.append({"case": patient, "status": "failed", "error": str(exc)})
            print(f"{patient}: FAILED: {exc}", file=sys.stderr, flush=True)

    batch = {
        "schema": "nasalseg_intake/v1",
        "source_root": display_path(args.source),
        "output_root": display_path(args.output),
        "cases": records,
        "failures": failures,
        "software": {"python": sys.version, "SimpleITK": sitk.Version_VersionString()},
        "policy": {
            "coordinate_system": "LPS",
            "unit": "mm",
            "semantic_mapping_required": True,
            "medical_or_cfd_validation_pass": False,
        },
    }
    manifest_path = args.manifest or (args.output.parent / "nasalseg_intake_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"imported": len(records), "failed": len(failures)}, ensure_ascii=False))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
