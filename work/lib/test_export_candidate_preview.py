# -*- coding: utf-8 -*-
"""Geometry tests use synthetic masks only, never modify patient inputs."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import vtk

import export_candidate_preview as preview


def synthetic_image(array, spacing=(1.0, 1.0, 1.0), origin=(0.0, 0.0, 0.0), direction=None):
    image = sitk.GetImageFromArray(np.asarray(array, dtype=np.uint8))
    image.SetSpacing(spacing)
    image.SetOrigin(origin)
    if direction is not None:
        image.SetDirection(np.asarray(direction, dtype=float).ravel().tolist())
    return image


class CandidatePreviewGeometryTests(unittest.TestCase):
    def test_cropped_single_voxel_retains_original_index_coordinates(self):
        array = np.zeros((7, 10, 13), dtype=np.uint8)
        array[2, 5, 8] = 1
        image = synthetic_image(array, spacing=(0.4, 0.5, 0.8), origin=(-100.0, 30.0, 700.0))
        poly, mask = preview.mask_surface(image)
        points, _ = preview.triangle_arrays(poly)
        center = np.asarray(image.TransformIndexToPhysicalPoint((8, 5, 2)))
        half_spacing = np.asarray(image.GetSpacing()) * 0.5
        np.testing.assert_allclose(points.min(axis=0), center - half_spacing, atol=1e-10)
        np.testing.assert_allclose(points.max(axis=0), center + half_spacing, atol=1e-10)
        self.assertEqual(mask["voxels"], 1)
        self.assertAlmostEqual(mask["volume_mm3"], 0.16)

    def test_oblique_direction_and_translation_use_full_affine(self):
        array = np.zeros((8, 9, 10), dtype=np.uint8)
        array[2:6, 3:7, 4:8] = 1
        base, _ = preview.mask_surface(synthetic_image(array))
        base_points, _ = preview.triangle_arrays(base)
        angle = np.deg2rad(27.0)
        direction = np.asarray([[np.cos(angle), -np.sin(angle), 0],
                                [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
        image = synthetic_image(array, (0.35, 0.5, 0.8), (-92.0, -190.0, 640.0), direction)
        transformed, _ = preview.mask_surface(image)
        points, _ = preview.triangle_arrays(transformed)
        affine = preview.geometry_affine(image)
        expected = base_points @ affine[:3, :3].T + affine[:3, 3]
        np.testing.assert_allclose(points, expected, atol=1e-10)
        for index in ((0, 0, 0), (4, 3, 2), (9, 8, 7)):
            np.testing.assert_allclose((affine @ [*index, 1])[:3], image.TransformIndexToPhysicalPoint(index), atol=1e-10)

    def test_reflection_corrects_winding_and_preserves_scaled_signed_volume(self):
        array = np.zeros((8, 9, 10), dtype=np.uint8)
        array[2:6, 3:7, 4:8] = 1
        base, _ = preview.mask_surface(synthetic_image(array))
        baseline = preview.surface_stats(base)
        image = synthetic_image(array, (0.4, 0.5, 0.8), (10.0, 20.0, 30.0), np.diag([-1.0, 1.0, 1.0]))
        transformed, mask = preview.mask_surface(image)
        stats = preview.surface_stats(transformed)
        self.assertTrue(mask["reflection_winding_corrected"])
        self.assertAlmostEqual(stats["signed_enclosed_volume_mm3"], baseline["signed_enclosed_volume_mm3"] * 0.16, places=8)
        self.assertEqual(stats["boundary_edges"], 0)
        self.assertEqual(stats["nonmanifold_edges"], 0)

    def test_disconnected_islands_are_preserved_and_counted(self):
        array = np.zeros((18, 18, 18), dtype=np.uint8)
        array[2:6, 2:6, 2:6] = 1
        array[11:15, 11:15, 11:15] = 1
        poly, _ = preview.mask_surface(synthetic_image(array))
        self.assertEqual(preview.surface_stats(poly)["components"], 2)
        reduced = preview.decimate_for_viewer(poly, max_faces=100)
        self.assertEqual(preview.surface_stats(reduced)["components"], 2)
        self.assertEqual(preview.surface_stats(reduced)["nonmanifold_edges"], 0)

    def test_field_of_view_contact_is_reported(self):
        array = np.zeros((8, 9, 10), dtype=np.uint8)
        array[0:3, 2:6, 4:8] = 1
        _, mask = preview.mask_surface(synthetic_image(array))
        self.assertTrue(mask["touches_image_boundary"]["z_min"])
        self.assertFalse(mask["touches_image_boundary"]["z_max"])

    def test_source_affine_mismatch_is_rejected(self):
        array = np.zeros((8, 9, 10), dtype=np.uint8)
        array[2:6, 3:7, 4:8] = 1
        image = synthetic_image(array)
        manifest = {"coordinate_system": "LPS", "unit": "mm", "source_geometry": preview.image_geometry(image),
                    "affine_4x4_LPS": preview.geometry_affine(image).tolist()}
        preview.validate_source_geometry(image, manifest)
        manifest["affine_4x4_LPS"][0][3] += 1
        with self.assertRaisesRegex(ValueError, "affine"):
            preview.validate_source_geometry(image, manifest)

    def test_empty_and_multilabel_masks_fail(self):
        for value in (0, 2):
            array = np.full((3, 3, 3), value, dtype=np.uint8)
            with self.assertRaises(ValueError):
                preview.mask_surface(synthetic_image(array))

    def test_vtp_roundtrip_does_not_drop_direction_or_precision(self):
        array = np.zeros((8, 9, 10), dtype=np.uint8)
        array[2:6, 3:7, 4:8] = 1
        image = synthetic_image(array, (0.37, 0.51, 0.8), (-100.333, 29.5, 697.25),
                                np.asarray([[0, -1, 0], [1, 0, 0], [0, 0, 1]]))
        poly, _ = preview.mask_surface(image)
        preview.add_surface_metadata(poly, preview.geometry_affine(image), "synthetic-source-hash")
        with tempfile.TemporaryDirectory(prefix="nasal_geometry_test_") as tmp:
            output = Path(tmp) / "surface.vtp"
            preview.write_vtp(poly, output)
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(output))
            reader.Update()
            original, triangles = preview.triangle_arrays(poly)
            recovered, recovered_triangles = preview.triangle_arrays(reader.GetOutput())
            np.testing.assert_array_equal(triangles, recovered_triangles)
            np.testing.assert_allclose(original, recovered, atol=1e-10, rtol=0)
            fields = reader.GetOutput().GetFieldData()
            self.assertEqual(fields.GetAbstractArray("coordinate_system").GetValue(0), "LPS")
            self.assertEqual(fields.GetAbstractArray("unit").GetValue(0), "mm")
            self.assertEqual(fields.GetAbstractArray("cfd_ready").GetValue(0), "false")

    def test_complete_export_preserves_input_and_stays_unreviewed(self):
        array = np.zeros((8, 9, 10), dtype=np.uint8)
        array[2:6, 3:7, 4:8] = 1
        image = synthetic_image(array, (0.35, 0.5, 0.8), (-100.0, 25.0, 650.0),
                                np.asarray([[0, -1, 0], [1, 0, 0], [0, 0, 1]]))
        with tempfile.TemporaryDirectory(prefix="nasal_export_test_") as tmp:
            root = Path(tmp)
            anatomy = root / "input" / "synthetic" / "anatomy"
            anatomy.mkdir(parents=True)
            mask = anatomy / "mask.nii.gz"
            sitk.WriteImage(image, str(mask))
            original_hash = preview.sha256_file(mask)
            manifest = {"case": "synthetic", "status": "provisional", "coordinate_system": "LPS", "unit": "mm",
                        "source_geometry": preview.image_geometry(image), "affine_4x4_LPS": preview.geometry_affine(image).tolist(),
                        "threshold_candidates": {"-300": {"path": str(mask), "voxels": int(array.sum())}},
                        "review_checklist_pass": False, "openings": {"nostril_L": {"status": "unknown"}}}
            (anatomy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "output"
            result = preview.export_case("synthetic", root / "input", output, max_faces=300)
            viewer = json.loads((output / "synthetic" / "viewer_mesh.json").read_text(encoding="utf-8"))
            audit = json.loads((output / "synthetic" / "preview_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(preview.sha256_file(mask), original_hash)
            self.assertFalse(result["cfd_ready"])
            self.assertFalse(viewer["cfd_ready"])
            self.assertTrue(viewer["review_required"])
            self.assertTrue(viewer["display_geometry_only"])
            self.assertEqual(viewer["source"]["source_openings"]["nostril_L"]["status"], "unknown")
            self.assertEqual(viewer["source"]["mask_sha256"], original_hash)
            self.assertFalse(audit["operations"]["mask_modified"])
            self.assertTrue(audit["verification"]["viewer_json_readback_matches"])
            self.assertEqual(len(viewer["geometry"]["indices"]) % 3, 0)


if __name__ == "__main__":
    unittest.main()
