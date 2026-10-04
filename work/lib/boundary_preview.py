"""Physical-space CT draft previews, never an anatomical or CFD approval.

An incomplete source can be explored, but only a runner-bound draft with an
explicit sinus exclusion mask has status generated and can support review.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import itertools
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

import numpy as np
from PIL import Image, ImageDraw
import SimpleITK as sitk

from anatomy_barrier_seg import geometry_equal, plane_keep_mask, save_mask
from boundary_review import (IDENTITY_FIELDS, OPENINGS, parameters_sha256,
                             sha256_file, validate_cutting_planes)
from export_candidate_preview import geometry_affine, image_geometry, read_image_local

VIEWS = {
    "axial": ([1, 0, 0], [0, 1, 0]),
    "coronal": ([1, 0, 0], [0, 0, -1]),
    "sagittal": ([0, 1, 0], [0, 0, -1]),
}
COLORS = {"nostril_L": (45, 211, 129), "nostril_R": (77, 165, 255),
          "nasopharynx_outlet": (255, 197, 68), "oral": (250, 95, 140)}
SINUS_REGIONS = {"maxillary", "frontal", "ethmoid", "sphenoid"}


def validate_image(image, name, reference=None, binary=False):
    if image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
        raise ValueError(name + " must be a scalar 3-D image")
    affine = geometry_affine(image)
    direction = np.asarray(image.GetDirection()).reshape(3, 3)
    if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-5, rtol=0):
        raise ValueError(name + " direction must be orthonormal")
    if reference is not None and not geometry_equal(image, reference):
        raise ValueError(name + " geometry differs from CT; explicit upstream alignment required")
    values = sitk.GetArrayViewFromImage(image)
    if not np.isfinite(values).all() or (binary and not np.isin(values, (0, 1)).all()):
        raise ValueError(name + " contains nonfinite or nonbinary values")
    return affine


def slice_grid(point, u, v, *, pixels=257, field_mm=80.0):
    """The middle pixel is the exact LPS focus; columns follow u, rows follow v."""
    if (type(pixels) is not int or pixels < 33 or pixels > 1025 or pixels % 2 != 1
            or not np.isfinite(field_mm) or not 5 <= field_mm <= 300):
        raise ValueError("Use an odd pixel count 33..1025 and field_mm 5..300")
    point, u, v = (np.asarray(value, dtype=float) for value in (point, u, v))
    if any(value.shape != (3,) or not np.isfinite(value).all() for value in (point, u, v)):
        raise ValueError("Slice point and axes must contain three finite values")
    if not np.isclose(np.linalg.norm(u), 1) or not np.isclose(np.linalg.norm(v), 1) or abs(u @ v) > 1e-8:
        raise ValueError("Slice axes must be orthonormal")
    step = float(field_mm / (pixels - 1))
    origin = point - (u + v) * field_mm / 2
    direction = np.column_stack((u, v, np.cross(u, v)))
    grid = sitk.Image([pixels, pixels, 1], sitk.sitkUInt8)
    grid.SetOrigin(origin.tolist())
    grid.SetSpacing([step, step, step])
    grid.SetDirection(direction.ravel().tolist())
    return grid


def resample_slice(image, grid, *, label=False):
    interpolator = sitk.sitkNearestNeighbor if label else sitk.sitkLinear
    pixel_type = sitk.sitkUInt8 if label else sitk.sitkFloat32
    default = 0 if label else -1000
    result = sitk.Resample(image, grid, sitk.Transform(3, sitk.sitkIdentity),
                           interpolator, default, pixel_type)
    return sitk.GetArrayFromImage(result)[0]


def slice_points(grid):
    width, height, _ = grid.GetSize()
    col, row = np.meshgrid(np.arange(width), np.arange(height))
    indices = np.stack((col, row, np.zeros_like(col)), axis=-1)
    affine = geometry_affine(grid)
    return indices @ affine[:3, :3].T + affine[:3, 3]


def plane_slice_masks(points, plane, line_mm):
    normal = np.asarray(plane["normal_lps"], dtype=float)
    normal /= np.linalg.norm(normal)
    roi = plane["roi_lps_mm"]
    inside = ((points >= roi["min"]) & (points <= roi["max"])).all(axis=-1)
    signed = (points - plane["point_lps_mm"]) @ normal
    kept = signed >= 0 if plane["keep_positive"] else signed <= 0
    return inside & ~kept, inside & (np.abs(signed) <= line_mm)


def blend(rgb, mask, color, alpha):
    rgb[mask] = rgb[mask] * (1 - alpha) + np.asarray(color) * alpha


def plane_basis(normal):
    n = np.asarray(normal, dtype=float)
    n /= np.linalg.norm(n)
    seed = np.eye(3)[np.argmin(np.abs(n))]
    u = np.cross(seed, n)
    u /= np.linalg.norm(u)
    return u, np.cross(n, u)


def render_panel(ct, airway, sinus, grid, planes, title, *, mode="all"):
    hu = resample_slice(ct, grid)
    original = resample_slice(airway, grid, label=True) > 0
    gray = np.clip((hu + 1000) / 1600, 0, 1) * 255
    rgb = np.repeat(gray[:, :, None], 3, axis=2)
    blend(rgb, original, (49, 203, 205), 0.30)
    points = slice_points(grid)
    for key, plane in planes.items():
        if mode == "sinus":
            continue
        removed, line = plane_slice_masks(points, plane, grid.GetSpacing()[0] * 0.55)
        blend(rgb, removed & original, COLORS[key], 0.52)
        blend(rgb, line, COLORS[key], 0.92)
    if sinus is not None and mode in ("all", "sinus"):
        excluded = resample_slice(sinus, grid, label=True) > 0
        blend(rgb, excluded, (242, 102, 245), 0.65)
    panel = Image.fromarray(np.uint8(np.clip(rgb, 0, 255)))
    result = Image.new("RGB", (panel.width, panel.height + 42), (20, 23, 28))
    result.paste(panel, (0, 42))
    draw = ImageDraw.Draw(result)
    draw.text((8, 7), title, fill="white")
    axes = np.asarray(grid.GetDirection()).reshape(3, 3)
    labels = []
    for vector in (axes[:, 0], axes[:, 1]):
        axis = int(np.argmax(np.abs(vector)))
        labels.append(("L", "P", "S")[axis] if vector[axis] > 0 else ("R", "A", "I")[axis])
    draw.text((8, 24), "right: " + labels[0] + "  down: " + labels[1], fill=(190, 199, 209))
    mid = panel.width // 2
    draw.line((mid - 5, mid + 42, mid + 5, mid + 42), fill="white", width=1)
    draw.line((mid, mid + 37, mid, mid + 47), fill="white", width=1)
    metadata = {"title": title, "grid": image_geometry(grid),
                "focus_lps_mm": list(grid.TransformIndexToPhysicalPoint((mid, mid, 0))),
                "ct_center_HU": float(hu[mid, mid]), "airway_center": bool(original[mid, mid])}
    return result, metadata


def montage(panels, path, banner):
    width, height = panels[0].size
    image = Image.new("RGB", (width * len(panels), height + 54), (20, 23, 28))
    draw = ImageDraw.Draw(image)
    draw.text((8, 7), banner, fill=(255, 197, 68))
    draw.text((8, 26), "Cyan: source airway | colored lines: planes | colored airway: removed side | magenta: sinus mask", fill="white")
    for i, panel in enumerate(panels):
        image.paste(panel, (i * width, 54))
    image.save(path)


def validate_controls(controls, ct):
    validate_cutting_planes(controls.get("openings"), controls.get("oral_exclusion"))
    planes = dict(controls["openings"])
    if controls["oral_exclusion"]["mode"] == "separate_plane":
        planes["oral"] = controls["oral_exclusion"]["boundary"]
    for key, plane in planes.items():
        point = np.asarray(plane["point_lps_mm"])
        roi = plane["roi_lps_mm"]
        if not ((point >= roi["min"]) & (point <= roi["max"])).all():
            raise ValueError(key + " focus is outside CT or its ROI")
        index = np.asarray(ct.TransformPhysicalPointToContinuousIndex(point.tolist()))
        if np.any(index < 0) or np.any(index > np.asarray(ct.GetSize()) - 1):
            raise ValueError(key + " focus is outside CT")
    sinus = controls.get("sinus_policy", {})
    if sinus.get("policy") != "exclude_sinuses" or set(sinus.get("regions", [])) != SINUS_REGIONS:
        raise ValueError("The G_main draft must explicitly consider maxillary, frontal, ethmoid and sphenoid regions")
    return planes


def generate_preview(ct_path, airway_path, controls, output, *, sinus_path=None,
                     binding=None, pixels=513, field_mm=80.0):
    """Publish a unique draft only after all input hashes remain unchanged."""
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("Draft directory already exists; retain it and use a new id")
    controls = copy.deepcopy(controls)
    paths = {"ct": Path(ct_path).resolve(), "airway": Path(airway_path).resolve()}
    if sinus_path is not None:
        paths["sinus_exclusion"] = Path(sinus_path).resolve()
    before = {key: sha256_file(path) for key, path in paths.items()}
    if binding is not None:
        if (not isinstance(binding, dict) or set(binding) != set(IDENTITY_FIELDS)
                or any(binding.get(key) is None for key in IDENTITY_FIELDS)
                or binding["ct_sha256"] != before["ct"]):
            raise ValueError("Complete runner binding must match the CT source")
        if sinus_path is None:
            raise ValueError("Reviewable drafts require an explicit sinus exclusion mask")
    ct = read_image_local(paths["ct"])
    validate_image(ct, "CT")
    airway = read_image_local(paths["airway"])
    validate_image(airway, "airway", ct, binary=True)
    if not np.any(sitk.GetArrayViewFromImage(airway)):
        raise ValueError("Cannot preview an empty airway")
    sinus = read_image_local(paths["sinus_exclusion"]) if sinus_path is not None else None
    if sinus is not None:
        validate_image(sinus, "sinus exclusion", ct, binary=True)
    planes = validate_controls(controls, ct)
    controls["sinus_policy"]["mask_sha256"] = before.get("sinus_exclusion")
    # Validate display limits before allocating images or creating a draft folder.
    slice_grid(planes["nostril_L"]["point_lps_mm"], *VIEWS["axial"], pixels=pixels, field_mm=field_mm)
    status = "generated" if binding is not None else "exploratory"
    banner = "DRAFT - anatomy unreviewed; CFD locked" if binding is not None else "EXPLORATORY - no landmark approval; CFD locked"
    if sinus is None:
        banner += " | SINUS MASK MISSING"
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".boundary_preview_", dir=output.parent))
    try:
        outputs, panels_meta = {}, {}
        for view, axes in VIEWS.items():
            panels, metadata = [], []
            for key in OPENINGS:
                grid = slice_grid(planes[key]["point_lps_mm"], *axes, pixels=pixels, field_mm=field_mm)
                panel, meta = render_panel(ct, airway, sinus, grid, planes, key + " / " + view)
                panels.append(panel); metadata.append(meta)
            montage(panels, stage / (view + ".png"), banner)
            panels_meta[view] = metadata
        for name, focus, mode in (("oral_overlay", planes.get("oral", planes["nasopharynx_outlet"]), "oral"),
                                   ("sinus_overlay", planes["nasopharynx_outlet"], "sinus")):
            panels, metadata = [], []
            for view, axes in VIEWS.items():
                grid = slice_grid(focus["point_lps_mm"], *axes, pixels=pixels, field_mm=field_mm)
                shown = {"oral": focus} if mode == "oral" else {}
                panel, meta = render_panel(ct, airway, sinus, grid, shown, name + " / " + view, mode=mode)
                panels.append(panel); metadata.append(meta)
            montage(panels, stage / (name + ".png"), banner)
            panels_meta[name] = metadata
        panels, metadata = [], []
        for key in OPENINGS:
            grid = slice_grid(planes[key]["point_lps_mm"], *plane_basis(planes[key]["normal_lps"]),
                              pixels=pixels, field_mm=field_mm)
            panel, meta = render_panel(ct, airway, sinus, grid, {key: planes[key]}, key + " / plane")
            panels.append(panel); metadata.append(meta)
        montage(panels, stage / "openings_overlay.png", banner)
        panels_meta["openings_overlay"] = metadata
        if sinus is not None:
            shutil.copyfile(paths["sinus_exclusion"], stage / "sinus_exclusion_mask.nii.gz")
        kept = sitk.GetArrayFromImage(airway).astype(bool)
        original_count = int(kept.sum())
        for plane in planes.values():
            kept &= plane_keep_mask(ct, plane, kept.shape)
        if sinus is not None:
            kept &= sitk.GetArrayViewFromImage(sinus) == 0
        if not kept.any():
            raise ValueError("Cutting controls remove the entire airway")
        save_mask(ct, kept, str(stage / "draft_airway.nii.gz"))
        for path in stage.iterdir():
            key = path.name.split(".")[0]
            outputs[key] = {"path": path.name, "sha256": sha256_file(path)}
        manifest = {
            "schema": "boundary_draft_preview/v1", "status": status,
            "binding": binding, "coordinate_system": "LPS", "unit": "mm",
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "parameters_sha256": parameters_sha256(controls), "controls": controls,
            "source_sha256": before, "outputs": outputs, "panels": panels_meta,
            "source_geometry": image_geometry(ct), "cfd_ready": False,
            "landmark_approval_present": binding is not None,
            "sinus_scope_resolved": sinus is not None,
            "voxel_counts": {"source": original_count, "draft": int(kept.sum())},
            "generator_sha256": sha256_file(__file__), "SimpleITK_version": sitk.Version_VersionString(),
            "operations": {"ct_interpolation": "linear", "mask_interpolation": "nearest_neighbor",
                           "display_window_HU": [-1000, 600], "outside_CT_HU": -1000,
                           "clip": "voxel-center halfspace within LPS ROI; unchanged outside ROI",
                           "source_modified": False, "smoothing": False},
            "limitations": ["Draft mask is not a closed, partitioned CFD surface.",
                            "Slice panels show selected locations, not complete sinus or oral scope.",
                            "Sinus mask presence does not establish anatomical validity."],
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if any(sha256_file(path) != before[key] for key, path in paths.items()):
            raise ValueError("Source changed during generation; draft was not published")
        os.replace(stage, output)
        return manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    # CLI requests are exploratory; reviewable binding is resolved by the runner.
    result = generate_preview(request["ct_path"], request["airway_path"], request["controls"], args.output,
                              sinus_path=request.get("sinus_path"), pixels=request.get("pixels", 513),
                              field_mm=request.get("field_mm", 80.0))
    print(json.dumps({"status": result["status"], "output": str(args.output),
                      "cfd_ready": False, "voxel_counts": result["voxel_counts"]}))


if __name__ == "__main__":
    main()
