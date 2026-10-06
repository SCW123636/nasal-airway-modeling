"""Diagnostic geometry evidence; no synthetic test grants patient admission."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import SimpleITK as sitk
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray

import diagnose_patient_surface as diagnostic


def surface(points, faces):
    poly = vtk.vtkPolyData()
    vertices = vtk.vtkPoints()
    vertices.SetData(numpy_to_vtk(np.array(points, dtype=float), deep=True))
    poly.SetPoints(vertices)
    cells = vtk.vtkCellArray()
    cells.SetData(numpy_to_vtkIdTypeArray(np.arange(len(faces) + 1, dtype=np.int64) * 3, deep=True),
                  numpy_to_vtkIdTypeArray(np.array(faces, dtype=np.int64).ravel(), deep=True))
    poly.SetPolys(cells)
    return poly


class DiagnosticEvidenceTests(unittest.TestCase):
    def test_components_include_two_disconnected_tetrahedra(self):
        points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
        poly = surface(np.r_[points, points + 3], np.r_[faces, faces + 4])
        self.assertEqual(diagnostic.component_sizes(poly), [4, 4])

    def test_roi_removal_does_not_cut_unrelated_voxels_and_honors_sign(self):
        poly = surface([[0, 0, -1], [1, 0, 1], [0, 1, 1]], [[0, 1, 2]])
        spec = {"point_lps_mm": [0, 0, 0], "normal_lps": [0, 0, 2],
                "roi_lps_mm": {"min": [-2, -2, -2], "max": [2, 2, 2]},
                "keep_positive": True}
        voxels = np.array([[0, 0, -1], [0, 0, 1], [100, 0, -1], [0, 0, 0]])
        result = diagnostic.plane_probe(poly, {"opening": spec}, voxels, 0.5)["opening"]
        self.assertEqual(result["predicted_removed_voxels_in_roi"], 1)
        self.assertEqual(result["predicted_removed_volume_mm3"], 0.5)
        spec["keep_positive"] = False
        result = diagnostic.plane_probe(poly, {"opening": spec}, voxels, 0.5)["opening"]
        self.assertEqual(result["predicted_removed_voxels_in_roi"], 1)

    def test_binary_mask_and_oblique_full_affine(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = sitk.GetImageFromArray(np.ones((2, 3, 4), dtype=np.uint8))
            image.SetSpacing([0.2, 0.3, 0.7])
            image.SetOrigin([10, -20, 30])
            image.SetDirection([0, -1, 0, 1, 0, 0, 0, 0, 1])
            path = Path(tmp) / "input.nii.gz"
            sitk.WriteImage(image, str(path))
            info, loaded, _, affine = diagnostic.mask_summary(path)
            np.testing.assert_allclose(diagnostic.index_to_physical([2, 1, 1], affine),
                                       loaded.TransformIndexToPhysicalPoint((2, 1, 1)))
            self.assertAlmostEqual(info["volume_mm3"], 24 * 0.2 * 0.3 * 0.7, places=6)
            bad = sitk.GetImageFromArray(np.full((2, 3, 4), 2, dtype=np.uint8))
            sitk.WriteImage(bad, str(path))
            with self.assertRaisesRegex(ValueError, "binary"):
                diagnostic.mask_summary(path)

    def test_topology_counts_duplicate_and_reversed_triangle(self):
        poly = surface([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                       [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tetra.stl"
            writer = vtk.vtkSTLWriter()
            writer.SetFileName(str(path))
            writer.SetInputData(poly)
            writer.Write()
            info, _ = diagnostic.surface_summary(path)
            self.assertEqual(info["boundary_edges"], 0)
            self.assertEqual(info["inconsistent_winding_edges"], 0)
            self.assertAlmostEqual(info["enclosed_volume_mm3"], 1 / 6)
            reversed_poly = surface([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                                   [[0, 1, 2], [0, 1, 3], [1, 2, 3], [2, 0, 3], [0, 1, 2]])
            writer.SetInputData(reversed_poly)
            writer.Write()
            info, _ = diagnostic.surface_summary(path)
            self.assertEqual(info["duplicate_triangles"], 1)
            self.assertEqual(info["nonmanifold_edges"], 3)


if __name__ == "__main__":
    unittest.main()
