"""Read actual T-026 candidates and compare every voxel to original CT/labels.

No import of T-026 code; metadata/extent routines reuse the T-027 input audit.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys

for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"):
    os.environ[key] = "1"
import numpy as np
import SimpleITK as sitk
sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)

spec = importlib.util.spec_from_file_location("t027_input_audit", Path(__file__).with_name("independent_input_audit.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read(path):
    # ITK receives an ASCII basename; this Unicode-cwd workaround only changes
    # this review process, and never writes the input image.
    path = Path(path).resolve()
    before = Path.cwd()
    try:
        os.chdir(path.parent)
        return sitk.ReadImage(path.name)
    finally:
        os.chdir(before)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--input-root", type=Path, default=Path(r"C:\ts_work"))
    parser.add_argument("--author-run", type=Path, required=True)
    parser.add_argument("--initial-audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    author_run = args.author_run.resolve()
    initial = {item["case"]: item for item in load(args.initial_audit)}
    checks = []

    def check(name, actual, expected):
        passed = actual == expected
        checks.append({"name": name, "pass": passed, "actual": actual, "expected": expected})
        print(json.dumps(checks[-1], ensure_ascii=False), flush=True)

    # Independently bind all before/after author input fingerprints to our
    # separate original audit, then re-hash actual source files now.
    fingerprints_before = load(author_run / "input_fingerprints_before.json")
    fingerprints_after = load(author_run / "input_fingerprints_after.json")
    check("author_before_after_input_manifests_equal", fingerprints_before, fingerprints_after)
    for entry in fingerprints_before:
        source = Path(entry["path"])
        case = source.parent.name if source.name == "ct.nii.gz" else source.parent.parent.name
        if case not in initial:
            continue
        if source.name == "ct.nii.gz":
            own_entry = initial[case]["ct"]
        else:
            name = source.name.removesuffix(".nii.gz")
            own_entry = initial[case]["labels"].get(name, {})
        actual = {"exists": source.is_file(), "sha256": audit.digest(source) if source.is_file() else None,
                  "bytes": source.stat().st_size if source.is_file() else None}
        expected = {"exists": entry["exists"], "sha256": entry["sha256"], "bytes": entry["bytes"]}
        check("actual_input_fingerprint_" + case + "_" + source.name, actual, expected)
        check("own_initial_input_identity_" + case + "_" + source.name, actual["sha256"], own_entry.get("sha256"))
    ct = read(args.input_root / args.case / "ct.nii.gz")
    ct_array = sitk.GetArrayViewFromImage(ct)
    positive = {}
    for name in ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx", "oropharynx"):
        label = read(args.input_root / args.case / "masks" / (name + ".nii.gz"))
        check("source_grid_" + name, all(audit.matches(ct, label).values()), True)
        positive[name] = sitk.GetArrayFromImage(label) == 1
    baseline_semantic = positive["nasal_cavity_left"] | positive["nasal_cavity_right"] | positive["nasopharynx"]
    expected_base = baseline_semantic & (ct_array < -300)
    expected_extended = (baseline_semantic | positive["oropharynx"]) & (ct_array < -300)
    expected_added = expected_extended & ~expected_base
    author_report = load(author_run / (args.case + "_candidate_report.json"))
    candidate_masks = {}
    independent = {}
    for profile, expected in (("nasal_original", expected_base), ("nasal_oropharynx", expected_extended)):
        claimed = author_report["profiles"][profile]
        check("generated_" + profile, claimed["generated"], True)
        candidate_path = Path(claimed["path"])
        im = read(candidate_path)
        arr = sitk.GetArrayViewFromImage(im)
        mask = arr > 0
        candidate_masks[profile] = mask.copy()
        check("candidate_binary_" + profile, bool(np.all((arr == 0) | (arr == 1))), True)
        check("candidate_grid_" + profile, all(audit.matches(ct, im).values()), True)
        check("candidate_sha256_" + profile, audit.digest(candidate_path), claimed["sha256"])
        check("every_voxel_exact_" + profile, int(np.count_nonzero(mask != expected)), 0)
        own = audit.foreground_summary(mask, ct)
        independent[profile] = own
        check("claimed_voxels_" + profile, own["nonzero_voxels"], claimed["voxels"])
        check("claimed_mm3_" + profile, bool(np.isclose(own["volume_mm3"], claimed["volume_mm3"], rtol=0, atol=1e-8)), True)
        check("claimed_centre_bounds_" + profile, bool(np.allclose([own["centre_min_lps_mm"], own["centre_max_lps_mm"]], claimed["center_bounds_LPS_mm"], rtol=0, atol=1e-8)), True)
        check("claimed_support_bounds_" + profile, bool(np.allclose([own["support_min_lps_mm"], own["support_max_lps_mm"]], claimed["bounds_LPS_mm"], rtol=0, atol=1e-8)), True)
        faces = own["face_voxel_counts"]
        renamed_faces = {axis + "_" + side: faces[axis + "_index_" + index] for axis in "xyz" for side, index in (("low", "0"), ("high", "last"))}
        check("claimed_boundary_contact_" + profile, renamed_faces, claimed["boundary_contact"]["face_voxel_counts"])
    base, extended = candidate_masks["nasal_original"], candidate_masks["nasal_oropharynx"]
    check("original_missing_in_extension", int(np.count_nonzero(base & ~extended)), 0)
    check("new_air_not_real_oropharynx_below_threshold", int(np.count_nonzero((extended & ~base) & ~(positive["oropharynx"] & (ct_array < -300)))), 0)
    check("all_real_added_oral_air_preserved", int(np.count_nonzero((extended & ~base) != expected_added)), 0)
    independent["added_air_voxels"] = int(np.count_nonzero(expected_added))
    check("claimed_added_air", independent["added_air_voxels"], author_report["profiles"]["nasal_oropharynx"]["added_air_voxels"])
    hypo = sitk.GetArrayFromImage(read(args.input_root / args.case / "masks/hypopharynx.nii.gz"))
    check("real_hypopharynx_is_empty", int(np.count_nonzero(hypo)), 0)
    check("empty_hypopharynx_refused", author_report["profiles"]["nasal_oropharynx_hypopharynx"], {"generated": False, "refusal": "empty_label:hypopharynx"})
    check("CFD_admitted_default_false", author_report["CFD_admitted"], False)
    check("outlet_selected_default_false", author_report["outlet_selected"], False)
    preview = author_report["preview"]
    selected = preview["native_fixed_indices_xyz"]
    maxima = [int(np.argmax(np.sum(expected_added, axis=(0, 1)))), int(np.argmax(np.sum(expected_added, axis=(0, 2)))), int(np.argmax(np.sum(expected_added, axis=(1, 2))))]
    check("preview_selected_indices_max_added_air", selected, maxima)
    expected_point = list(ct.TransformIndexToPhysicalPoint(tuple(selected)))
    check("preview_selected_LPS_coordinate", bool(np.allclose(preview["LPS_point_at_indices_mm"], expected_point, rtol=0, atol=1e-8)), True)
    check("preview_direction_matches_CT", preview["direction_row_major"], list(ct.GetDirection()))
    check("preview_sha256", audit.digest(Path(preview["path"])), preview["sha256"])
    independent["preview_expected_xyz"] = maxima
    independent["preview_expected_LPS_mm"] = expected_point
    independent["CT_geometry"] = audit.geometry(ct)
    independent["preview_expected_image_extents"] = {
        axis: [ct.GetOrigin()[i] - ct.GetSpacing()[i]/2, ct.GetOrigin()[i] + (ct.GetSize()[i]-.5)*ct.GetSpacing()[i]] for i, axis in enumerate("LPS")}
    env = load(author_run / "environment.json")
    snapshot = author_run / "prototype_source_snapshot.py"
    check("run_source_snapshot_matches_code_fingerprint", audit.digest(snapshot), env["prototype_sha256"])
    for source, claimed_hash in env["production_readonly_sha256"].items():
        check("production_source_current_matches_run_" + Path(source).name, audit.digest(Path(source)), claimed_hash)
    result = {"review_time_utc": datetime.now(timezone.utc).isoformat(), "case": args.case,
              "review_script_sha256": audit.digest(Path(__file__)), "author_run": str(author_run),
              "author_environment_sha256": audit.digest(author_run / "environment.json"),
              "independent_results": independent, "checks": checks,
              "all_pass": all(item["pass"] for item in checks), "command": [sys.executable, *sys.argv],
              "limits": ["This is an uncropped semantic air candidate", "No anatomy completeness / symptom causality / CFD admission established", "STL not exported in reviewed run; STL checks not applicable", "Visual inspection recorded separately"]}
    audit.dump(args.out / "real_candidate_review.json", result)
    if not result["all_pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
