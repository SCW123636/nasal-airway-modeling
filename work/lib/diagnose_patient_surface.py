# -*- coding: utf-8 -*-
"""只读诊断患者表面与当前分割候选的绑定、拓扑和开口候选。

这个脚本不修改 STL、掩膜或审核件，也不生成体网格和 CFD 结果。它用于把
“旧表面能打开”与“当前患者几何可以进入 CFD”分开，并为下一次人工边界审核
保存可复现证据。

默认输入是项目当前的 p0 T300 候选和历史 ``airway_cfd_ready.stl``。所有
路径均可由命令行覆盖；SimpleITK 输入会先复制到 ASCII 临时目录，以规避
Windows 下非 ASCII 路径的 ITK 读写限制。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import vtk
from vtk.util.numpy_support import vtk_to_numpy

from export_candidate_preview import (
    geometry_affine as image_affine, mask_surface, read_image_local as read_image_ascii,
    triangle_arrays, validate_source_geometry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORK = PROJECT_ROOT / "work"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def index_to_physical(index_xyz: np.ndarray, affine: np.ndarray) -> np.ndarray:
    index_xyz = np.asarray(index_xyz, dtype=float)
    return index_xyz @ affine[:3, :3].T + affine[:3, 3]


def mask_summary(path: Path) -> tuple[dict, sitk.Image, np.ndarray, np.ndarray]:
    image = read_image_ascii(path)
    array = sitk.GetArrayFromImage(image)
    if array.ndim != 3 or not np.isin(array, (0, 1)).all():
        raise ValueError("mask must be a binary 3-D image")
    mask = np.asarray(array != 0)
    if not mask.any():
        raise ValueError("mask is empty")
    affine = image_affine(image)
    zyx = np.argwhere(mask)
    xyz = zyx[:, ::-1]
    low = xyz.min(axis=0)
    high = xyz.max(axis=0)
    # Include half a voxel around the first and last nonzero voxel.
    corners = np.asarray(
        [
            [x, y, z]
            for x in (low[0] - 0.5, high[0] + 0.5)
            for y in (low[1] - 0.5, high[1] + 0.5)
            for z in (low[2] - 0.5, high[2] + 0.5)
        ],
        dtype=float,
    )
    physical = index_to_physical(corners, affine)
    voxel_volume = abs(float(np.linalg.det(affine[:3, :3])))
    result = {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_xyz": list(image.GetSize()),
        "spacing_xyz_mm": list(image.GetSpacing()),
        "origin_xyz_mm": list(image.GetOrigin()),
        "direction": list(image.GetDirection()),
        "coordinate_system": "LPS",
        "unit": "mm",
        "nonzero_voxels": int(mask.sum()),
        "voxel_volume_mm3": voxel_volume,
        "volume_mm3": float(mask.sum() * voxel_volume),
        "index_bounds_inclusive_xyz": {"min": low.tolist(), "max": high.tolist()},
        "bounds_lps_mm": {"min": physical.min(axis=0).tolist(), "max": physical.max(axis=0).tolist()},
    }
    return result, image, mask, affine


def component_sizes(poly: vtk.vtkPolyData) -> list[int]:
    connectivity = vtk.vtkPolyDataConnectivityFilter()
    connectivity.SetInputData(poly)
    connectivity.SetExtractionModeToAllRegions()
    connectivity.ColorRegionsOn()
    connectivity.Update()
    connected = connectivity.GetOutput()
    _, triangles = triangle_arrays(connected)
    cell_regions = connected.GetCellData().GetArray("RegionId")
    point_regions = connected.GetPointData().GetArray("RegionId")
    if cell_regions is not None:
        regions = vtk_to_numpy(cell_regions)
    elif point_regions is not None:
        regions = vtk_to_numpy(point_regions)[triangles[:, 0]]
    else:
        raise RuntimeError("VTK connectivity output has no region IDs")
    _, counts = np.unique(regions, return_counts=True)
    return sorted([int(value) for value in counts], reverse=True)


def surface_summary(path: Path) -> tuple[dict, vtk.vtkPolyData]:
    reader = vtk.vtkSTLReader()
    reader.SetFileName(str(path))
    reader.Update()
    poly = vtk.vtkPolyData()
    poly.DeepCopy(reader.GetOutput())
    points, triangles = triangle_arrays(poly)
    a = points[triangles[:, 0]]
    b = points[triangles[:, 1]]
    c = points[triangles[:, 2]]
    cross = np.cross(b - a, c - a)
    areas = 0.5 * np.linalg.norm(cross, axis=1)
    edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]))
    directed = edges.copy()
    edges.sort(axis=1)
    _, inverse, edge_counts = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
    signs = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    balance = np.bincount(inverse, weights=signs)
    winding_errors = int(np.count_nonzero((edge_counts == 2) & (balance != 0)))
    canonical_faces = np.sort(triangles, axis=1)
    duplicate_triangles = len(triangles) - len(np.unique(canonical_faces, axis=0))
    boundary_edges = int(np.count_nonzero(edge_counts == 1))
    nonmanifold_edges = int(np.count_nonzero(edge_counts > 2))
    lengths = np.stack(
        [np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)],
        axis=1,
    )
    # Minimum angle is a more interpretable triangle-quality statistic than only area.
    cosines = []
    for opposite, side1, side2 in ((a, b, c), (b, c, a), (c, a, b)):
        u = side1 - opposite
        v = side2 - opposite
        denominator = np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1)
        cosines.append(np.clip(np.divide(np.einsum("ij,ij->i", u, v), denominator,
                                         out=np.ones_like(denominator), where=denominator > 0), -1, 1))
    min_angles = np.degrees(np.arccos(np.stack(cosines, axis=1))).min(axis=1)
    mass = vtk.vtkMassProperties()
    mass.SetInputData(poly)
    mass.Update()
    closed = boundary_edges == 0 and nonmanifold_edges == 0
    result = {
        "path": str(path),
        "sha256": sha256_file(path),
        "points": int(len(points)),
        "triangles": int(len(triangles)),
        "components": component_sizes(poly),
        "bounds_lps_or_surface_mm": {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()},
        "extent_mm": np.ptp(points, axis=0).tolist(),
        "center_mm": points.mean(axis=0).tolist(),
        "surface_area_mm2": float(areas.sum()),
        "closed_by_edge_counts": closed,
        "boundary_edges": boundary_edges,
        "nonmanifold_edges": nonmanifold_edges,
        "inconsistent_winding_edges": winding_errors,
        "duplicate_triangles": int(duplicate_triangles),
        "degenerate_triangles": int(np.count_nonzero(areas <= 1e-12)),
        "triangle_area_percentiles_mm2": np.percentile(areas, [0, 1, 5, 50, 95, 99, 100]).tolist(),
        "edge_length_percentiles_mm": np.percentile(lengths, [0, 1, 5, 50, 95, 99, 100]).tolist(),
        "minimum_angle_percentiles_deg": np.percentile(min_angles, [0, 1, 5, 50, 95, 99, 100]).tolist(),
        "enclosed_volume_mm3": float(mass.GetVolume()) if closed else None,
        "volume_method": "vtkMassProperties; numerical estimate, self-intersection checked separately",
        "self_intersection_check": "not_performed_by_this_script",
    }
    return result, poly


def plane_probe(poly: vtk.vtkPolyData, planes: dict, voxel_points=None, voxel_volume=None) -> dict:
    points, triangles = triangle_arrays(poly)
    output = {}
    for name, spec in planes.items():
        if "point_lps_mm" not in spec and "same_boundary_as" in spec:
            output[name] = {"status": "alias", "same_boundary_as": spec["same_boundary_as"]}
            continue
        point = np.asarray(spec.get("point_lps_mm", []), dtype=float)
        normal = np.asarray(spec.get("normal_lps", []), dtype=float)
        if point.shape != (3,) or normal.shape != (3,) or not np.isfinite(np.r_[point, normal]).all():
            output[name] = {"status": "invalid_proposal"}
            continue
        norm = float(np.linalg.norm(normal))
        if norm <= 1e-12:
            output[name] = {"status": "invalid_proposal", "reason": "zero normal"}
            continue
        normal /= norm
        signed_vertices = (points - point) @ normal
        signed_triangles = (points[triangles] - point) @ normal
        crossing = np.any(signed_triangles >= 0, axis=1) & np.any(signed_triangles < 0, axis=1)
        plane = vtk.vtkPlane()
        plane.SetOrigin(*point)
        plane.SetNormal(*normal)
        cutter = vtk.vtkCutter()
        cutter.SetCutFunction(plane)
        cutter.SetInputData(poly)
        cutter.Update()
        roi = spec.get("roi_lps_mm", {})
        low, high = np.asarray(roi.get("min", [])), np.asarray(roi.get("max", []))
        if low.shape != (3,) or high.shape != (3,) or not np.isfinite(np.r_[low, high]).all() or np.any(low >= high):
            raise ValueError(name + " needs finite ROI bounds")
        box = vtk.vtkBox()
        box.SetBounds(*np.column_stack((low, high)).ravel())
        clip = vtk.vtkClipPolyData()
        clip.SetInputConnection(cutter.GetOutputPort())
        clip.SetClipFunction(box)
        clip.InsideOutOn()
        clip.Update()
        stripper = vtk.vtkStripper()
        stripper.SetInputConnection(clip.GetOutputPort())
        stripper.JoinContiguousSegmentsOn()
        stripper.Update()
        cut = stripper.GetOutput()
        lengths = []
        for idx in range(cut.GetNumberOfCells()):
            cell = cut.GetCell(idx)
            q = np.asarray([cut.GetPoint(cell.GetPointId(j)) for j in range(cell.GetNumberOfPoints())])
            if len(q) > 1:
                lengths.append(float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum()))
        output[name] = {
            "status": "exploratory_only",
            "signed_vertex_distance_percentiles_mm": np.percentile(
                signed_vertices, [0, 1, 5, 50, 95, 99, 100]
            ).tolist(),
            "positive_vertex_fraction": float(np.mean(signed_vertices >= 0)),
            "global_crossing_triangles_reference_only": int(np.count_nonzero(crossing)),
            "roi_cut_polyline_cells": int(cut.GetNumberOfCells()),
            "roi_cut_polyline_lengths_mm_desc": sorted(lengths, reverse=True),
            "roi_cut_polyline_total_length_mm": float(sum(lengths)),
            "roi_lps_mm": roi,
            "warning": "proposal has not been medically confirmed and was not applied",
        }
        if voxel_points is not None:
            inside = ((voxel_points >= low) & (voxel_points <= high)).all(axis=1)
            signed = (voxel_points - point) @ normal
            removed = inside & (signed < 0 if spec.get("keep_positive", True) else signed > 0)
            output[name]["predicted_removed_voxels_in_roi"] = int(removed.sum())
            output[name]["predicted_removed_volume_mm3"] = float(removed.sum() * voxel_volume)
    return output


def compare_geometry(surface: dict, mask: dict) -> dict:
    surf_extent = np.asarray(surface["extent_mm"], dtype=float)
    mask_bounds = mask["bounds_lps_mm"]
    mask_extent = np.asarray(mask_bounds["max"], dtype=float) - np.asarray(mask_bounds["min"], dtype=float)
    surf_center = np.asarray(surface["center_mm"], dtype=float)
    mask_center = (np.asarray(mask_bounds["min"], dtype=float) + np.asarray(mask_bounds["max"], dtype=float)) / 2
    extent_relative = np.divide(surf_extent - mask_extent, mask_extent,
                                out=np.full(3, np.nan), where=mask_extent != 0)
    volume_ratio = None
    if surface.get("enclosed_volume_mm3") and mask.get("volume_mm3"):
        volume_ratio = float(surface["enclosed_volume_mm3"] / mask["volume_mm3"])
    return {
        "surface_extent_mm": surf_extent.tolist(),
        "mask_extent_mm": mask_extent.tolist(),
        "extent_relative_difference": extent_relative.tolist(),
        "surface_center_mm": surf_center.tolist(),
        "mask_center_mm": mask_center.tolist(),
        "center_distance_mm": float(np.linalg.norm(surf_center - mask_center)),
        "surface_to_mask_volume_ratio": volume_ratio,
        "comparison_scope": "Descriptive only; numerical similarity cannot certify provenance or registration",
    }


def make_report(args: argparse.Namespace) -> dict:
    surface_path = Path(args.surface).resolve()
    mask_path = Path(args.mask).resolve()
    if not surface_path.is_file() or not mask_path.is_file():
        raise FileNotFoundError("surface and mask must both exist")
    surface, _ = surface_summary(surface_path)
    mask, image, mask_array, affine = mask_summary(mask_path)
    mask_poly, _ = mask_surface(image)
    review = read_json(Path(args.review)) if args.review and Path(args.review).is_file() else {}
    gate = read_json(Path(args.gate)) if args.gate and Path(args.gate).is_file() else {}
    manifest = read_json(Path(args.manifest)) if args.manifest and Path(args.manifest).is_file() else {}
    if manifest:
        validate_source_geometry(image, manifest)
    voxel_points = index_to_physical(np.argwhere(mask_array)[:, ::-1], affine)
    if args.exploration_dir:
        destination = Path(args.exploration_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        candidate_stl = destination / "p0_T300_provisional_envelope.stl"
        writer = vtk.vtkSTLWriter()
        writer.SetFileName(str(candidate_stl))
        writer.SetFileTypeToBinary()
        writer.SetInputData(mask_poly)
        if writer.Write() != 1:
            raise RuntimeError("Diagnostic STL export failed")
        mask["diagnostic_surface"] = {"path": str(candidate_stl), "sha256": sha256_file(candidate_stl),
                                      "scope": "unreviewed envelope only; not a CFD input"}

    openings = gate.get("openings") or manifest.get("openings") or review.get("openings") or {}
    plane_specs = review.get("planes_lps", {}) if review else {}
    plane_status = {name: spec.get("status") for name, spec in plane_specs.items()
                    if isinstance(spec, dict) and "point_lps_mm" in spec}
    blockers = []
    comparison = compare_geometry(surface, mask)
    blockers.append("surface_source_and_transform_binding_not_supplied")
    blockers.append("boundary_patch_semantics_not_supplied")
    if gate.get("manual_review_required") is True or gate.get("medical_or_cfd_validation_pass") is not True:
        blockers.append("medical_or_cfd_review_not_passed")
    if any(value != "confirmed" for value in plane_status.values()) or len(plane_status) < 3:
        blockers.append("nostril_and_nasopharynx_planes_not_confirmed")
    if any((spec or {}).get("status", "unknown") == "unknown" for spec in openings.values()):
        blockers.append("one_or_more_opening_semantics_unknown")
    return {
        "schema": "patient_surface_diagnostic/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked",
        "patient_cfd_allowed": False,
        "patient_cfd_results": 0,
        "inputs": {
            "surface": surface,
            "current_mask": mask,
            "manifest": str(Path(args.manifest).resolve()) if args.manifest else None,
            "review": str(Path(args.review).resolve()) if args.review else None,
            "gate": str(Path(args.gate).resolve()) if args.gate else None,
            "metadata_sha256": {name: sha256_file(Path(path)) for name, path in
                                (("manifest", args.manifest), ("review", args.review), ("gate", args.gate))
                                if path and Path(path).is_file()},
        },
        "geometry_comparison": comparison,
        "surface_topology": {
            "closed_surface_is_not_a_cfd_boundary_pass": True,
            "interpretation": "Closure alone is not a failure: a closed CFD boundary needs separately labelled inlet/outlet caps and wall. This STL has no supplied patch mapping.",
        },
        "review_state": {
            "gate_status": gate.get("overall_status"),
            "manual_review_required": gate.get("manual_review_required"),
            "medical_or_cfd_validation_pass": gate.get("medical_or_cfd_validation_pass"),
            "opening_statuses": openings,
            "proposed_plane_statuses": plane_status,
        },
        "proposed_plane_probe": plane_probe(mask_poly, plane_specs, voxel_points, mask["voxel_volume_mm3"]),
        "blockers": blockers,
        "next_action": [
            "Use 3D Slicer 5.12.4 Segmentations/Markups to review the p0 CT, T300 candidate and the three proposed planes.",
            "Record confirmed nostril_L, nostril_R and nasopharynx_outlet planes plus oral exclusion and sinus policy.",
            "Generate a new geometry from the reviewed mask; do not reuse airway_cfd_ready.stl.",
            "Attach patch labels, run external volume meshing, repair only proven boundary tetrahedra, then run OpenFOAM checkMesh.",
        ],
    }


def markdown(report: dict) -> str:
    surface = report["inputs"]["surface"]
    mask = report["inputs"]["current_mask"]
    comparison = report["geometry_comparison"]
    lines = [
        "# 患者表面只读诊断",
        "",
        f"生成时间（UTC）：{report['generated_at']}",
        "",
        "## 结论",
        "",
        f"状态：**{report['status']}**；患者 CFD 仍为 **0**。",
        "",
        "当前 `airway_cfd_ready.stl` 不能作为患者 CFD 输入。它是闭合单一表面，没有 inlet/outlet/wall 分区，且与当前 p0 T300 候选没有可追溯的坐标和几何绑定。",
        "",
        "## 可核验事实",
        "",
        f"- 旧 STL：{surface['path']}；SHA-256 `{surface['sha256']}`；{surface['triangles']} 三角形；边界边 {surface['boundary_edges']}；非流形边 {surface['nonmanifold_edges']}；闭合体积 {surface['enclosed_volume_mm3']:.3f} mm³。",
        f"- 当前掩膜：{mask['path']}；SHA-256 `{mask['sha256']}`；{mask['nonzero_voxels']} 个体素；体积 {mask['volume_mm3']:.3f} mm³；物理范围 {mask['bounds_lps_mm']}。",
        f"- 表面顶点平均中心与掩膜包围盒中心距离：{comparison['center_distance_mm']:.3f} mm；体积比（STL/掩膜）：{comparison['surface_to_mask_volume_ratio']!s}。这些是描述性对照，不作为注册或来源认证。",
        f"- 当前审核状态：gate={report['review_state']['gate_status']}，manual_review_required={report['review_state']['manual_review_required']}，medical_or_cfd_validation_pass={report['review_state']['medical_or_cfd_validation_pass']}。",
        "",
        "## 阻断项",
        "",
    ]
    lines.extend(f"- `{item}`" for item in report["blockers"])
    lines.extend([
        "",
        "## 软件路线",
        "",
        "本机已有 3D Slicer 5.12.4，最适合做当前缺失的人工解剖确认：在 CT、语义分割和 Markups 平面同屏检查三端开口及口腔排除；Surface Toolbox/Segmentations 用于生成审核后的表面。体网格仍采用已经在解析圆管上通过验证的 Netgen→局部拓扑修复→OpenFOAM checkMesh 路线。SimScale 等云端网格器可作为备选，但导出后仍必须通过同一套本地门禁，不能绕过医学审核。",
        "",
        "## 下一步",
        "",
    ])
    lines.extend(f"- {item}" for item in report["next_action"])
    lines.extend([
        "",
        "闭合本身不构成失败；体网格需要闭合边界及独立标记的入口、出口端面和 wall。候选平面按现有规则限制在 ROI 内探测，统计只用于发现问题，不构成医学确认，也没有应用任何裁剪。",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", default=str(WORK / "04_cfd_ready" / "airway_cfd_ready.stl"))
    parser.add_argument("--mask", default=str(WORK / "05_ts_seg" / "p0" / "anatomy" / "main_nasal_airway_T300_provisional.nii.gz"))
    parser.add_argument("--manifest", default=str(WORK / "05_ts_seg" / "p0" / "anatomy" / "manifest.json"))
    parser.add_argument("--review", default=str(WORK / "06_auto_landmarks" / "p0" / "review_config_proposed.json"))
    parser.add_argument("--gate", default=str(WORK / "05_ts_seg" / "p0" / "gate_p0.json"))
    parser.add_argument("--out-json", default=str(WORK / "07_cfd_pipeline" / "patient_surface_diagnostic.json"))
    parser.add_argument("--out-md", default=str(WORK / "07_cfd_pipeline" / "患者表面只读诊断.md"))
    parser.add_argument("--exploration-dir", help="Optional ASCII directory for an unreviewed diagnostic STL")
    args = parser.parse_args(argv)
    report = make_report(args)
    json_dump(Path(args.out_json), report)
    Path(args.out_md).write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "blockers": report["blockers"],
                      "out_json": str(Path(args.out_json).resolve()),
                      "out_md": str(Path(args.out_md).resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
