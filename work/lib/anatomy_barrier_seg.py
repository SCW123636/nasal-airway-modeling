# -*- coding: utf-8 -*-
"""Build auditable, provisional nasal-air candidates from CT and TS labels.

Manual LPS planes are applied only when a review JSON marks each plane
confirmed. Sinus air is never inferred from threshold connectivity alone.
"""
import argparse
import json
import os
import shutil
import tempfile

import numpy as np
import SimpleITK as sitk

ROOT = r"D:\项目\鼻腔建模"
TS_BASE = r"C:\ts_work"
FLOW_CLASSES = ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx")
REFERENCE_CLASSES = ("oropharynx", "soft_palate", "hard_palate")
THRESHOLDS = (-300, -350, -400)
OPENING_KEYS = (
    "nostril_L", "nostril_R", "nasopharynx_outlet", "maxillary_sinus_left",
    "maxillary_sinus_right", "frontal_sinus", "ethmoid_sinus_left",
    "ethmoid_sinus_right", "sphenoid_sinus",
)
PLANE_KEYS = ("nostril_L", "nostril_R", "nasopharynx_outlet", "oral_exclusion")


def geometry_equal(a, b, tol=1e-5):
    return (a.GetSize() == b.GetSize()
            and np.allclose(a.GetSpacing(), b.GetSpacing(), atol=tol, rtol=0)
            and np.allclose(a.GetOrigin(), b.GetOrigin(), atol=tol, rtol=0)
            and np.allclose(a.GetDirection(), b.GetDirection(), atol=tol, rtol=0))


def read_mask(mask_dir, name, reference, required=False):
    path = os.path.join(mask_dir, name + ".nii.gz")
    if not os.path.isfile(path):
        if required:
            raise FileNotFoundError("required TotalSegmentator label missing: " + path)
        return None, None
    img = sitk.ReadImage(path)
    if not geometry_equal(reference, img):
        raise ValueError("CT/mask geometry mismatch: " + name)
    return img, sitk.GetArrayFromImage(img) > 0


def plane_keep_mask(img, plane, shape):
    """Evaluate a finite LPS plane patch by slices to keep peak memory bounded."""
    point = np.asarray(plane.get("point_lps_mm"), dtype=float)
    normal = np.asarray(plane.get("normal_lps"), dtype=float)
    if point.shape != (3,) or normal.shape != (3,) or not np.isfinite(point).all() or not np.isfinite(normal).all():
        raise ValueError("plane point_lps_mm and normal_lps must each contain 3 finite values")
    norm = float(np.linalg.norm(normal))
    if norm < 1e-8:
        raise ValueError("plane normal_lps must be nonzero")
    normal /= norm
    roi = plane.get("roi_lps_mm", {})
    roi_min = np.asarray(roi.get("min"), dtype=float)
    roi_max = np.asarray(roi.get("max"), dtype=float)
    if (roi_min.shape != (3,) or roi_max.shape != (3,)
            or not np.isfinite(roi_min).all() or not np.isfinite(roi_max).all()
            or np.any(roi_min >= roi_max)):
        raise ValueError("confirmed plane needs roi_lps_mm min/max bounds in mm")
    keep_positive = bool(plane.get("keep_positive", True))

    spacing = np.asarray(img.GetSpacing(), dtype=float)
    direction = np.asarray(img.GetDirection(), dtype=float).reshape(3, 3)
    origin = np.asarray(img.GetOrigin(), dtype=float)
    # Physical LPS position for voxel (x,y,z) is origin + direction @ (index*spacing).
    vx = direction[:, 0] * spacing[0]
    vy = direction[:, 1] * spacing[1]
    vz = direction[:, 2] * spacing[2]
    xs = np.arange(shape[2], dtype=float)
    ys = np.arange(shape[1], dtype=float)
    xx = normal[0] * vx[0] * xs[None, :] + normal[1] * vx[1] * xs[None, :] + normal[2] * vx[2] * xs[None, :]
    yy = normal[0] * vy[0] * ys[:, None] + normal[1] * vy[1] * ys[:, None] + normal[2] * vy[2] * ys[:, None]
    base = -float(np.dot(normal, point - origin))
    out = np.empty(shape, dtype=bool)
    for z in range(shape[0]):
        signed = xx + yy + base + float(np.dot(normal, vz)) * z
        px = origin[0] + vx[0] * xs[None, :] + vy[0] * ys[:, None] + vz[0] * z
        py = origin[1] + vx[1] * xs[None, :] + vy[1] * ys[:, None] + vz[1] * z
        pz = origin[2] + vx[2] * xs[None, :] + vy[2] * ys[:, None] + vz[2] * z
        inside_roi = ((px >= roi_min[0]) & (px <= roi_max[0])
                      & (py >= roi_min[1]) & (py <= roi_max[1])
                      & (pz >= roi_min[2]) & (pz <= roi_max[2]))
        keep_halfspace = signed >= 0 if keep_positive else signed <= 0
        out[z] = ~inside_roi | keep_halfspace
    return out


def apply_confirmed_planes(mask, image, config, used):
    for key in PLANE_KEYS:
        plane = config.get("planes_lps", {}).get(key)
        if not plane or plane.get("status") != "confirmed":
            continue
        mask &= plane_keep_mask(image, plane, mask.shape)
        if key not in used:
            used.append(key)
    return mask


def save_mask(reference, array, path):
    img = sitk.GetImageFromArray(array.astype(np.uint8))
    img.CopyInformation(reference)
    tmpdir = tempfile.TemporaryDirectory(prefix="nasal_seg_")
    try:
        staged = os.path.join(tmpdir.name, "mask.nii.gz")
        sitk.WriteImage(img, staged, True)
        shutil.copyfile(staged, path)
    finally:
        tmpdir.cleanup()


def write_review_template(path):
    template = {
        "schema": "anatomy_barrier_review/v1",
        "coordinate_system": "LPS",
        "unit": "mm",
        "planes_lps": {
            key: {"status": "unknown", "point_lps_mm": None, "normal_lps": None,
                  "keep_positive": True, "roi_lps_mm": {"min": None, "max": None},
                  "reviewer": "", "note": "Enter after anatomical review"}
            for key in PLANE_KEYS
        },
        "openings": {key: {"status": "unknown", "reviewer": "", "note": ""}
                     for key in OPENING_KEYS[:3]},
        "sinus_ostia": {key: {"status": "unknown", "reviewer": "", "note": ""}
                        for key in OPENING_KEYS[3:]},
        "sinus_branch_mask": None,
        "review_checklist": {
            key: "pending" for key in ("nostril_L", "nostril_R", "nasal_valve",
                                        "turbinate_gaps", "olfactory_cleft", "posterior_choana",
                                        "sinus_ostia", "oral_separation")
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser(description="Make provisional anatomy-constrained nasal airway masks")
    ap.add_argument("key", nargs="?", default="p0")
    ap.add_argument("--data-dir", help="Directory with ct.nii.gz and masks/")
    ap.add_argument("--out-dir", help="Product directory")
    ap.add_argument("--review", help="Reviewed JSON configuration in LPS/mm")
    args = ap.parse_args()

    data_dir = args.data_dir or os.path.join(TS_BASE, args.key)
    out_dir = args.out_dir or os.path.join(ROOT, "work", "05_ts_seg", args.key, "anatomy")
    os.makedirs(out_dir, exist_ok=True)
    ct_path = os.path.join(data_dir, "ct.nii.gz")
    if not os.path.isfile(ct_path):
        raise FileNotFoundError(ct_path)

    ct_img = sitk.ReadImage(ct_path)
    ct = sitk.GetArrayFromImage(ct_img)
    mask_dir = os.path.join(data_dir, "masks")
    anatomy = {}
    source_info = {}
    for name in FLOW_CLASSES + REFERENCE_CLASSES:
        img, array = read_mask(mask_dir, name, ct_img, required=name in FLOW_CLASSES)
        if array is not None:
            anatomy[name] = array
            source_info[name] = {"path": os.path.join(mask_dir, name + ".nii.gz"),
                                 "voxels": int(array.sum())}

    semantic = anatomy[FLOW_CLASSES[0]] | anatomy[FLOW_CLASSES[1]] | anatomy[FLOW_CLASSES[2]]
    review = {}
    if args.review:
        with open(args.review, "r", encoding="utf-8") as f:
            review = json.load(f)
    used_planes = []
    review_template = os.path.join(out_dir, "review_config_template_v2.json")
    if not os.path.exists(review_template):
        write_review_template(review_template)

    sinus_branch_input = None
    sinus_branch_source = review.get("sinus_branch_mask")
    if sinus_branch_source:
        if not os.path.isabs(sinus_branch_source) and args.review:
            sinus_branch_source = os.path.join(os.path.dirname(os.path.abspath(args.review)), sinus_branch_source)
        stage = tempfile.TemporaryDirectory(prefix="sinus_mask_")
        try:
            source_lower = sinus_branch_source.lower()
            suffix = ".nii.gz" if source_lower.endswith(".nii.gz") else os.path.splitext(source_lower)[1]
            staged_path = os.path.join(stage.name, "sinus_branch" + suffix)
            shutil.copyfile(sinus_branch_source, staged_path)
            sinus_img = sitk.ReadImage(staged_path)
        finally:
            stage.cleanup()
        if not geometry_equal(ct_img, sinus_img):
            raise ValueError("manual sinus_branch_mask geometry does not match CT")
        sinus_branch_input = (sitk.GetArrayFromImage(sinus_img) > 0) & (ct < -300)

    spacing = ct_img.GetSpacing()
    voxel_ml = float(np.prod(spacing) / 1000.0)
    thresholds = {}
    main_t300 = None
    for threshold in THRESHOLDS:
        candidate = semantic & (ct < threshold)
        candidate = apply_confirmed_planes(candidate, ct_img, review, used_planes)
        if threshold == -300:
            main_t300 = candidate.copy()
        name = f"main_nasal_airway_T{abs(threshold)}_provisional.nii.gz"
        path = os.path.join(out_dir, name)
        save_mask(ct_img, candidate, path)
        thresholds[str(threshold)] = {
            "path": path, "voxels": int(candidate.sum()),
            "volume_mL": round(float(candidate.sum() * voxel_ml), 3),
            "HU_gt0_voxels": int((candidate & (ct > 0)).sum()),
            "components_26_connectivity_not_used_as_anatomy_classifier": True,
        }

    oral_record = None
    if "oropharynx" in anatomy:
        oral = anatomy["oropharynx"] & (ct < -300)
        oral_path = os.path.join(out_dir, "oral_excluded_reference_T300.nii.gz")
        save_mask(ct_img, oral, oral_path)
        oral_record = {"path": oral_path, "voxels": int(oral.sum()),
                       "volume_mL": round(float(oral.sum() * voxel_ml), 3),
                       "meaning": "TS oropharynx air reference; review/cut-plane still required"}

    sinus_record = {"status": "not_generated", "reason": "TS Task 775 has no paranasal sinus air label; threshold connectivity alone cannot name an ostium"}
    g_sinus_record = {"status": "not_generated_until_sinus_branch_mask_and_ostia_are_reviewed"}
    if sinus_branch_input is not None:
        sinus_path = os.path.join(out_dir, "nasal_sinus_branch_reviewed.nii.gz")
        save_mask(ct_img, sinus_branch_input, sinus_path)
        sinus_record = {"status": "provided_manual_mask", "path": sinus_path,
                        "voxels": int(sinus_branch_input.sum()),
                        "volume_mL": round(float(sinus_branch_input.sum() * voxel_ml), 3)}
        g_sinus = apply_confirmed_planes(main_t300 | sinus_branch_input, ct_img, review, used_planes)
        g_sinus_path = os.path.join(out_dir, "G_sinus_T300_provisional.nii.gz")
        save_mask(ct_img, g_sinus, g_sinus_path)
        g_sinus_record = {"status": "provisional_requires_all_ostia_and_7_point_review",
                          "path": g_sinus_path, "voxels": int(g_sinus.sum()),
                          "volume_mL": round(float(g_sinus.sum() * voxel_ml), 3)}

    ostia = review.get("sinus_ostia", {})
    opening_status = {key: {"status": "unknown", "plane_confirmed": False}
                      for key in OPENING_KEYS}
    for key in OPENING_KEYS[:3]:
        plane_status = review.get("planes_lps", {}).get(key, {}).get("status")
        status = review.get("openings", {}).get(key, {}).get("status", "unknown")
        if status not in ("open", "closed", "unknown"):
            raise ValueError(f"invalid opening status for {key}: {status}")
        opening_status[key] = {"status": status, "plane_confirmed": plane_status == "confirmed"}
    for key in OPENING_KEYS[3:]:
        status = ostia.get(key, {}).get("status", "unknown")
        if status not in ("open", "closed", "unknown"):
            raise ValueError(f"invalid sinus ostium status for {key}: {status}")
        opening_status[key] = {"status": status, "plane_confirmed": None}
    planes_confirmed = all(
        review.get("planes_lps", {}).get(key, {}).get("status") == "confirmed"
        for key in PLANE_KEYS
    )
    checklist_pass = all(v == "pass" for v in review.get("review_checklist", {}).values()) and bool(review.get("review_checklist"))
    all_ostia_known = all(opening_status[key]["status"] in ("open", "closed")
                          for key in OPENING_KEYS[3:])

    manifest = {
        "schema": "nasal_anatomy_products/v1",
        "case": args.key,
        "method": "TotalSegmentator head_glands_cavities semantic labels intersected with HU air candidate",
        "status": "reviewed_candidate" if planes_confirmed and checklist_pass and all_ostia_known else "provisional",
        "coordinate_system": "LPS", "unit": "mm",
        "source_ct": os.path.abspath(ct_path),
        "source_geometry": {"size_xyz": list(ct_img.GetSize()), "spacing_xyz_mm": list(spacing),
                            "origin_xyz_mm": list(ct_img.GetOrigin()), "direction": list(ct_img.GetDirection())},
        "affine_4x4_LPS": (lambda d, s, o: (np.block([[d @ np.diag(s), np.asarray(o).reshape(3, 1)],
                                                        [np.zeros((1, 3)), np.ones((1, 1))]]).tolist()))(
                                                            np.asarray(ct_img.GetDirection()).reshape(3, 3),
                                                            spacing, ct_img.GetOrigin()),
        "source_labels": source_info,
        "threshold_candidates": thresholds,
        "oral_excluded_reference": oral_record,
        "sinus_branch": sinus_record,
        "G_main": {"path": thresholds["-300"]["path"],
                   "status": "provisional_requires_7_point_review_and_opening_plane_confirmation"},
        "G_sinus": g_sinus_record,
        "openings": opening_status,
        "manual_planes_applied_to_T300": used_planes,
        "review_config_template": review_template,
        "review_config_used": os.path.abspath(args.review) if args.review else None,
        "review_checklist_pass": checklist_pass,
        "all_sinus_ostia_resolved": all_ostia_known,
        "limitations": [
            "Tissue labels are anatomical proposals, not binary lumen labels; every output is intersected with CT HU threshold.",
            "The nasal cavity labels do not identify whether individual paranasal sinus ostia are open.",
            "Threshold connected components are not used to decide nasal versus oral or sinus anatomy.",
            "Confirmed planes are voxel-center half-space clips in LPS; resulting CFD caps and mesh quality still require surface review.",
        ],
    }
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"status": manifest["status"], "manifest": manifest_path,
                      "thresholds": thresholds, "oral_excluded_reference": oral_record,
                      "sinus_branch": sinus_record, "G_sinus": g_sinus_record,
                      "openings": opening_status,
                      "manual_planes_applied": used_planes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
