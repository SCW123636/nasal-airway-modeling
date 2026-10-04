"""Map the published NasalSeg label ids to named binary masks.

The published dataset contains five annotated structures. This step creates
those five masks on the already validated CT grid and records the three
project labels that the dataset does not contain. It never invents missing
anatomy or changes the source multi-class labelmap.
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

from import_nasalseg import read_image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = ROOT / "work" / "10_nasalseg_intake" / "cases"
DEFAULT_OUTPUT = ROOT / "work" / "10_nasalseg_intake" / "nasalseg_semantic_manifest.json"

SOURCE_ARTICLE = {
    "title": "NasalSeg: A Dataset for Automatic Segmentation of Nasal Cavity and Paranasal Sinuses from 3D CT Images",
    "doi": "10.1038/s41597-024-04176-1",
    "url": "https://www.nature.com/articles/s41597-024-04176-1",
    "zenodo": "https://zenodo.org/records/13893419",
    "evidence": "Data Records: labels 0 to 5 and Table 2",
}

LABEL_MAP = {
    1: {"source_name": "right_maxillary_sinus", "output_name": "maxillary_sinus_right"},
    2: {"source_name": "left_maxillary_sinus", "output_name": "maxillary_sinus_left"},
    3: {"source_name": "right_nasal_cavity", "output_name": "nasal_cavity_right"},
    4: {"source_name": "left_nasal_cavity", "output_name": "nasal_cavity_left"},
    5: {"source_name": "nasopharynx", "output_name": "nasopharynx"},
}
MISSING_PROJECT_LABELS = ["oropharynx", "hard_palate", "soft_palate"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def same_geometry(a: sitk.Image, b: sitk.Image, tolerance: float = 1e-5) -> bool:
    return (
        a.GetSize() == b.GetSize()
        and all(abs(x - y) <= tolerance for x, y in zip(a.GetSpacing(), b.GetSpacing()))
        and all(abs(x - y) <= tolerance for x, y in zip(a.GetOrigin(), b.GetOrigin()))
        and all(abs(x - y) <= tolerance for x, y in zip(a.GetDirection(), b.GetDirection()))
    )


def write_image(path: Path, image: sitk.Image) -> None:
    """Write through an ASCII temporary path for SimpleITK on Windows."""
    if all(ord(char) < 128 for char in str(path)):
        sitk.WriteImage(image, str(path), useCompression=True)
        return
    with tempfile.TemporaryDirectory(prefix="nasalseg_write_") as temp_dir:
        staged = Path(temp_dir) / path.name
        sitk.WriteImage(image, str(staged), useCompression=True)
        shutil.copyfile(staged, path)


def map_case(case_dir: Path) -> dict:
    case = case_dir.name
    ct_path = case_dir / "ct.nii.gz"
    label_path = case_dir / "masks" / "nasalseg_labelmap.nii.gz"
    if not ct_path.is_file() or not label_path.is_file():
        raise FileNotFoundError(f"{case}: validated CT or source labelmap is missing")
    ct = read_image(ct_path)
    label = read_image(label_path)
    if not same_geometry(ct, label):
        raise ValueError(f"{case}: CT and source labelmap geometry differ")
    label_array = sitk.GetArrayFromImage(label)
    values = {int(value) for value in np.unique(label_array)}
    if values != set(range(6)):
        raise ValueError(f"{case}: expected source label values 0..5, got {sorted(values)}")

    outputs = {}
    mask_dir = case_dir / "masks"
    for value, spec in LABEL_MAP.items():
        output_path = mask_dir / f"{spec['output_name']}.nii.gz"
        mask = sitk.Cast(label == value, sitk.sitkUInt8)
        write_image(output_path, mask)
        if not same_geometry(ct, read_image(output_path)):
            raise ValueError(f"{case}: generated mask geometry differs for {spec['output_name']}")
        outputs[spec["output_name"]] = {
            "source_label_id": value,
            "source_name": spec["source_name"],
            "path": str(output_path.resolve()),
            "sha256": sha256(output_path),
            "voxels": int(np.count_nonzero(label_array == value)),
        }

    manifest_path = case_dir / "case_manifest.json"
    case_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case_manifest["status"] = "needs_semantic_mapping"
    case_manifest["cfd_eligible"] = False
    case_manifest["semantic_mapping"] = {
        "status": "verified_partial_project_mapping",
        "source": SOURCE_ARTICLE,
        "label_id_to_structure": {str(value): spec["source_name"] for value, spec in LABEL_MAP.items()},
        "project_masks": outputs,
        "missing_project_labels": MISSING_PROJECT_LABELS,
        "mapping_does_not_claim_medical_accuracy": True,
    }
    case_manifest["downstream"] = {
        "landmark_pipeline": "blocked_until_oropharynx_hard_palate_soft_palate",
        "geometry": "blocked_until_project_label_completion_and_boundary_review",
        "cfd": "blocked",
    }
    manifest_path.write_text(json.dumps(case_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"case": case, "status": "pass", "project_masks": outputs,
            "missing_project_labels": MISSING_PROJECT_LABELS}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--patients", nargs="+", default=None)
    args = parser.parse_args()

    patients = args.patients or sorted(path.name for path in args.cases.iterdir()
                                       if path.is_dir() and path.name.startswith("P"))
    results = []
    failures = []
    for patient in patients:
        try:
            result = map_case(args.cases / patient)
            results.append(result)
            print(f"{patient}: mapped 5 published structures; 3 project labels remain missing", flush=True)
        except Exception as exc:
            failures.append({"case": patient, "status": "fail", "error": str(exc)})
            print(f"{patient}: FAILED: {exc}", file=sys.stderr, flush=True)

    manifest = {
        "schema": "nasalseg_semantic_mapping/v1",
        "source_article": SOURCE_ARTICLE,
        "label_id_to_structure": {str(value): spec["source_name"] for value, spec in LABEL_MAP.items()},
        "project_mask_names": sorted({spec["output_name"] for spec in LABEL_MAP.values()}),
        "missing_project_labels": MISSING_PROJECT_LABELS,
        "cases": results,
        "failures": failures,
        "case_count": len(results),
        "mapped_cases": sum(result["status"] == "pass" for result in results),
        "overall_status": "partial_project_mapping" if not failures else "mapping_failed",
        "project_cfd_eligible_cases": 0,
        "next_action": "Provide or annotate oropharynx, hard_palate and soft_palate masks, then rerun S03 QC.",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"overall_status": manifest["overall_status"], "cases": len(results),
                      "mapped": manifest["mapped_cases"], "failed": len(failures)}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
