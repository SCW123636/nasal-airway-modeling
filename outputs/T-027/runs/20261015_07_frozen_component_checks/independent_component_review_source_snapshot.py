"""Fresh known-answer and rejection checks of T-026 public functions.

Fixture and analytic answers originate here, not from T-026 self-tests.
Outputs never write outside the directory passed by --out.
"""
from __future__ import annotations
import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import sys

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS"):
    os.environ[_key] = "1"
import numpy as np
import SimpleITK as sitk
sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__ + " is not JSON serializable")


def image(a, reference=None):
    im = sitk.GetImageFromArray(a)
    if reference is not None:
        im.CopyInformation(reference)
    return im


def component_sizes(mask, diagonal=False):
    remaining = set(map(tuple, np.argwhere(mask)))
    offsets = [p for p in itertools.product((-1, 0, 1), repeat=3)
               if p != (0, 0, 0) and (diagonal or sum(map(abs, p)) == 1)]
    sizes = []
    while remaining:
        queue = deque([remaining.pop()])
        count = 0
        while queue:
            p = queue.popleft()
            count += 1
            for d in offsets:
                q = tuple(p[i] + d[i] for i in range(3))
                if q in remaining:
                    remaining.remove(q)
                    queue.append(q)
        sizes.append(count)
    return sorted(sizes, reverse=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--implementation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    implementation_before = sha(args.implementation)
    spec = importlib.util.spec_from_file_location("t026_under_independent_review", args.implementation)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = []

    def check(name, actual, expected):
        passed = actual == expected
        checks.append({"name": name, "pass": passed, "actual": actual, "expected": expected})
        print(json.dumps(checks[-1], ensure_ascii=False, default=json_default), flush=True)

    def rejects(name, ct_im, ims, expected, profile="nasal_oropharynx"):
        try:
            module.build_candidate(ct_im, ims, profile)
        except Exception as exc:
            actual = type(exc).__name__ + ":" + str(exc)
        else:
            actual = "ACCEPTED"
        check(name, actual, "ValueError:" + expected)

    shape = (5, 6, 7)
    ct_array = np.full(shape, 20, dtype=np.float64)
    labelled = {
        "nasal_cavity_left": [(1, 1, 1), (1, 1, 2)],
        "nasal_cavity_right": [(1, 2, 1)],
        "nasopharynx": [(2, 2, 2)],
        "oropharynx": [(2, 2, 2), (3, 2, 2), (4, 5, 6), (3, 3, 3), (3, 3, 4), (3, 3, 5)],
        "hypopharynx": [(4, 2, 2)],
    }
    arrays = {name: np.zeros(shape, dtype=np.uint8) for name in labelled}
    for name, points in labelled.items():
        for point in points:
            arrays[name][point] = 1
            ct_array[point] = -500
    ct_array[3, 3, 3] = -300
    ct_array[3, 3, 4] = -299.9999
    ct_array[3, 3, 5] = -300.0001
    ct_array[0, 0, 0] = -1000  # Unlabelled air must remain out.
    ct_im = image(ct_array)
    ct_im.SetSpacing((0.7, 1.3, 2.1))
    ct_im.SetOrigin((-12, 6, 40))
    ct_im.SetDirection((0.6, -0.8, 0, 0.8, 0.6, 0, 0, 0, -1))
    ims = {name: image(a, ct_im) for name, a in arrays.items()}
    baseline = {(1, 1, 1), (1, 1, 2), (1, 2, 1), (2, 2, 2)}
    extension = baseline | {(3, 2, 2), (4, 5, 6), (3, 3, 5)}
    extended_hypo = extension | {(4, 2, 2)}
    expectations = {"nasal_original": baseline, "nasal_oropharynx": extension,
                    "nasal_oropharynx_hypopharynx": extended_hypo}
    built = {}
    for profile, expected in expectations.items():
        built[profile] = module.build_candidate(ct_im, ims, profile)
        actual = set(map(tuple, np.argwhere(built[profile])))
        check("explicit_set_" + profile, sorted(map(list, actual)), sorted(map(list, expected)))
    check("strict_threshold_exact_excluded", bool(built["nasal_oropharynx"][3, 3, 3]), False)
    check("strict_threshold_above_excluded", bool(built["nasal_oropharynx"][3, 3, 4]), False)
    check("strict_threshold_below_included", bool(built["nasal_oropharynx"][3, 3, 5]), True)
    check("unlabelled_air_excluded", bool(built["nasal_oropharynx"][0, 0, 0]), False)
    check("original_subset_of_extension", bool(np.all(~built["nasal_original"] | built["nasal_oropharynx"])), True)
    check("separate_6_components_retained", component_sizes(built["nasal_oropharynx"]), [3, 2, 1, 1])
    check("separate_26_components_retained", component_sizes(built["nasal_oropharynx"], True), [5, 1, 1])
    check("hand_calculated_LPS_oblique_flip", bool(np.allclose(module.index_to_lps([[5, 4, 3]], ct_im)[0], [-14.06, 11.92, 33.7], rtol=0, atol=1e-12)), True)
    check("hand_calculated_CT_support_bounds", bool(np.allclose(module.ct_extent(ct_im)["voxel_support_bounds_LPS_mm"], [[-17.93, 5.33, 30.55], [-8.75, 13.93, 41.05]], rtol=0, atol=1e-12)), True)
    all_indices = list(itertools.product(range(7), range(6), range(5)))
    expected_points = [ct_im.TransformIndexToPhysicalPoint(point) for point in all_indices]
    check("all_210_centres_against_SimpleITK_transform", bool(np.allclose(module.index_to_lps(all_indices, ct_im), expected_points, rtol=0, atol=1e-12)), True)
    summary = module.mask_extent(built["nasal_oropharynx"], ct_im, components=True)
    expected_centres = np.asarray([ct_im.TransformIndexToPhysicalPoint((x, y, z)) for z, y, x in extension])
    half_support = np.array([0.73, 0.67, 1.05])  # |D| @ spacing / 2, evaluated by hand.
    expected_bounds = [(expected_centres.min(0) - half_support).tolist(), (expected_centres.max(0) + half_support).tolist()]
    check("mask_centre_bounds_distinct_from_support", bool(np.allclose(summary["center_bounds_LPS_mm"], [expected_centres.min(0), expected_centres.max(0)], rtol=0, atol=1e-12) and np.allclose(summary["bounds_LPS_mm"], expected_bounds, rtol=0, atol=1e-12)), True)
    check("anisotropic_volume_mm3", bool(np.isclose(summary["volume_mm3"], 7 * 0.7 * 1.3 * 2.1, rtol=0, atol=1e-12)), True)
    check("reported_6_components", summary["connectivity"]["6"]["sizes_voxels_descending"], [3, 2, 1, 1])
    check("reported_26_components", summary["connectivity"]["26"]["sizes_voxels_descending"], [5, 1, 1])
    check("reported_scan_face_counts", summary["boundary_contact"]["face_voxel_counts"], {"x_low": 0, "x_high": 1, "y_low": 0, "y_high": 1, "z_low": 0, "z_high": 1})
    for name in ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx", "oropharynx"):
        missing = dict(ims)
        del missing[name]
        rejects("missing_" + name, ct_im, missing, "missing_label:" + name)
        empty = image(np.zeros(shape, dtype=np.uint8), ct_im)
        rejects("empty_" + name, ct_im, {**ims, name: empty}, "empty_label:" + name)
    for field in ("origin", "spacing", "direction", "size"):
        altered = sitk.Image(ims["oropharynx"])
        if field == "origin":
            altered.SetOrigin((-12, 6.00002, 40))
        elif field == "spacing":
            altered.SetSpacing((0.7, 1.30001, 2.1))
        elif field == "direction":
            altered.SetDirection((1, 0, 0, 0, 1, 0, 0, 0, -1))
        else:
            altered = sitk.Image((6, 6, 5), sitk.sitkUInt8)
        rejects("grid_mismatch_" + field, ct_im, {**ims, "oropharynx": altered}, "grid_mismatch:oropharynx")
    rejects("nonbinary_label", ct_im, {**ims, "oropharynx": image(arrays["oropharynx"] * 2, ct_im)}, "label_not_binary:oropharynx")
    no_oral_air = ct_array.copy()
    no_oral_air[arrays["oropharynx"] > 0] = 0
    # Retain baseline nasopharynx air elsewhere to reach the intended oral rejection.
    other_naso = arrays["nasopharynx"].copy()
    other_naso[0, 1, 0] = 1
    no_oral_air[0, 1, 0] = -700
    rejects("nonempty_oral_label_without_air", image(no_oral_air, ct_im), {**ims, "nasopharynx": image(other_naso, ct_im)}, "empty_label_air:oropharynx")
    rejects("empty_hypopharynx_profile", ct_im, {**ims, "hypopharynx": image(np.zeros(shape, dtype=np.uint8), ct_im)}, "empty_label:hypopharynx", "nasal_oropharynx_hypopharynx")
    nonfinite = ct_array.copy()
    nonfinite[0, 0, 0] = np.nan
    rejects("nonfinite_CT", image(nonfinite, ct_im), ims, "nonfinite_CT")
    rejects("unknown_profile", ct_im, ims, "unknown_profile:invented", "invented")
    rejects("CT_2D", image(np.zeros((4, 5))), ims, "CT_not_3D")
    # Positive control on optional profile semantics: missing optional hypopharynx
    # must not make the original/oropharynx profiles fail.
    absent_hypo = dict(ims)
    del absent_hypo["hypopharynx"]
    actual = set(map(tuple, np.argwhere(module.build_candidate(ct_im, absent_hypo, "nasal_oropharynx"))))
    check("optional_hypopharynx_not_required_for_oral", sorted(map(list, actual)), sorted(map(list, extension)))
    implementation_after = sha(args.implementation)
    check("implementation_unchanged_during_review", implementation_after, implementation_before)
    report = {"review_time_utc": datetime.now(timezone.utc).isoformat(), "implementation": str(args.implementation.resolve()),
              "implementation_sha256_before": implementation_before, "implementation_sha256_after": implementation_after,
              "review_script_sha256": sha(__file__), "python": sys.version, "SimpleITK": sitk.Version_VersionString(),
              "numpy": np.__version__, "command": [sys.executable, *sys.argv],
              "known_answer_provenance": "Explicit zyx sets and hand-evaluated 3-4-5 oblique/flip transform in this independent script; SimpleITK transform is a second independent coordinate oracle.",
              "checks": checks, "all_pass": all(c["pass"] for c in checks)}
    write(args.out / "independent_component_checks.json", report)
    if not report["all_pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
