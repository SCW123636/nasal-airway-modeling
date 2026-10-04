# -*- coding: utf-8 -*-
"""Audit TotalSegmentator head_glands_cavities labels against the source CT.

Volume, span, and symmetry are reported as review hints. Hard failures concern
data integrity and empty required masks. Connectivity is evidence about this
discrete segmentation, not proof of anatomical patency or a valid CFD domain.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
import SimpleITK as sitk
from scipy import ndimage

ROOT = r"D:\项目\鼻腔建模"
TS_BASE = r"C:\ts_work"
CLASSES = (
    "nasal_cavity_left", "nasal_cavity_right", "nasopharynx",
    "oropharynx", "soft_palate", "hard_palate",
)
FLOW_CLASSES = ("nasal_cavity_left", "nasal_cavity_right", "nasopharynx")


def read_image(path):
    """Read images through an ASCII temporary path when native I/O truncates Unicode paths."""
    try:
        return sitk.ReadImage(str(path))
    except RuntimeError:
        if all(ord(char) < 128 for char in str(path)):
            raise
        with tempfile.TemporaryDirectory(prefix="ts_quality_read_") as temp_dir:
            staged = Path(temp_dir) / Path(path).name
            shutil.copyfile(path, staged)
            return sitk.ReadImage(str(staged))


def same_geometry(a, b, tol=1e-5):
    return (a.GetSize() == b.GetSize()
            and np.allclose(a.GetSpacing(), b.GetSpacing(), atol=tol, rtol=0)
            and np.allclose(a.GetOrigin(), b.GetOrigin(), atol=tol, rtol=0)
            and np.allclose(a.GetDirection(), b.GetDirection(), atol=tol, rtol=0))


def load_mask(path, reference):
    image = read_image(path)
    return image, sitk.GetArrayFromImage(image) > 0


def bbox_zyx(mask):
    coords = np.where(mask)
    if not coords[0].size:
        return None
    return [[int(axis.min()), int(axis.max())] for axis in coords]


def connectivity_structure(connectivity):
    if connectivity not in (6, 26):
        raise ValueError("connectivity must be 6 or 26")
    return ndimage.generate_binary_structure(3, 1 if connectivity == 6 else 3)


def component_summary(mask, voxel_ml, connectivity=26):
    box = bbox_zyx(mask)
    if box is None:
        return {"count": 0, "largest_voxels": 0, "nonlargest_voxels": 0,
                "largest_fraction": None, "sizes_mL": [],
                "sizes_mL_largest_first": [], "connectivity": connectivity}
    margin = 1
    slices = tuple(slice(max(0, lo - margin), min(mask.shape[i], hi + margin + 1))
                   for i, (lo, hi) in enumerate(box))
    local = mask[slices]
    labels, count = ndimage.label(local, structure=connectivity_structure(connectivity))
    counts = np.bincount(labels.ravel())[1:]
    counts.sort()
    top = counts[::-1][:10]
    return {
        "count": int(count),
        "largest_voxels": int(counts[-1]) if count else 0,
        "nonlargest_voxels": int(counts.sum() - counts[-1]) if count else 0,
        "largest_fraction": round(float(counts[-1] / counts.sum()), 8) if count else None,
        "sizes_mL_largest_first": [round(float(n * voxel_ml), 4) for n in top],
        "bbox_zyx_inclusive": box,
        "connectivity": connectivity,
    }


def raw_hu_statistics(ct, mask):
    """Measure the original semantic mask, before any HU filtering."""
    values = ct[mask]
    finite = values[np.isfinite(values)]
    stats = {"sample_voxels": int(values.size),
             "nonfinite_voxels": int(values.size - finite.size),
             "HU_gt0_voxels": int(np.count_nonzero(finite > 0)),
             "interpretation": "original semantic label before HU threshold intersection"}
    if not finite.size:
        stats.update({key: None for key in ("min", "p05", "median", "p95", "max", "mean")})
        return stats
    p05, median, p95 = np.percentile(finite, [5, 50, 95])
    stats.update({"min": float(finite.min()), "p05": float(p05), "median": float(median),
                  "p95": float(p95), "max": float(finite.max()), "mean": float(finite.mean())})
    return stats


def audit_label(name, image, ct_image, ct, hard_failures, warnings):
    """Return metrics and a usable mask only after grid compatibility checks."""
    mask = sitk.GetArrayFromImage(image) > 0
    shape_ok = mask.shape == ct.shape
    geom_ok = image.GetDimension() == ct_image.GetDimension() and same_geometry(ct_image, image)
    scalar_ok = image.GetNumberOfComponentsPerPixel() == 1
    voxels = int(mask.sum())
    result = {
        "found": True, "geometry_matches_ct": bool(geom_ok),
        "array_shape_matches_ct": bool(shape_ok), "scalar_label": scalar_ok,
        "voxels": voxels,
        "semantic_volume_mL": round(float(voxels * np.prod(image.GetSpacing()) / 1000), 3),
        "air_voxels_HU_lt_minus300": None, "air_fraction_HU_lt_minus300": None,
        "raw_semantic_HU": None, "bbox_zyx_inclusive": bbox_zyx(mask) if mask.ndim == 3 else None,
        "usable_on_ct_grid": bool(shape_ok and geom_ok and scalar_ok),
    }
    if not geom_ok:
        hard_failures.append("geometry mismatch: " + name)
    if not shape_ok:
        hard_failures.append("array shape mismatch: " + name)
    if not scalar_ok:
        hard_failures.append("label is not scalar: " + name)
    if voxels == 0:
        (hard_failures if name in FLOW_CLASSES else warnings).append(
            ("required label empty: " if name in FLOW_CLASSES else "reference label empty: ") + name)
    if not result["usable_on_ct_grid"]:
        result["HU_statistics_status"] = "unavailable_grid_mismatch_or_nonscalar_label"
        result["fov_boundary_contact"] = {"status": "unavailable_incompatible_grid"}
        return result, None
    box = result["bbox_zyx_inclusive"]
    faces = []
    if box is not None:
        for axis, (lo, hi) in enumerate(box):
            if lo == 0:
                faces.append("zyx"[axis] + "_min")
            if hi == mask.shape[axis] - 1:
                faces.append("zyx"[axis] + "_max")
    result["fov_boundary_contact"] = {
        "touches_image_boundary": bool(faces), "index_faces": faces,
        "interpretation": "label reaches acquisition grid boundary; anatomical truncation not proven",
    }
    if faces:
        warnings.append("label touches image boundary: " + name + " (" + ", ".join(faces) + ")")
    # Never index the CT using a mask with a different shape or affine geometry.
    raw = raw_hu_statistics(ct, mask)
    result["raw_semantic_HU"] = raw
    result["HU_statistics_status"] = "measured_before_threshold"
    air_voxels = int(np.count_nonzero(ct[mask] < -300))
    result["air_voxels_HU_lt_minus300"] = air_voxels
    result["air_fraction_HU_lt_minus300"] = round(air_voxels / voxels, 5) if voxels else None
    if raw["nonfinite_voxels"]:
        hard_failures.append("nonfinite CT values within label: " + name)
    if name in FLOW_CLASSES and voxels and air_voxels == 0:
        hard_failures.append("required label has no air below -300 HU: " + name)
    return result, mask


def pathway_evidence(source, target, connectivity):
    """Audit paths in one nasal side plus nasopharynx, without contralateral detours.

    These paths start somewhere within a semantic nasal label. No nostril or
    CFD outlet is supplied, so they cannot prove an inlet-to-outlet flow path.
    """
    if source.shape != target.shape or source.ndim != 3:
        raise ValueError("path masks must be 3D and share one grid")
    box = bbox_zyx(source | target)
    result = {"connectivity": connectivity, "source_voxels": int(source.sum()),
              "target_voxels": int(target.sum()), "direct_contact": False,
              "direct_contact_target_voxels": 0, "shared_path_exists": False,
              "source_voxels_reaching_target": 0, "source_fraction_reaching_target": 0.0,
              "largest_source_component_voxels": 0,
              "largest_source_component_reaches_target": False,
              "domain": "ipsilateral_nasal_air_union_nasopharynx_air"}
    if box is None or not source.any() or not target.any():
        result["status"] = "unavailable_empty_source_or_target"
        return result
    slices = tuple(slice(max(0, lo - 1), min(source.shape[i], hi + 2))
                   for i, (lo, hi) in enumerate(box))
    source, target = source[slices], target[slices]
    structure = connectivity_structure(connectivity)
    contacts = ndimage.binary_dilation(source, structure=structure) & target
    union_labels, _ = ndimage.label(source | target, structure=structure)
    target_ids = np.unique(union_labels[target])
    target_ids = target_ids[target_ids != 0]
    source_union_ids = union_labels[source]
    reachable = np.isin(source_union_ids, target_ids)
    source_labels, _ = ndimage.label(source, structure=structure)
    source_sizes = np.bincount(source_labels.ravel())
    source_sizes[0] = 0
    largest_id = int(source_sizes.argmax())
    largest_reaches = bool(np.isin(union_labels[source_labels == largest_id], target_ids).any())
    result.update({
        "direct_contact": bool(contacts.any()),
        "direct_contact_target_voxels": int(contacts.sum()),
        "shared_path_exists": bool(reachable.any()),
        "source_voxels_reaching_target": int(reachable.sum()),
        "source_fraction_reaching_target": round(float(reachable.mean()), 6),
        "largest_source_component_voxels": int(source_sizes[largest_id]),
        "largest_source_component_reaches_target": largest_reaches,
        "status": "voxel_path_observed" if largest_reaches else "path_not_established",
    })
    return result


def save_overlay(ct, flow, oral, soft, hard, out_png, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    box = bbox_zyx(flow)
    if box:
        centers = [int((lo + hi) / 2) for lo, hi in box]
    else:
        centers = [n // 2 for n in ct.shape]
    zc, yc, xc = centers
    planes = [
        (ct[zc, :, :], flow[zc, :, :], oral[zc, :, :], soft[zc, :, :], hard[zc, :, :], f"axial z={zc}"),
        (ct[:, yc, :], flow[:, yc, :], oral[:, yc, :], soft[:, yc, :], hard[:, yc, :], f"coronal y={yc}"),
        (ct[:, :, xc], flow[:, :, xc], oral[:, :, xc], soft[:, :, xc], hard[:, :, xc], f"sagittal x={xc}"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(16, 6))
    for ax, (image, fmask, omask, smask, hmask, label) in zip(axes, planes):
        ax.imshow(np.clip(image, -300, 1500), cmap="gray", origin="lower")
        for mask, color, alpha in ((fmask, "red", .55), (omask, "blue", .4),
                                   (smask, "lime", .45), (hmask, "yellow", .4)):
            ax.imshow(np.ma.masked_where(~mask, mask), cmap=matplotlib.colors.ListedColormap([color]),
                      alpha=alpha, origin="lower")
        ax.set_title(label)
        ax.axis("off")
    fig.suptitle(title + " | red=nasal/nasopharynx air, blue=oropharynx, green=soft palate, yellow=hard palate")
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("key", nargs="?", default="p0")
    ap.add_argument("--data-dir", help="Directory containing ct.nii.gz and masks/")
    ap.add_argument("--out-dir", help="Report output directory; defaults to data directory")
    args = ap.parse_args(argv)

    data_dir = args.data_dir or os.path.join(TS_BASE, args.key)
    if not args.data_dir and not os.path.isfile(os.path.join(data_dir, "ct.nii.gz")):
        data_dir = os.path.join(ROOT, "work", "05_ts_seg", args.key)
    out_dir = args.out_dir or data_dir
    os.makedirs(out_dir, exist_ok=True)
    ct_path = os.path.join(data_dir, "ct.nii.gz")
    mask_dir = os.path.join(data_dir, "masks")
    report = {"case": args.key, "ct": ct_path, "mask_dir": mask_dir,
              "threshold_HU": -300, "overall_status": "fail", "hard_failures": [],
              "warnings": [], "manual_review_required": True, "audit_version": "2.0",
              "medical_or_cfd_validation_pass": False}
    if not os.path.isfile(ct_path):
        report["hard_failures"].append("ct.nii.gz missing")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2

    ct_image = read_image(ct_path)
    ct = sitk.GetArrayFromImage(ct_image)
    spacing = ct_image.GetSpacing()
    voxel_ml = float(np.prod(spacing) / 1000.0)
    report["ct_geometry"] = {"size_xyz": list(ct_image.GetSize()),
                             "spacing_xyz_mm": list(spacing),
                             "origin_xyz_mm": list(ct_image.GetOrigin()),
                             "direction": list(ct_image.GetDirection()),
                             "coordinate_system": "LPS", "unit": "mm"}

    arrays = {}
    per_class = {}
    for name in CLASSES:
        path = os.path.join(mask_dir, name + ".nii.gz")
        if not os.path.isfile(path):
            per_class[name] = {"found": False}
            if name in FLOW_CLASSES:
                report["hard_failures"].append("required label missing: " + name)
            else:
                report["warnings"].append("reference label missing: " + name)
            continue
        try:
            image = read_image(path)
            metrics, mask = audit_label(name, image, ct_image, ct,
                                        report["hard_failures"], report["warnings"])
            per_class[name] = metrics
            if mask is not None:
                arrays[name] = mask
        except (RuntimeError, ValueError) as exc:
            per_class[name] = {"found": True, "readable": False, "error": str(exc)}
            report["hard_failures"].append("cannot audit label: " + name)

    report["per_class"] = per_class
    if all(name in arrays for name in FLOW_CLASSES):
        semantic = arrays[FLOW_CLASSES[0]] | arrays[FLOW_CLASSES[1]] | arrays[FLOW_CLASSES[2]]
        flow = semantic & (ct < -300)
        report["semantic_air_candidate"] = {
            "voxels": int(flow.sum()), "volume_mL": round(float(flow.sum() * voxel_ml), 3),
            "HU_gt0_voxels": int((flow & (ct > 0)).sum()),
            "HU_purity_pass": bool(not np.any(flow & (ct > 0))),
            "HU_purity_interpretation": "construction invariant of semantic AND CT<-300; not independent validation",
            "threshold_intersection_invariant_pass": bool(not np.any(flow & ~(ct < -300))),
            "raw_semantic_HU_before_threshold": raw_hu_statistics(ct, semantic),
            "components_6_connected": component_summary(flow, voxel_ml, connectivity=6),
            "components_26_connected": component_summary(flow, voxel_ml),
            "volume_reference_mL": [15, 40],
            "volume_is_warning_only": True,
        }
        if not flow.any():
            report["hard_failures"].append("semantic air candidate is empty")
        if np.any(flow & (ct > 0)):
            report["hard_failures"].append("air candidate contains HU > 0")
        if not 15 <= float(flow.sum() * voxel_ml) <= 40:
            report["warnings"].append("candidate volume outside reference range 15-40 mL")
        nasopharynx_air = arrays["nasopharynx"] & (ct < -300)
        contact = {"interpretation": "voxel label contact only; 26-neighbor contact can be only an edge or corner"}
        paths = {"interpretation": "discrete ipsilateral label paths; no nostril/outlet endpoints or finite-caliber lumen validation"}
        for side in ("left", "right"):
            source = arrays["nasal_cavity_" + side] & (ct < -300)
            evidence = {str(n): pathway_evidence(source, nasopharynx_air, n) for n in (6, 26)}
            paths[side] = {"connectivity_6": evidence["6"], "connectivity_26": evidence["26"],
                           "diagonal_only_contact": evidence["26"]["direct_contact"] and not evidence["6"]["direct_contact"],
                           "inlet_to_outlet_patency": "not_assessed"}
            for n in (6, 26):
                contact[f"{side}_touches_nasopharynx_{n}_neighborhood"] = evidence[str(n)]["direct_contact"]
            if paths[side]["diagonal_only_contact"]:
                report["warnings"].append(side + " nasal/nasopharynx contact is diagonal only; no face-connected lumen established")
            if not evidence["6"]["largest_source_component_reaches_target"]:
                report["warnings"].append(side + " largest nasal air component has no 6-connected path to nasopharynx")
            elif evidence["6"]["source_fraction_reaching_target"] < 1:
                report["warnings"].append(side + " nasal air contains components disconnected from nasopharynx in 6-neighborhood")
        report["nasal_to_nasopharynx_contact"] = contact
        report["nasal_to_nasopharynx_paths"] = paths
    else:
        flow = np.zeros(ct.shape, dtype=bool)

    if "oropharynx" in arrays:
        oral = arrays["oropharynx"] & (ct < -300)
        overlap = int((flow & oral).sum())
        oral_summary = component_summary(oral, voxel_ml)
        report["oral_exclusion_reference"] = {
            "voxels": int(oral.sum()), "volume_mL": round(float(oral.sum() * voxel_ml), 3),
            "overlap_with_candidate_voxels": overlap,
            "components_26_connected": oral_summary,
            "components_6_connected": component_summary(oral, voxel_ml, connectivity=6),
            "separation_status": "not_proven_without_reviewed_oral_cut_plane",
        }
        if overlap:
            report["warnings"].append("semantic candidate overlaps oropharynx air label")
    else:
        oral = np.zeros(ct.shape, dtype=bool)
        report["oral_exclusion_reference"] = {"separation_status": "unavailable"}

    for name, color in (("soft_palate", "soft palate"), ("hard_palate", "hard palate")):
        if name in arrays:
            overlap = int((flow & arrays[name]).sum())
            report.setdefault("palate_reference_checks", {})[name] = {
                "overlap_with_candidate_voxels": overlap,
                "note": "reference anatomy only; does not define a CFD cut plane",
            }
            if overlap:
                report["warnings"].append(f"candidate overlaps {color} label")

    if all(name in arrays for name in ("nasal_cavity_left", "nasal_cavity_right")):
        volumes = [int((arrays[n] & (ct < -300)).sum()) for n in ("nasal_cavity_left", "nasal_cavity_right")]
        report["bilateral_reference"] = {
            "left_air_mL": round(volumes[0] * voxel_ml, 3),
            "right_air_mL": round(volumes[1] * voxel_ml, 3),
            "smaller_over_larger": round(min(volumes) / max(volumes), 4) if max(volumes) else None,
            "status": "warning_only_no_symmetry_pass_threshold",
        }

    report["openings"] = {
        name: {"status": "unknown", "review_required": True}
        for name in ("nostril_L", "nostril_R", "nasopharynx_outlet",
                     "maxillary_sinus_left", "maxillary_sinus_right", "frontal_sinus",
                     "ethmoid_sinus_left", "ethmoid_sinus_right", "sphenoid_sinus")
    }
    report["cfd_geometry_status"] = "provisional_requires_reviewed_opening_planes_and_ostia_status"

    png_path = os.path.join(out_dir, f"gate_{args.key}.png")
    try:
        save_overlay(ct, flow, oral, arrays.get("soft_palate", np.zeros_like(flow)),
                     arrays.get("hard_palate", np.zeros_like(flow)), png_path, args.key)
        report["overlay_png"] = png_path
    except Exception as exc:
        report["warnings"].append("overlay generation failed: " + str(exc))
        report["overlay_png"] = None

    report["data_integrity_status"] = "fail" if report["hard_failures"] else "pass"
    report["overall_status"] = "fail" if report["hard_failures"] else "provisional"
    report_path = os.path.join(out_dir, f"gate_{args.key}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["hard_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
