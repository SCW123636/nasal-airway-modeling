"""Synthetic tests for the legacy surface function's physical geometry.

All files are temporary. No patient data or existing project products are read,
regenerated, promoted, capped, padded, or cropped by these tests.
"""
from pathlib import Path
import tempfile
import unittest

import numpy as np
import SimpleITK as sitk

import geo_manifest

if geo_manifest.HAS_VTK:
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy


def oblique_direction(reflect=False):
    a, b = np.deg2rad([31., 23.])
    around_z = np.array([[np.cos(a), -np.sin(a), 0.],
                         [np.sin(a), np.cos(a), 0.], [0., 0., 1.]])
    around_x = np.array([[1., 0., 0.], [0., np.cos(b), -np.sin(b)],
                         [0., np.sin(b), np.cos(b)]])
    direction = around_z @ around_x
    if reflect:
        direction = direction @ np.diag([-1., 1., 1.])
    return direction


def single_voxel_image(direction=None, spacing=(.4, .7, 1.2), origin=(19., -47., 112.)):
    voxels = np.zeros((5, 6, 7), dtype=np.uint8)
    voxels[2, 3, 4] = 1
    image = sitk.GetImageFromArray(voxels)
    image.SetSpacing(spacing)
    image.SetOrigin(origin)
    if direction is not None:
        image.SetDirection(np.asarray(direction).ravel().tolist())
    return image


@unittest.skipUnless(geo_manifest.HAS_VTK, "VTK is required to test the VTP extraction path")
class SurfaceAffineTests(unittest.TestCase):
    def extract(self, image):
        with tempfile.TemporaryDirectory(prefix="geo_affine_test_") as temporary:
            path = Path(temporary)/"surface.vtp"
            count = geo_manifest.make_surface_vtp(image, str(path))
            self.assertTrue(path.exists())
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(path))
            reader.Update()
            mesh = vtk.vtkPolyData()
            mesh.DeepCopy(reader.GetOutput())
        self.assertEqual(count, mesh.GetNumberOfPoints())
        return mesh

    def assert_single_voxel_coordinates(self, image, mesh, tolerance=1e-10):
        # A sole interior foreground voxel has six interpolated face-centre
        # vertices: index (4,3,2) plus/minus one half along each XYZ axis.
        center_xyz = np.array([4., 3., 2.])
        index_vertices = [center_xyz + sign * .5 * axis for axis in np.eye(3) for sign in (-1., 1.)]
        expected = np.array([image.TransformContinuousIndexToPhysicalPoint(tuple(p)) for p in index_vertices])
        actual = vtk_to_numpy(mesh.GetPoints().GetData())
        self.assertEqual(mesh.GetNumberOfPoints(), 6)
        self.assertEqual(mesh.GetNumberOfPolys(), 8)
        distances = np.linalg.norm(actual[:, None, :] - expected[None, :, :], axis=2)
        self.assertLessEqual(float(distances.min(axis=0).max()), tolerance)
        self.assertLessEqual(float(distances.min(axis=1).max()), tolerance)
        return actual

    def assert_outward_winding(self, image, mesh):
        center = np.array(image.TransformContinuousIndexToPhysicalPoint((4., 3., 2.)))
        points = vtk_to_numpy(mesh.GetPoints().GetData())
        signed_volume = 0.
        for index in range(mesh.GetNumberOfCells()):
            cell = mesh.GetCell(index)
            self.assertEqual(cell.GetNumberOfPoints(), 3)
            triangle = points[[cell.GetPointId(i) for i in range(3)]]
            cross = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
            self.assertGreater(float(cross @ (triangle.mean(axis=0)-center)), 0.)
            p = triangle-center
            signed_volume += float(p[0] @ np.cross(p[1], p[2])) / 6.
        # The marching-cubes single-voxel surface is an octahedron, not a cube.
        # Semiaxes spacing/2 give volume 4/3 * (sx/2)*(sy/2)*(sz/2).
        self.assertAlmostEqual(signed_volume, float(np.prod(image.GetSpacing()))/6., places=10)

    def test_axis_aligned_anisotropic_geometry_keeps_previous_physical_positions(self):
        image = single_voxel_image()
        mesh = self.extract(image)
        self.assert_single_voxel_coordinates(image, mesh)
        self.assert_outward_winding(image, mesh)

    def test_oblique_anisotropic_direction_and_origin_match_simpleitk(self):
        image = single_voxel_image(oblique_direction())
        before = sitk.GetArrayFromImage(image).copy()
        original_geometry = (image.GetSize(), image.GetSpacing(), image.GetOrigin(), image.GetDirection())
        mesh = self.extract(image)
        self.assert_single_voxel_coordinates(image, mesh)
        self.assert_outward_winding(image, mesh)
        np.testing.assert_array_equal(sitk.GetArrayFromImage(image), before)
        self.assertEqual((image.GetSize(), image.GetSpacing(), image.GetOrigin(), image.GetDirection()), original_geometry)

    def test_reflected_oblique_geometry_preserves_outward_triangle_winding(self):
        image = single_voxel_image(oblique_direction(reflect=True))
        self.assertLess(np.linalg.det(np.array(image.GetDirection()).reshape(3, 3)), 0.)
        mesh = self.extract(image)
        self.assert_single_voxel_coordinates(image, mesh)
        self.assert_outward_winding(image, mesh)

    def test_large_origin_does_not_round_points_to_float32_precision(self):
        image = single_voxel_image(oblique_direction(), origin=(123456.789, -234567.891, 98765.4321))
        mesh = self.extract(image)
        self.assert_single_voxel_coordinates(image, mesh, tolerance=1e-9)
        self.assertEqual(vtk_to_numpy(mesh.GetPoints().GetData()).dtype, np.dtype("float64"))

    def test_volume_touching_scan_edge_stays_open_without_external_padding(self):
        voxels = np.zeros((5, 6, 7), dtype=np.uint8)
        voxels[1:4, 1:5, 0:2] = 1  # Label intersects the original x=0 scan boundary.
        image = sitk.GetImageFromArray(voxels)
        image.SetSpacing((.4, .7, 1.2))
        image.SetOrigin((19., -47., 112.))
        image.SetDirection(oblique_direction(reflect=True).ravel().tolist())
        mesh = self.extract(image)
        points = vtk_to_numpy(mesh.GetPoints().GetData())
        index_points = np.array([image.TransformPhysicalPointToContinuousIndex(tuple(p)) for p in points])
        self.assertAlmostEqual(float(index_points[:, 0].min()), 0., places=10)
        self.assertAlmostEqual(float(index_points[:, 0].max()), 1.5, places=10)
        boundary = vtk.vtkFeatureEdges()
        boundary.SetInputData(mesh)
        boundary.BoundaryEdgesOn()
        boundary.FeatureEdgesOff()
        boundary.NonManifoldEdgesOff()
        boundary.ManifoldEdgesOff()
        boundary.Update()
        self.assertGreater(boundary.GetOutput().GetNumberOfCells(), 0)

    def test_all_foreground_keeps_original_no_interface_result(self):
        # Padding with invented exterior background would create a closed shell;
        # the original extraction range has no 0/1 transition and must stay empty.
        image = sitk.GetImageFromArray(np.ones((4, 5, 6), dtype=np.uint8))
        image.SetDirection(oblique_direction(reflect=True).ravel().tolist())
        mesh = self.extract(image)
        self.assertEqual(mesh.GetNumberOfPoints(), 0)
        self.assertEqual(mesh.GetNumberOfCells(), 0)

    def test_empty_mask_remains_empty(self):
        image = sitk.GetImageFromArray(np.zeros((4, 5, 6), dtype=np.uint8))
        mesh = self.extract(image)
        self.assertEqual(mesh.GetNumberOfPoints(), 0)
        self.assertEqual(mesh.GetNumberOfCells(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
