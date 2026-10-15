"""T-026 isolated audit/candidate tool. Never imports production segmentation code.

NIfTI only; label names are software classes, not anatomy coverage certificates.
All arrays use NumPy z,y,x, all physical coordinates use SimpleITK LPS mm.
"""
from __future__ import annotations

import os
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import argparse
import hashlib
import itertools
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

sitk.ProcessObject.SetGlobalDefaultNumberOfThreads(1)
BASE = ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx")
AUDIT_LABELS = BASE + ("oropharynx", "hypopharynx", "larynx_air")
PROFILES = {"nasal_original": BASE,
            "nasal_oropharynx": BASE + ("oropharynx",),
            "nasal_oropharynx_hypopharynx": BASE + ("oropharynx", "hypopharynx")}
THRESHOLD_HU = -300.0
TS_SITE = Path(r"C:\Users\lenovo\.workbuddy\binaries\python\envs\nasal-cfd\Lib\site-packages")
LIMITS = ["engineering_candidate_only", "symptom_patient_mapping_unknown",
          "uncropped_semantic_intersection_baseline_not_equivalent_to_final_production_STL",
          "symptom_location_unknown", "anatomical_extent_not_reviewed",
          "CT_complete_pharynx_or_larynx_coverage_not_established",
          "outlet_not_selected_or_frozen", "oral_cavity_exclusion_not_reviewed",
          "threshold_exploratory_not_medically_adjudicated", "not_CFD_admitted"]


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    def json_default(value):
        if isinstance(value, np.generic):
            return value.item()
        raise TypeError(type(value).__name__ + " is not JSON serializable")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    tmp.replace(path)


def geometry(image):
    return {"size_xyz": list(image.GetSize()), "spacing_xyz_mm": list(image.GetSpacing()),
            "origin_LPS_mm": list(image.GetOrigin()), "direction_row_major": list(image.GetDirection()),
            "coordinate_system": "LPS_mm", "array_axes": "zyx",
            "orientation_code": sitk.DICOMOrientImageFilter_GetOrientationFromDirectionCosines(image.GetDirection())}


def same_grid(a, b):
    return (a.GetDimension() == b.GetDimension() == 3 and a.GetSize() == b.GetSize()
            and np.allclose(a.GetSpacing(), b.GetSpacing(), rtol=0, atol=1e-6)
            and np.allclose(a.GetOrigin(), b.GetOrigin(), rtol=0, atol=1e-5)
            and np.allclose(a.GetDirection(), b.GetDirection(), rtol=0, atol=1e-6))


def write_nifti_and_reread(image, path):
    """Windows ITK NIfTI cannot open a Chinese absolute path in this runtime.

    Python changes cwd using Unicode; ITK receives only an ASCII basename.
    This process is single-threaded and writes exclusively inside this run.
    """
    path = Path(path).resolve()
    if not path.name.isascii():
        raise ValueError("NIfTI_basename_must_be_ASCII")
    previous = Path.cwd()
    try:
        os.chdir(path.parent)
        sitk.WriteImage(image, path.name, useCompression=True)
        return sitk.ReadImage(path.name)
    finally:
        os.chdir(previous)


def index_to_lps(indices_xyz, image):
    p = np.asarray(indices_xyz, dtype=float)
    direction = np.asarray(image.GetDirection()).reshape(3, 3)
    return np.asarray(image.GetOrigin()) + (p * image.GetSpacing()) @ direction.T


def ct_extent(image):
    size = np.asarray(image.GetSize())
    corners = np.array(list(itertools.product(*[(-0.5, float(n) - 0.5) for n in size])))
    world = index_to_lps(corners, image)
    return {"voxel_support_corners_LPS_mm": world.tolist(),
            "voxel_support_bounds_LPS_mm": [world.min(0).tolist(), world.max(0).tolist()],
            "FOV_extent_along_index_axes_mm": (size * image.GetSpacing()).tolist(),
            "physical_convention": "+L left, +P posterior, +S superior; bounds include half voxel support"}


def mask_extent(mask, image, components=False):
    coords_zyx = np.argwhere(mask)
    count = len(coords_zyx)
    result = {"voxels": count, "volume_mm3": float(count * np.prod(image.GetSpacing())),
              "empty": count == 0, "boundary_contact": None, "bounds_LPS_mm": None}
    if count == 0:
        return result
    indices = coords_zyx[:, ::-1]
    lo, hi = indices.min(0), indices.max(0)
    world = index_to_lps(indices, image)
    half_width = np.abs(np.asarray(image.GetDirection()).reshape(3, 3)) @ (np.asarray(image.GetSpacing()) / 2)
    result.update({"index_bounds_xyz_inclusive": [lo.tolist(), hi.tolist()],
                   "center_bounds_LPS_mm": [world.min(0).tolist(), world.max(0).tolist()],
                   "bounds_LPS_mm": [(world.min(0) - half_width).tolist(), (world.max(0) + half_width).tolist()]})
    size = np.asarray(image.GetSize())
    faces, margins = {}, {}
    for axis, name in enumerate("xyz"):
        faces[name + "_low"] = int(np.count_nonzero(indices[:, axis] == 0))
        faces[name + "_high"] = int(np.count_nonzero(indices[:, axis] == size[axis] - 1))
        margins[name + "_low_mm"] = float(lo[axis] * image.GetSpacing()[axis])
        margins[name + "_high_mm"] = float((size[axis] - 1 - hi[axis]) * image.GetSpacing()[axis])
    result["boundary_contact"] = {"any": any(faces.values()), "face_voxel_counts": faces,
                                  "voxel_support_gap_to_CT_face_mm": margins,
                                  "interpretation": "contact describes truncation risk; no contact does not prove anatomical completeness"}
    if components:
        cropped = mask[lo[2]:hi[2]+1, lo[1]:hi[1]+1, lo[0]:hi[0]+1]
        cc = {}
        for connectivity, order in ((6, 1), (26, 3)):
            labels, number = ndimage.label(cropped, structure=ndimage.generate_binary_structure(3, order))
            sizes = np.bincount(labels.ravel())[1:]
            cc[str(connectivity)] = {"component_count": int(number),
                                    "sizes_voxels_descending": sorted(map(int, sizes), reverse=True),
                                    "all_components_preserved": True}
        result["connectivity"] = cc
    return result


def require_arrays(ct_image, images, profile):
    if profile not in PROFILES:
        raise ValueError("unknown_profile:" + profile)
    if ct_image.GetDimension() != 3:
        raise ValueError("CT_not_3D")
    if not np.all(np.isfinite(ct_image.GetSpacing())) or min(ct_image.GetSpacing()) <= 0:
        raise ValueError("invalid_spacing")
    direction = np.asarray(ct_image.GetDirection()).reshape(3, 3)
    if not np.allclose(direction.T @ direction, np.eye(3), rtol=0, atol=1e-5):
        raise ValueError("direction_not_orthonormal")
    ct = sitk.GetArrayFromImage(ct_image)
    if not np.all(np.isfinite(ct)):
        raise ValueError("nonfinite_CT")
    arrays = {}
    for name in PROFILES[profile]:
        if name not in images:
            raise ValueError("missing_label:" + name)
        if not same_grid(ct_image, images[name]):
            raise ValueError("grid_mismatch:" + name)
        a = sitk.GetArrayFromImage(images[name])
        if not np.all(np.isfinite(a)) or not np.all((a == 0) | (a == 1)):
            raise ValueError("label_not_binary:" + name)
        arrays[name] = a > 0
        if not np.any(arrays[name]):
            raise ValueError("empty_label:" + name)
        if not np.any(arrays[name] & (ct < THRESHOLD_HU)):
            raise ValueError("empty_label_air:" + name)
    return ct, arrays


def build_candidate(ct_image, images, profile):
    ct, arrays = require_arrays(ct_image, images, profile)
    semantic = np.zeros(ct.shape, dtype=bool)
    for a in arrays.values():
        semantic |= a
    return semantic & (ct < THRESHOLD_HU)


def source_manifest(data_root, cases):
    paths = []
    for case in cases:
        root = data_root / case
        paths.append(root / "ct.nii.gz")
        paths.extend(root / "masks" / (name + ".nii.gz") for name in AUDIT_LABELS)
    return [{"path": str(p), "exists": p.is_file(), "bytes": p.stat().st_size if p.is_file() else None,
             "sha256": sha256(p) if p.is_file() else None} for p in paths]


def environment():
    import scipy
    import matplotlib
    map_path = TS_SITE / "totalsegmentator" / "map_to_binary.py"
    definitions = []
    if map_path.is_file():
        lines = map_path.read_text(encoding="utf-8").splitlines()
        definitions = [{"line": i, "text": line.strip()} for i, line in enumerate(lines, 1)
                       if any(t in line for t in ('"head_glands_cavities"', '"hypopharynx"',
                                                   '"headneck_bones_vessels"', '"larynx_air"'))]
    repo = Path(__file__).resolve().parents[3]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True).stdout.strip()
    production = {str(repo / p): sha256(repo / p) for p in ("work/lib/nasal_pipeline.py", "work/lib/ts_quality_gate.py")}
    return {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
            "SimpleITK": sitk.Version_VersionString(), "numpy": np.__version__, "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__, "threads": 1, "repo_HEAD": head,
            "prototype_path": str(Path(__file__).resolve()), "prototype_sha256": sha256(__file__),
            "production_readonly_sha256": production,
            "TotalSegmentator_installation": {"site_packages": str(TS_SITE),
                "dist_info": [p.name for p in TS_SITE.glob("totalsegmentator-*.dist-info")],
                "map_path": str(map_path), "map_sha256": sha256(map_path) if map_path.is_file() else None,
                "map_definitions": definitions, "inference_invoked": False}}


def synthetic_tests(out):
    """Explicit handwritten fixture; expected values are independent of build_candidate."""
    checks = []
    shape = (3, 4, 5)
    ct = np.full(shape, 100, dtype=np.float32)
    locations = {"nasal_cavity_left": (1, 1, 0), "nasal_cavity_right": (1, 1, 1),
                 "nasopharynx": (1, 1, 2), "oropharynx": (0, 1, 2), "hypopharynx": (0, 2, 2)}
    label_arrays = {name: np.zeros(shape, dtype=np.uint8) for name in locations}
    for name, idx in locations.items():
        label_arrays[name][idx] = 1
        ct[idx] = -301
    # Exact threshold excluded; below included; disconnected voxel retained; air without any label excluded.
    label_arrays["oropharynx"][2, 3, 4] = 1
    ct[2, 3, 4] = -900
    label_arrays["oropharynx"][2, 2, 4] = 1
    ct[2, 2, 4] = -300
    ct[2, 2, 3] = -1000
    image = sitk.GetImageFromArray(ct)
    image.SetSpacing((2, 3, 4))
    image.SetOrigin((10, 20, 30))
    image.SetDirection((0, -1, 0, 1, 0, 0, 0, 0, -1))
    images = {}
    for name, a in label_arrays.items():
        m = sitk.GetImageFromArray(a)
        m.CopyInformation(image)
        images[name] = m
    expected_original = {(1, 1, 0), (1, 1, 1), (1, 1, 2)}
    expected_oral = expected_original | {(0, 1, 2), (2, 3, 4)}
    expected_hypo = expected_oral | {(0, 2, 2)}
    built = {}
    for profile, expected in zip(PROFILES, (expected_original, expected_oral, expected_hypo)):
        got = build_candidate(image, images, profile)
        actual = set(map(tuple, np.argwhere(got)))
        assert actual == expected, (profile, actual, expected)
        built[profile] = got
        checks.append({"name": profile + "_handwritten_exact_set", "pass": True,
                       "expected_zyx": sorted(expected), "actual_zyx": sorted(actual)})
    assert not np.any(built["nasal_original"] & ~built["nasal_oropharynx"])
    checks.append({"name": "original_subset_extension_no_bridge_no_unlabelled_air", "pass": True})
    p = index_to_lps([[2, 1, 1]], image)[0]
    assert np.allclose(p, [7, 24, 26])  # 10-1*3, 20+2*2, 30-1*4
    bounds = ct_extent(image)["voxel_support_bounds_LPS_mm"]
    assert np.allclose(bounds, [[-0.5, 19, 20], [11.5, 29, 32]])
    assert np.isclose(mask_extent(built["nasal_oropharynx"], image)["volume_mm3"], 120)
    checks.append({"name": "handwritten_nonidentity_direction_LPS_mm_and_half_voxel_CT_bounds", "pass": True,
                   "expected_point": [7, 24, 26], "actual_point": p.tolist(), "expected_CT_support": bounds})
    reread = write_nifti_and_reread(image, out / "known_direction_roundtrip.nii.gz")
    assert same_grid(image, reread)
    assert np.array_equal(sitk.GetArrayFromImage(reread), ct)
    checks.append({"name": "NIfTI_roundtrip_nonidentity_direction_exact_array_in_Unicode_parent", "pass": True,
                   "output": "known_direction_roundtrip.nii.gz", "original_and_reread_geometry": geometry(reread)})
    component_summary = mask_extent(built["nasal_oropharynx"], image, components=True)
    assert component_summary["connectivity"]["6"]["sizes_voxels_descending"] == [4, 1]
    assert component_summary["boundary_contact"]["face_voxel_counts"]["x_low"] == 1
    assert component_summary["boundary_contact"]["face_voxel_counts"]["z_low"] == 1
    checks.append({"name": "handwritten_6_connectivity_and_scan_face_contacts", "pass": True,
                   "expected_component_sizes": [4, 1]})
    def rejects(name, test_images, expected, test_ct=image):
        try:
            build_candidate(test_ct, test_images, "nasal_oropharynx")
        except ValueError as exc:
            assert str(exc).startswith(expected), (name, str(exc), expected)
            checks.append({"name": name, "pass": True, "expected_error": expected, "actual_error": str(exc)})
        else:
            raise AssertionError(name + " unexpectedly accepted")
    absent = dict(images)
    del absent["oropharynx"]
    rejects("missing_label_rejected", absent, "missing_label:oropharynx")
    empty = sitk.Image(images["oropharynx"].GetSize(), sitk.sitkUInt8)
    empty.CopyInformation(image)
    rejects("empty_label_rejected", {**images, "oropharynx": empty}, "empty_label:oropharynx")
    shifted = sitk.Image(images["oropharynx"])
    shifted.SetOrigin((11, 20, 30))
    rejects("origin_mismatch_rejected", {**images, "oropharynx": shifted}, "grid_mismatch:oropharynx")
    turned = sitk.Image(images["oropharynx"])
    turned.SetDirection((1, 0, 0, 0, 1, 0, 0, 0, 1))
    rejects("direction_mismatch_rejected", {**images, "oropharynx": turned}, "grid_mismatch:oropharynx")
    spaced = sitk.Image(images["oropharynx"])
    spaced.SetSpacing((2, 3, 5))
    rejects("spacing_mismatch_rejected", {**images, "oropharynx": spaced}, "grid_mismatch:oropharynx")
    smaller = sitk.Image((4, 4, 3), sitk.sitkUInt8)
    rejects("size_mismatch_rejected", {**images, "oropharynx": smaller}, "grid_mismatch:oropharynx")
    nonbinary = sitk.GetImageFromArray(label_arrays["oropharynx"] * 2)
    nonbinary.CopyInformation(image)
    rejects("nonbinary_label_rejected", {**images, "oropharynx": nonbinary}, "label_not_binary:oropharynx")
    no_air = sitk.GetImageFromArray(np.full(shape, 0, dtype=np.float32))
    no_air.CopyInformation(image)
    rejects("no_air_label_rejected", images, "empty_label_air:", no_air)
    report = {"fixture_source": "handwritten explicit arrays and analytical coordinates in synthetic_tests source",
              "no_external_anatomical_claim": True, "checks": checks, "all_pass": True, "count": len(checks)}
    write_json(out / "known_answers.json", report)
    return report


def read_case(data_root, case):
    root = data_root / case
    ct = sitk.ReadImage(str(root / "ct.nii.gz"))
    labels = {}
    for name in AUDIT_LABELS:
        path = root / "masks" / (name + ".nii.gz")
        if path.is_file():
            labels[name] = sitk.ReadImage(str(path))
    return ct, labels


def audit_case(data_root, case, out):
    report = {"case": case, "symptom_patient_mapping": "unknown", "limitations": LIMITS,
              "required_input_issues": [], "labels": {}, "coverage_conclusion": "requires_professional_review"}
    try:
        ct_image, images = read_case(data_root, case)
        report["CT"] = {**geometry(ct_image), **ct_extent(ct_image)}
        ct = sitk.GetArrayFromImage(ct_image)
        for name in AUDIT_LABELS:
            p = data_root / case / "masks" / (name + ".nii.gz")
            entry = {"path": str(p), "exists": name in images}
            if name not in images:
                entry["issue"] = "file_missing"
            else:
                image = images[name]
                entry["geometry"] = geometry(image)
                entry["same_grid_as_CT"] = same_grid(ct_image, image)
                a = sitk.GetArrayFromImage(image)
                entry["binary_values_0_or_1"] = bool(np.all((a == 0) | (a == 1)))
                entry["semantic"] = mask_extent(a > 0, image)
                if same_grid(ct_image, image):
                    entry["air_HU_lt_minus300"] = mask_extent((a > 0) & (ct < THRESHOLD_HU), image)
                else:
                    entry["issue"] = "grid_mismatch_no_air_intersection"
            if name in PROFILES["nasal_oropharynx"] and (not entry.get("exists") or
                    not entry.get("same_grid_as_CT", False) or not entry.get("binary_values_0_or_1", False) or
                    entry.get("semantic", {}).get("empty", True) or entry.get("air_HU_lt_minus300", {}).get("empty", True)):
                report["required_input_issues"].append(name)
            report["labels"][name] = entry
        report["entry_pass_for_oropharynx_profile"] = not report["required_input_issues"]
        hypo = report["labels"]["hypopharynx"]
        report["entry_pass_for_hypopharynx_profile"] = bool(report["entry_pass_for_oropharynx_profile"] and
            hypo.get("same_grid_as_CT") and hypo.get("binary_values_0_or_1") and
            not hypo.get("air_HU_lt_minus300", {}).get("empty", True))
    except Exception as exc:
        report["error"] = type(exc).__name__ + ":" + str(exc)
        report["entry_pass_for_oropharynx_profile"] = False
        report["entry_pass_for_hypopharynx_profile"] = False
    write_json(out / (case + "_audit.json"), report)
    return report


def preview(ct_image, original, extended, out, case="p3", source_bound=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    ct = sitk.GetArrayFromImage(ct_image)
    added = extended & ~original
    if not np.any(added):
        raise ValueError("no_added_air_for_preview")
    x = int(np.argmax(added.sum(axis=(0, 1))))
    y = int(np.argmax(added.sum(axis=(0, 2))))
    z = int(np.argmax(added.sum(axis=(1, 2))))
    # Native slices retain exact indices; equal physical aspect, full CT FOV shown.
    slices = [("Sagittal", (slice(None), slice(None), x), 1, 2, [x, y, z]),
              ("Coronal", (slice(None), y, slice(None)), 0, 2, [x, y, z]),
              ("Axial", (z, slice(None), slice(None)), 0, 1, [x, y, z])]
    fig, axes = plt.subplots(2, 3, figsize=(15, 10), constrained_layout=True)
    direction = np.asarray(ct_image.GetDirection()).reshape(3, 3)
    card = np.allclose(direction, np.eye(3))
    sizes, spacing = np.asarray(ct_image.GetSize()), np.asarray(ct_image.GetSpacing())
    origin = np.asarray(ct_image.GetOrigin())
    for col, (name, sel, h, v, xyz) in enumerate(slices):
        if card:
            extent = [origin[h] - spacing[h]/2, origin[h] + (sizes[h] - .5)*spacing[h],
                      origin[v] - spacing[v]/2, origin[v] + (sizes[v] - .5)*spacing[v]]
            hl = ("L", "P", "S")[h] + " (LPS mm, increasing +)"
            vl = ("L", "P", "S")[v] + " (LPS mm, increasing +)"
        else:
            extent = [-spacing[h]/2, (sizes[h]-.5)*spacing[h], -spacing[v]/2, (sizes[v]-.5)*spacing[v]]
            hl = "index " + "xyz"[h] + " mm; +LPS=" + str(direction[:, h].tolist())
            vl = "index " + "xyz"[v] + " mm; +LPS=" + str(direction[:, v].tolist())
        for row in range(2):
            ax = axes[row, col]
            ax.imshow(ct[sel], cmap="gray", vmin=-1000, vmax=400, origin="lower", extent=extent, aspect="equal")
            rgba = np.zeros(original[sel].shape + (4,), dtype=float)
            rgba[original[sel]] = [0.05, 0.85, 1.0, .72]
            if row == 1:
                rgba[added[sel]] = [1.0, .4, .02, .85]
            ax.imshow(rgba, origin="lower", extent=extent, aspect="equal")
            for spine in ax.spines.values():
                spine.set_color("#d627a0")
                spine.set_linewidth(1.7)
            ax.set_xlabel(hl)
            ax.set_ylabel(vl)
            fixed_index = (x, y, z)[col]
            ax.set_title(("Uncropped baseline" if row == 0 else "Uncropped + oropharynx") + " | " + name + " native index=" + str(fixed_index))
    fig.legend(handles=[Patch(color="#0dd9ff", label="Original: nasal L/R + nasopharynx air"),
                        Patch(color="#ff6600", label="Added: labelled oropharynx air"),
                        Patch(facecolor="none", edgecolor="#d627a0", label="CT scan/FOV edge")],
               loc="outside lower center", ncol=3)
    identity = case + " engineering example / symptom identity unknown"
    if source_bound:
        identity += " / source geometry matched"
    fig.suptitle(identity + " | UNCROPPED (not final production STL) | same CT / same slice / equal mm aspect\n"
                 "HU < -300 exploratory; no bridge/closure; outlet/anatomy unreviewed; NOT CFD admitted", fontsize=12)
    path = out / (case + "_original_vs_oropharynx.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    description = {"path": str(path), "sha256": sha256(path), "native_fixed_indices_xyz": [x, y, z],
                   "slice_selection": "maximum added-air slice for each axis", "equal_physical_aspect": True,
                   "full_CT_FOV_visible": True, "no_resampling": True,
                   "direction_row_major": ct_image.GetDirection(), "LPS_point_at_indices_mm": index_to_lps([[x,y,z]], ct_image)[0].tolist()}
    write_json(out / "preview_coordinates.json", description)
    return description


def candidate(data_root, case, out, source_binding=None):
    ct, images = read_case(data_root, case)
    report = {"case": case, "symptom_patient_mapping": "unknown", "threshold_HU": THRESHOLD_HU,
              "baseline_definition": "UNCROPPED semantic label union intersect CT threshold; not equivalent to final cropped production STL",
              "operator": "union_of_named_binary_labels INTERSECT CT_strictly_less_than_threshold",
              "morphology_or_bridge_or_filling": False, "resampling": False, "component_removal": False,
              "outlet_selected": False, "CFD_admitted": False,
              "limitations": LIMITS, "profiles": {}}
    if source_binding:
        report["source_binding_evidence"] = source_binding
    originals = None
    oral = None
    for profile in PROFILES:
        try:
            mask = build_candidate(ct, images, profile)
            if originals is None:
                originals = mask.copy()
            subset = not np.any(originals & ~mask)
            added = int(np.count_nonzero(mask & ~originals))
            if profile != "nasal_original" and added == 0:
                raise ValueError("no_added_air")
            image = sitk.GetImageFromArray(mask.astype(np.uint8))
            image.CopyInformation(ct)
            p = out / (case + "_" + profile + "_candidate.nii.gz")
            reread = write_nifti_and_reread(image, p)
            assert same_grid(ct, reread)
            assert np.array_equal(sitk.GetArrayFromImage(reread) > 0, mask)
            report["profiles"][profile] = {"generated": True, "path": str(p), "sha256": sha256(p),
                "source_labels": PROFILES[profile], "original_is_subset": subset, "added_air_voxels": added,
                "reread_matches_exactly": True, **mask_extent(mask, ct, components=True)}
            if profile == "nasal_oropharynx":
                oral = mask.copy()
        except ValueError as exc:
            report["profiles"][profile] = {"generated": False, "refusal": str(exc)}
        write_json(out / (case + "_candidate_report.json"), report)
    if originals is not None and oral is not None:
        report["preview"] = preview(ct, originals, oral, out, case, bool(source_binding))
    write_json(out / (case + "_candidate_report.json"), report)
    return report


def write_summary(out, audits, result, env):
    lines = ["# T-026 五例覆盖审计与 p3 工程候选", "", "本次仅审计既有 NIfTI；未启动 TS、网格或求解。所有数字均可由同目录 JSON 与输入指纹复算。", "",
             "对照基线为未裁剪的左右鼻腔+鼻咽语义标签∩CT阈值；扩展域使用相同处理增加口咽。它们不是既有最终已裁剪患者 STL，生产流程可能另有连通、表面和开口后处理。", "",
             "软件类别不是解剖完整性证明。当前最小候选只加入口咽真实空气；下咽须有非空同网格标签；没有自动生成或冻结出口。", "",
             "| 例 | CT size xyz | 口咽空气体素 | 下咽空气体素 | 喉气道文件 | 口咽入口 | 下咽入口 |", "|---|---|---:|---:|---|---|---|"]
    for a in audits:
        def val(name):
            return a["labels"].get(name, {}).get("air_HU_lt_minus300", {}).get("voxels", "unknown")
        lines.append(f"| {a['case']} | {a.get('CT',{}).get('size_xyz','unknown')} | {val('oropharynx')} | {val('hypopharynx')} | {a['labels'].get('larynx_air',{}).get('exists',False)} | {a['entry_pass_for_oropharynx_profile']} | {a['entry_pass_for_hypopharynx_profile']} |")
    lines.extend(["", "## 覆盖解释", "", "逐例 JSON 给出 CT 的 LPS mm 物理范围、方向、标签/空气范围、六面接触体素和距离。未接触扫描边缘只说明标签在边缘前结束，不能证明整个咽喉被扫描或分割。患者 B 与 p 编号的映射为 unknown。", "",
                  "本机 TotalSegmentator 安装为 " + ", ".join(env["TotalSegmentator_installation"]["dist_info"]) + "；其 head_glands_cavities 含 hypopharynx，larynx_air 属 headneck_bones_vessels。映射路径、行号和 SHA 见 environment.json。此处未生成缺失喉部标签。", "",
                  "## p3 候选", ""])
    for name, profile in result.get("profiles", {}).items():
        if profile["generated"]:
            lines.append(f"- `{name}`：{profile['voxels']} 体素，{profile['volume_mm3']:.6f} mm³，新增 {profile['added_air_voxels']} 体素；原域子集={profile['original_is_subset']}。")
        else:
            lines.append(f"- `{name}`：拒绝生成，原因 `{profile['refusal']}`。")
    lines.extend(["", "原域与扩展域均保留全部真实不连通部分；连通分量见 JSON。无造桥、闭运算、插值补齐或删除分量。候选尚未获解剖/症状/下界出口/口腔排除复核，不符合 CFD 准入。", "",
                  "## 重现", "", "精确命令见 reproduction.json；新执行必须使用新的 --out 目录，脚本拒绝覆盖旧 run。已知答案结果先写 known_answers.json，随后真实审计与候选。输入前后 hashes 见 input_fingerprints_before/after.json，变化会失败。", ""])
    (out / "审计报告.md").write_text("\n".join(lines), encoding="utf-8")
    original = result.get("profiles", {}).get("nasal_original", {})
    oral = result.get("profiles", {}).get("nasal_oropharynx", {})
    review = ["# 专业复核请求（默认未审核）", "", "- 当前审核结果：未审核；复核人：王湧瑞（待实际填写）。", "- 工程示例：p3；与症状患者/患者 B 的对应关系：unknown。不得由文件编号推断身份。",
              "- 候选身份：未裁剪鼻腔—鼻咽基线与增加口咽真实空气的探索候选；不等同生产最终STL，不代表完整咽喉、喉部或声门。",
              "- CT 路径：" + str(Path(r"C:\ts_work") / "p3" / "ct.nii.gz"),
              "- 输入 CT/标签 SHA：见同目录 input_fingerprints_before.json。",
              "- 原域 SHA-256：" + str(original.get("sha256")), "- 口咽扩展 SHA-256：" + str(oral.get("sha256")),
              "- 审阅预览：p3_original_vs_oropharynx.png；原始候选 NIfTI 保留 CT 物理坐标。", "",
              "待逐项确认并记录证据：", "", "1. 身份与症状：该例是否为需研究患者？不适的具体位置、呼吸阶段与临床问题是什么？",
              "2. CT 覆盖：影像是否实际覆盖目标区域？是否需要下咽、喉部或声门；现有扫描与标签分别有什么缺口？",
              "3. 连续气道与口腔排除：鼻咽—口咽交界及口腔排除是否符合研究问题？标记需要修正的位置。",
              "4. 下界与出口：指出患者坐标中的下界/平面、理由、是否离开观察区足够远；现阶段不沿用原鼻咽出口。",
              "5. 认可范围：是否仅认可影像覆盖/解剖候选？阈值、边界条件、动态塌陷与 CFD 准入另行明确。", "",
              "复核日期：待填。决定与附件证据：待填。当前默认：未审核、出口未定、不可按已审核 CFD 输入使用。", ""]
    (out / "专业复核请求.md").write_text("\n".join(review), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path(r"C:\ts_work"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--self-test-only", action="store_true")
    args = parser.parse_args()
    out = args.out.resolve()
    allowed = Path(__file__).resolve().parents[1]
    if allowed not in out.parents:
        raise ValueError("output_must_be_inside_T026")
    out.mkdir(parents=True, exist_ok=False)
    env = environment()
    write_json(out / "environment.json", env)
    command = [sys.executable, str(Path(__file__).resolve()), "--data-root", str(args.data_root.resolve()), "--out", str(out)]
    write_json(out / "reproduction.json", {"argv": command, "rerun_note": "Choose a new --out run directory; existing directory is rejected", "start_UTC": datetime.now(timezone.utc).isoformat()})
    try:
        known = synthetic_tests(out)
        print(json.dumps({"phase": "known_answers", "all_pass": known["all_pass"], "count": known["count"]}), flush=True)
        if args.self_test_only:
            return
        cases = ("p0", "p1", "p2", "p3", "p3t1")
        before = source_manifest(args.data_root, cases)
        write_json(out / "input_fingerprints_before.json", before)
        audits = []
        for case in cases:
            audit = audit_case(args.data_root, case, out)
            audits.append(audit)
            print(json.dumps({"phase": "audit", "case": case, "oral_entry": audit["entry_pass_for_oropharynx_profile"], "hypo_entry": audit["entry_pass_for_hypopharynx_profile"]}), flush=True)
        result = candidate(args.data_root, "p3", out)
        after = source_manifest(args.data_root, cases)
        write_json(out / "input_fingerprints_after.json", after)
        unchanged = before == after
        write_json(out / "input_integrity.json", {"all_inputs_unchanged": unchanged, "comparison": "full content SHA256 plus existence and byte size"})
        assert unchanged, "input_fingerprint_changed"
        write_summary(out, audits, result, env)
        write_json(out / "run_result.json", {"execution_finished": True, "all_inputs_unchanged": unchanged,
                    "known_answers_pass": known["all_pass"], "case_count": len(audits),
                    "candidate_case": "p3", "professional_review": "not_reviewed", "CFD_admitted": False,
                    "end_UTC": datetime.now(timezone.utc).isoformat(), "requires_Lead_and_fresh_independent_acceptance": True})
        print(json.dumps({"phase": "artifacts_written", "out": str(out), "all_inputs_unchanged": unchanged}), flush=True)
    except Exception as exc:
        write_json(out / "run_failure.json", {"error_type": type(exc).__name__, "message": str(exc), "UTC": datetime.now(timezone.utc).isoformat()})
        raise


if __name__ == "__main__":
    main()
