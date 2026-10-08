"""Analytic synthetic contours; no patient geometry is read."""
import unittest

import numpy as np

from planar_cap import triangulate_cap


def square(x0, y0, x1, y1):
    return np.array([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0]], dtype=float)


class PlanarCapTests(unittest.TestCase):
    def test_square_and_reversed_normal(self):
        for normal in ([0, 0, 1], [0, 0, -1]):
            vertices = square(0, 0, 4, 4)
            faces, qc = triangulate_cap(vertices, [[0, 1, 2, 3]], normal)
            self.assertAlmostEqual(qc['area_mm2'], 16)
            cross = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                             vertices[faces[:, 2]] - vertices[faces[:, 0]])
            self.assertTrue(np.all(cross @ normal > 0))
            self.assertFalse(qc['patient_solver_allowed'])

    def test_concave_u(self):
        vertices = np.array([[0, 0, 0], [4, 0, 0], [4, 4, 0], [3, 4, 0],
                             [3, 1, 0], [1, 1, 0], [1, 4, 0], [0, 4, 0]], float)
        _, qc = triangulate_cap(vertices, [list(range(8))], [0, 0, 1])
        self.assertAlmostEqual(qc['area_mm2'], 10)

    def test_hole_and_nested_island_with_arbitrary_winding(self):
        vertices = np.vstack((square(0, 0, 4, 4), square(1, 1, 3, 3), square(1.5, 1.5, 2.5, 2.5)))
        _, qc = triangulate_cap(vertices, [[3, 2, 1, 0], [4, 5, 6, 7], [11, 10, 9, 8]], [0, 0, 1])
        self.assertAlmostEqual(qc['area_mm2'], 13)
        self.assertEqual(qc['contour_depths'], [0, 1, 2])

    def test_disconnected_openings(self):
        vertices = np.vstack((square(0, 0, 1, 1), square(2, 0, 4, 2)))
        _, qc = triangulate_cap(vertices, [list(range(4)), list(range(4, 8))], [0, 0, 1])
        self.assertAlmostEqual(qc['area_mm2'], 5)
        self.assertEqual(qc['contour_depths'], [0, 0])

    def test_rotation_translation_preserve_area(self):
        vertices = np.vstack((square(0, 0, 4, 4), square(1, 1, 3, 3)))
        theta = .63
        rotation = np.array([[np.cos(theta), 0, np.sin(theta)], [0, 1, 0],
                             [-np.sin(theta), 0, np.cos(theta)]])
        vertices = vertices @ rotation.T + [20, -30, 40]
        _, qc = triangulate_cap(vertices, [list(range(4)), list(range(4, 8))], rotation[:, 2])
        self.assertAlmostEqual(qc['area_mm2'], 12)

    def test_arbitrary_rotations_nested_contours(self):
        original = np.vstack((square(0, 0, 4, 4), square(1, 1, 3, 3),
                              square(1.5, 1.5, 2.5, 2.5)))
        loops = [list(range(start, start + 4)) for start in (0, 4, 8)]
        rng = np.random.default_rng(20261007)
        for _ in range(100):
            rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
            vertices = original @ rotation.T + rng.uniform(-700, 700, 3)
            faces, qc = triangulate_cap(vertices, loops, rotation[:, 2])
            self.assertAlmostEqual(qc['area_mm2'], 13)
            self.assertEqual(qc['contour_depths'], [0, 1, 2])
            cross = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                             vertices[faces[:, 2]] - vertices[faces[:, 0]])
            self.assertTrue(np.all(cross @ rotation[:, 2] > 0))

    def test_collinear_boundary_vertex_preserved(self):
        vertices = np.array([[0, 0, 0], [2, 0, 0], [4, 0, 0], [4, 4, 0], [0, 4, 0]], float)
        faces, qc = triangulate_cap(vertices, [list(range(5))], [0, 0, 1])
        self.assertIn(1, faces)
        self.assertEqual(qc['boundary_edges'], 5)

    def test_crossing_or_touching_contours_rejected(self):
        for second in (square(2, 2, 5, 5), square(4, 1, 5, 2)):
            vertices = np.vstack((square(0, 0, 4, 4), second))
            with self.assertRaisesRegex(ValueError, 'cross or touch'):
                triangulate_cap(vertices, [list(range(4)), list(range(4, 8))], [0, 0, 1])

    def test_self_crossing_rejected(self):
        vertices = np.array([[0, 0, 0], [4, 4, 0], [0, 4, 0], [4, 0, 0]], float)
        with self.assertRaisesRegex(ValueError, 'cross or touch'):
            triangulate_cap(vertices, [list(range(4))], [0, 0, 1])

    def test_bad_geometry_rejected(self):
        vertices = square(0, 0, 4, 4)
        for loops, normal in (([[0, 1, 2, 4]], [0, 0, 1]), ([[0, 1, 1, 3]], [0, 0, 1]),
                              ([[0, 1, 2, 3]], [0, 0, 0])):
            with self.assertRaises(ValueError):
                triangulate_cap(vertices, loops, normal)
        vertices[0, 2] = 1
        with self.assertRaisesRegex(ValueError, 'coplanar'):
            triangulate_cap(vertices, [list(range(4))], [0, 0, 1])


if __name__ == '__main__':
    unittest.main()
