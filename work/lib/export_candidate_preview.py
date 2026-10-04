# -*- coding: utf-8 -*-
"""Export real provisional binary masks as local display-only LPS/mm surfaces.

No input mask, landmark decision, opening, or CFD case is modified. Binary-mask
envelopes have no anatomical inlet/outlet meaning. This is not CFD meshing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray, vtk_to_numpy


DEFAULT_CASES = ("p0", "p1", "p2", "p3", "p3t1")
WORK = Path(__file__).resolve().parents[1]
DISPLAY_NOTES = [
    "Display-only envelope of an unreviewed provisional binary air mask.",
    "No nostril inlet, nasopharyngeal outlet, or sinus opening has been confirmed.",
    "The binary isosurface may appear closed; closure does not validate a CFD boundary.",
    "No hole filling, smoothing, resampling, largest-component removal, or manual plane is applied here.",
    "The viewer mesh is decimated for display and must not be used as a CFD input.",
]


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def geometry_affine(image):
    spacing = np.asarray(image.GetSpacing(), dtype=np.float64)
    direction = np.asarray(image.GetDirection(), dtype=np.float64).reshape(3, 3)
    origin = np.asarray(image.GetOrigin(), dtype=np.float64)
    if (image.GetDimension() != 3 or not np.isfinite(spacing).all()
            or not np.isfinite(direction).all() or not np.isfinite(origin).all()
            or np.any(spacing <= 0) or abs(float(np.linalg.det(direction))) < 1e-8):
        raise ValueError("Image needs finite, nonsingular 3-D geometry and positive spacing")
    affine = np.eye(4, dtype=np.float64)
    affine[:3, :3] = direction @ np.diag(spacing)
    affine[:3, 3] = origin
    return affine


def image_geometry(image):
    return {"size_xyz": list(image.GetSize()), "spacing_xyz_mm": list(image.GetSpacing()),
            "origin_xyz_mm": list(image.GetOrigin()), "direction": list(image.GetDirection())}


def read_image_local(path):
    """Stage only for I/O compatibility with Windows Unicode NIfTI paths."""
    with tempfile.TemporaryDirectory(prefix="nasal_preview_read_") as tmp:
        staged = Path(tmp) / "mask.nii.gz"
        shutil.copyfile(path, staged)
        return sitk.ReadImage(str(staged))


def triangle_arrays(poly):
    points = np.asarray(vtk_to_numpy(poly.GetPoints().GetData()), dtype=np.float64)
    cells = poly.GetPolys()
    offsets = vtk_to_numpy(cells.GetOffsetsArray())
    connectivity = vtk_to_numpy(cells.GetConnectivityArray())
    if not len(connectivity) or not np.all(np.diff(offsets) == 3):
        raise ValueError("Expected a nonempty triangle surface")
    triangles = np.asarray(connectivity.reshape(-1, 3), dtype=np.int64)
    if np.any(triangles < 0) or np.any(triangles >= len(points)) or not np.isfinite(points).all():
        raise ValueError("Mesh has invalid triangle indices or nonfinite points")
    return points, triangles


def set_triangle_arrays(poly, points, triangles):
    vtk_points = vtk.vtkPoints()
    vtk_points.SetData(numpy_to_vtk(np.ascontiguousarray(points, dtype=np.float64), deep=True))
    offsets = np.arange(0, 3 * (len(triangles) + 1), 3, dtype=np.int64)
    vtk_cells = vtk.vtkCellArray()
    vtk_cells.SetData(numpy_to_vtkIdTypeArray(offsets, deep=True),
                      numpy_to_vtkIdTypeArray(np.ascontiguousarray(triangles).ravel(), deep=True))
    poly.SetPoints(vtk_points)
    poly.SetPolys(vtk_cells)
    poly.Modified()


def mask_surface(image):
    """Extract in original voxel-index space, then apply the complete LPS affine."""
    array = sitk.GetArrayFromImage(image)
    if array.ndim != 3 or not np.isin(array, (0, 1)).all():
        raise ValueError("Preview input must be a 3-D binary 0/1 mask")
    z, y, x = np.nonzero(array)
    if not len(x):
        raise ValueError("Cannot preview an empty mask")
    low_zyx = np.asarray([z.min(), y.min(), x.min()], dtype=int)
    high_zyx = np.asarray([z.max(), y.max(), x.max()], dtype=int)
    bounds = tuple(slice(int(lo), int(hi) + 1) for lo, hi in zip(low_zyx, high_zyx))
    cropped = np.pad(array[bounds].astype(np.uint8), 1, mode="constant")
    index_origin_xyz = low_zyx[::-1] - 1
    vtk_image = vtk.vtkImageData()
    vtk_image.SetDimensions(*cropped.shape[::-1])
    vtk_image.SetOrigin(*[float(n) for n in index_origin_xyz])
    vtk_image.SetSpacing(1.0, 1.0, 1.0)
    vtk_image.GetPointData().SetScalars(numpy_to_vtk(cropped.ravel(order="C"), deep=True))
    mc = vtk.vtkDiscreteMarchingCubes()
    mc.SetInputData(vtk_image)
    mc.SetValue(0, 1)
    mc.ComputeNormalsOff()
    mc.ComputeGradientsOff()
    mc.ComputeScalarsOff()
    mc.Update()
    poly = vtk.vtkPolyData()
    poly.DeepCopy(mc.GetOutput())
    index_points, triangles = triangle_arrays(poly)
    affine = geometry_affine(image)
    physical_points = index_points @ affine[:3, :3].T + affine[:3, 3]
    # A reflection reverses winding. Restore the index-isosurface orientation.
    reversed_winding = float(np.linalg.det(affine[:3, :3])) < 0
    if reversed_winding:
        triangles = triangles[:, [0, 2, 1]]
    set_triangle_arrays(poly, physical_points, triangles)
    voxel_count = int(len(x))
    touching = {axis + "_min": bool(low_zyx[::-1][i] == 0) for i, axis in enumerate("xyz")}
    touching.update({axis + "_max": bool(high_zyx[::-1][i] == image.GetSize()[i] - 1)
                     for i, axis in enumerate("xyz")})
    details = {
        "voxels": voxel_count,
        "voxel_volume_mm3": abs(float(np.linalg.det(affine[:3, :3]))),
        "volume_mm3": voxel_count * abs(float(np.linalg.det(affine[:3, :3]))),
        "nonzero_bbox_index_xyz": {"min": low_zyx[::-1].tolist(), "max": high_zyx[::-1].tolist()},
        "touches_image_boundary": touching,
        "extraction": "vtkDiscreteMarchingCubes at label 1 in voxel index coordinates; explicit full LPS affine",
        "exterior_padding_voxels": 1,
        "padding_meaning": "Display envelope only; voxels outside the source domain assumed zero; no opening is certified.",
        "reflection_winding_corrected": reversed_winding,
    }
    return poly, details


def surface_stats(poly):
    points, triangles = triangle_arrays(poly)
    a, b, c = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    cross = np.cross(b - a, c - a)
    triangle_areas = np.linalg.norm(cross, axis=1) * 0.5
    edges = np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]), axis=0)
    edges.sort(axis=1)
    _, edge_counts = np.unique(edges, axis=0, return_counts=True)
    boundary_edges = int(np.count_nonzero(edge_counts == 1))
    nonmanifold_edges = int(np.count_nonzero(edge_counts > 2))
    connectivity = vtk.vtkPolyDataConnectivityFilter()
    connectivity.SetInputData(poly)
    connectivity.SetExtractionModeToAllRegions()
    connectivity.ColorRegionsOn()
    connectivity.Update()
    connected = connectivity.GetOutput()
    _, connected_triangles = triangle_arrays(connected)
    regions = vtk_to_numpy(connected.GetPointData().GetArray("RegionId"))
    _, component_faces = np.unique(regions[connected_triangles[:, 0]], return_counts=True)
    reference = points.mean(axis=0)
    signed_volume = float(np.einsum("ij,ij->i", a - reference,
                                    np.cross(b - reference, c - reference)).sum() / 6.0)
    closed = boundary_edges == 0 and nonmanifold_edges == 0
    return {
        "vertices": int(len(points)), "triangles": int(len(triangles)),
        "boundary_edges": boundary_edges, "nonmanifold_edges": nonmanifold_edges,
        "degenerate_triangles": int(np.count_nonzero(triangle_areas < 1e-12)),
        "components": int(connectivity.GetNumberOfExtractedRegions()),
        "component_triangle_counts_desc": sorted([int(n) for n in component_faces], reverse=True),
        "area_mm2": float(triangle_areas.sum()),
        "signed_enclosed_volume_mm3": signed_volume if closed else None,
        "enclosed_volume_mm3": abs(signed_volume) if closed else None,
        "closed_manifold_by_edge_counts": closed,
        "bounds_lps_mm": {"min": points.min(axis=0).tolist(), "max": points.max(axis=0).tolist()},
        "volume_note": "Binary-envelope numerical volume; closure and components do not establish anatomy or CFD suitability.",
    }


def decimate_for_viewer(poly, max_faces):
    if max_faces < 4:
        raise ValueError("max_faces must be at least four")
    input_faces = poly.GetNumberOfPolys()
    if input_faces <= max_faces:
        result = vtk.vtkPolyData()
        result.DeepCopy(poly)
        return result
    decimator = vtk.vtkDecimatePro()
    decimator.SetInputData(poly)
    decimator.SetTargetReduction(1.0 - float(max_faces) / input_faces)
    decimator.PreserveTopologyOn()
    decimator.SplittingOff()
    decimator.BoundaryVertexDeletionOff()
    decimator.AccumulateErrorOn()
    decimator.Update()
    result = vtk.vtkPolyData()
    result.DeepCopy(decimator.GetOutput())
    triangle_arrays(result)
    return result


def vertex_normals(poly):
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.ComputePointNormalsOn()
    normals.ComputeCellNormalsOff()
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOff()
    normals.SplittingOff()
    normals.Update()
    result = vtk.vtkPolyData()
    result.DeepCopy(normals.GetOutput())
    return result


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                                    allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_vtp(poly, output):
    """Use an ASCII staging path for VTK, and verify its actual read-back."""
    with tempfile.TemporaryDirectory(prefix="nasal_preview_vtp_") as tmp:
        staged = Path(tmp) / "surface.vtp"
        writer = vtk.vtkXMLPolyDataWriter()
        writer.SetFileName(str(staged))
        writer.SetInputData(poly)
        writer.SetDataModeToBinary()
        if writer.Write() != 1:
            raise RuntimeError("VTK surface write failed")
        reader = vtk.vtkXMLPolyDataReader()
        reader.SetFileName(str(staged))
        reader.Update()
        recovered = reader.GetOutput()
        original_points, original_triangles = triangle_arrays(poly)
        restored_points, restored_triangles = triangle_arrays(recovered)
        if (not np.array_equal(original_triangles, restored_triangles)
                or not np.allclose(original_points, restored_points, atol=1e-10, rtol=0)):
            raise RuntimeError("VTP read-back changed geometry")
        temporary = output.with_name(output.name + ".tmp")
        shutil.copyfile(staged, temporary)
        os.replace(temporary, output)


def add_surface_metadata(poly, affine, mask_hash):
    for name, value in {"coordinate_system": "LPS", "unit": "mm",
                        "artifact_type": "unreviewed_candidate_display_envelope",
                        "cfd_ready": "false", "source_mask_sha256": mask_hash}.items():
        field = vtk.vtkStringArray()
        field.SetName(name)
        field.InsertNextValue(value)
        poly.GetFieldData().AddArray(field)
    field = vtk.vtkDoubleArray()
    field.SetName("source_voxel_index_xyz_to_LPS_mm_affine_row_major")
    field.SetNumberOfComponents(16)
    field.InsertNextTuple(affine.ravel().tolist())
    poly.GetFieldData().AddArray(field)


def validate_source_geometry(image, manifest):
    if manifest.get("coordinate_system") != "LPS" or manifest.get("unit") != "mm":
        raise ValueError("Manifest must declare LPS and mm")
    if not np.allclose(geometry_affine(image), np.asarray(manifest["affine_4x4_LPS"]), atol=1e-5, rtol=0):
        raise ValueError("Mask affine differs from source manifest")
    source_geo = manifest["source_geometry"]
    if list(image.GetSize()) != source_geo["size_xyz"]:
        raise ValueError("Mask dimensions differ from source manifest")
    for actual, key in ((image.GetSpacing(), "spacing_xyz_mm"), (image.GetOrigin(), "origin_xyz_mm"),
                        (image.GetDirection(), "direction")):
        if not np.allclose(actual, source_geo[key], atol=1e-5, rtol=0):
            raise ValueError("Mask " + key + " differs from source manifest")


def relative_change(current, reference):
    return None if current is None or reference is None or reference == 0 else 100.0 * (current - reference) / reference


def export_case(case, input_root, output_root, threshold=-300, max_faces=40000):
    source_dir = (Path(input_root) / case / "anatomy").resolve()
    manifest_path = source_dir / "manifest.json"
    source_manifest_hash = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("case") != case:
        raise ValueError("Requested case does not match input manifest")
    candidate = manifest["threshold_candidates"][str(threshold)]
    mask_path = Path(candidate["path"]).resolve()
    if not mask_path.is_relative_to(source_dir):
        raise ValueError("Mask source must remain within this case anatomy directory")
    mask_hash = sha256_file(mask_path)
    image = read_image_local(mask_path)
    validate_source_geometry(image, manifest)
    raw, mask_info = mask_surface(image)
    if candidate.get("voxels") != mask_info["voxels"]:
        raise ValueError("Candidate voxel count differs from manifest")
    raw_stats = surface_stats(raw)
    viewer = vertex_normals(decimate_for_viewer(raw, max_faces))
    viewer_stats = surface_stats(viewer)
    points, triangles = triangle_arrays(viewer)
    normals = vtk_to_numpy(viewer.GetPointData().GetNormals())
    if not np.isfinite(normals).all():
        raise ValueError("Viewer normals are not finite")
    rounded_points = np.round(points, decimals=5)
    rounding_error = float(np.max(np.abs(rounded_points - points)))
    warnings = []
    if any(mask_info["touches_image_boundary"].values()):
        warnings.append("Source mask touches the CT field of view; padded envelope is not an anatomical boundary.")
    if viewer_stats["triangles"] > max_faces:
        warnings.append("Topology preservation prevents reaching the requested face budget.")
    if raw_stats["components"] != viewer_stats["components"]:
        warnings.append("Viewer decimation changed the connected component count.")
    if raw_stats["boundary_edges"] or raw_stats["nonmanifold_edges"]:
        warnings.append("Raw display envelope has boundary or nonmanifold edges.")
    if viewer_stats["boundary_edges"] or viewer_stats["nonmanifold_edges"]:
        warnings.append("Viewer display mesh has boundary or nonmanifold edges.")
    volume_change = relative_change(viewer_stats["enclosed_volume_mm3"], raw_stats["enclosed_volume_mm3"])
    if volume_change is not None and abs(volume_change) > 2:
        warnings.append("Decimation changed numerical enclosed volume by more than 2 percent; display-only engineering flag.")
    output_dir = Path(output_root) / case
    output_dir.mkdir(parents=True, exist_ok=True)
    source = {
        "mask_path_relative_to_work": str(mask_path.relative_to(WORK)).replace("\\", "/") if mask_path.is_relative_to(WORK) else mask_path.name,
        "manifest_path_relative_to_work": str(manifest_path.relative_to(WORK)).replace("\\", "/") if manifest_path.is_relative_to(WORK) else manifest_path.name,
        "mask_sha256": mask_hash, "manifest_sha256": source_manifest_hash,
        "threshold_HU": threshold, "source_status": manifest.get("status"),
        "source_review_checklist_pass": manifest.get("review_checklist_pass", False),
        "source_openings": manifest.get("openings", {}),
    }
    qc = {"mask": mask_info, "raw_surface": raw_stats, "viewer_surface": viewer_stats,
          "raw_surface_vs_voxel_volume_change_percent": relative_change(raw_stats["enclosed_volume_mm3"], mask_info["volume_mm3"]),
          "viewer_vs_raw_surface_volume_change_percent": volume_change,
          "requested_max_faces": max_faces, "json_coordinate_rounding_decimals": 5,
          "json_coordinate_rounding_max_abs_mm": rounding_error, "warnings": warnings}
    metadata = {
        "schema": "candidate_surface_preview/v1", "case": case,
        "status": "unreviewed_candidate_preview", "display_geometry_only": True,
        "review_required": True, "cfd_ready": False,
        "coordinate_system": "LPS", "unit": "mm",
        "affine_4x4_LPS": geometry_affine(image).tolist(),
        "affine_meaning": "Original source voxel index xyz to physical LPS/mm; viewer vertices are already transformed. Do not apply again.",
        "source_geometry": image_geometry(image), "source": source,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "vtk_version": vtk.vtkVersion.GetVTKVersion(),
        "operations": {"mask_modified": False, "resampled": False, "smoothed": False, "holes_filled": False,
                       "components_removed": False, "cropping_planes_applied": False,
                       "viewer_decimation": "vtkDecimatePro; preserve topology, no splitting, no boundary vertex deletion"},
        "notes": DISPLAY_NOTES, "qc": qc,
    }
    # Ensure the upstream inputs did not change while this artifact was built.
    if sha256_file(mask_path) != mask_hash or sha256_file(manifest_path) != source_manifest_hash:
        raise RuntimeError("Input changed during preview export; retry from the new source")
    add_surface_metadata(raw, geometry_affine(image), mask_hash)
    write_vtp(raw, output_dir / "surface_preview.vtp")
    viewer_payload = {**metadata, "geometry": {
        "vertex_layout": "flat xyz triplets", "index_layout": "flat triangle vertex index triplets; zero-based",
        "vertices": rounded_points.ravel().tolist(), "indices": triangles.ravel().tolist(),
        "normals": np.round(normals.astype(np.float64), decimals=6).ravel().tolist(),
        "bounds_lps_mm": viewer_stats["bounds_lps_mm"],
    }}
    atomic_json(output_dir / "viewer_mesh.json", viewer_payload)
    # Verify serialized numerical geometry rather than trusting the write call.
    recovered = json.loads((output_dir / "viewer_mesh.json").read_text(encoding="utf-8"))
    restored_vertices = np.asarray(recovered["geometry"]["vertices"]).reshape(-1, 3)
    restored_indices = np.asarray(recovered["geometry"]["indices"], dtype=np.int64).reshape(-1, 3)
    if (not np.array_equal(restored_indices, triangles)
            or not np.allclose(restored_vertices, points, atol=5.01e-6, rtol=0)):
        raise RuntimeError("Viewer JSON read-back changed geometry beyond its recorded precision")
    metadata["artifacts"] = {
        "surface_preview.vtp": {"sha256": sha256_file(output_dir / "surface_preview.vtp"),
                                "vertices": raw_stats["vertices"], "triangles": raw_stats["triangles"]},
        "viewer_mesh.json": {"sha256": sha256_file(output_dir / "viewer_mesh.json"),
                             "vertices": viewer_stats["vertices"], "triangles": viewer_stats["triangles"]},
    }
    metadata["verification"] = {"input_hash_unchanged": True, "vtp_readback_matches": True,
                                "viewer_json_readback_matches": True,
                                "geometry_matches_source_manifest": True}
    atomic_json(output_dir / "preview_manifest.json", metadata)
    return {"case": case, "status": metadata["status"], "cfd_ready": False,
            "output_dir": str(output_dir), "mask_volume_mL": mask_info["volume_mm3"] / 1000.0,
            "raw_triangles": raw_stats["triangles"], "viewer_triangles": viewer_stats["triangles"],
            "viewer_components": viewer_stats["components"], "viewer_boundary_edges": viewer_stats["boundary_edges"],
            "viewer_nonmanifold_edges": viewer_stats["nonmanifold_edges"],
            "viewer_volume_change_percent": volume_change, "warnings": warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", default=list(DEFAULT_CASES))
    parser.add_argument("--input-root", type=Path, default=WORK / "05_ts_seg")
    parser.add_argument("--output-root", type=Path, default=WORK / "07_cfd_pipeline" / "preview")
    parser.add_argument("--threshold", type=int, choices=(-300, -350, -400), default=-300)
    parser.add_argument("--max-faces", type=int, default=40000)
    args = parser.parse_args()
    results = []
    for case in args.cases:
        result = export_case(case, args.input_root, args.output_root, args.threshold, args.max_faces)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    atomic_json(args.output_root / "summary.json", {"schema": "candidate_surface_preview_batch/v1",
                "display_geometry_only": True, "cfd_ready": False, "cases": results})


if __name__ == "__main__":
    main()
