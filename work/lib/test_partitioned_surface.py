"""Synthetic closed meshes exercise exact clipping and wall/cap contracts."""
import unittest
import numpy as np
import SimpleITK as sitk

from partitioned_surface import clip_and_cap
from export_candidate_preview import mask_surface, triangle_arrays


def cube():
    points = np.array([[0, 0, 0], [4, 0, 0], [4, 4, 0], [0, 4, 0],
                       [0, 0, 8], [4, 0, 8], [4, 4, 8], [0, 4, 8]], float)
    faces = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                      [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                      [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]])
    return points, faces


def plane(point, normal, keep=True):
    return {'point_lps_mm': point, 'normal_lps': normal, 'keep_positive': keep,
            'roi_lps_mm': {'min': [-10, -10, -10], 'max': [10, 10, 20]}}


class PartitionedSurfaceTests(unittest.TestCase):
    def test_invalid_tolerance_rejected(self):
        v, f = cube()
        for tolerance in (0, -1, np.nan, np.inf):
            with self.assertRaisesRegex(ValueError, 'Tolerance'):
                clip_and_cap(v, f, {}, tolerance_mm=tolerance)

    def test_connected_three_opening_airway_keeps_all_patch_labels(self):
        values = np.zeros((20, 12, 20), np.uint8)
        values[2:12, 2:6, 2:6] = 1
        values[2:12, 2:6, 10:14] = 1
        values[10:17, 2:6, 2:14] = 1
        poly, _ = mask_surface(sitk.GetImageFromArray(values))
        vertices, faces = triangle_arrays(poly)
        specs = {'nostril_L': plane([4, 4, 4], [0, 0, 1]),
                 'nostril_R': plane([12, 4, 4], [0, 0, 1]),
                 'nasopharynx_outlet': plane([8, 4, 14], [0, 0, 1], False)}
        specs['nostril_L']['roi_lps_mm'] = {'min': [1, 1, 0], 'max': [7, 7, 8]}
        specs['nostril_R']['roi_lps_mm'] = {'min': [9, 1, 0], 'max': [15, 7, 8]}
        specs['nasopharynx_outlet']['roi_lps_mm'] = {'min': [1, 1, 12], 'max': [15, 7, 20]}
        _, _, labels, report = clip_and_cap(vertices, faces, specs)
        self.assertEqual(set(labels), {'wall', *specs})
        self.assertEqual(set(report['caps']), set(specs))
        for key in ('boundary_edges', 'nonmanifold_edges', 'inconsistent_winding_edges'):
            self.assertEqual(report['technical_qc'][key], 0)
        self.assertGreater(report['caps']['nasopharynx_outlet']['area_mm2'],
                           report['caps']['nostril_L']['area_mm2'])

    def test_two_end_caps_closed_and_labelled(self):
        vertices, faces = cube()
        p, f, labels, report = clip_and_cap(vertices, faces,
                       {'inlet': plane([0, 0, 2], [0, 0, 1]),
                        'outlet': plane([0, 0, 6], [0, 0, 1], False)})
        self.assertEqual(set(labels), {'wall', 'inlet', 'outlet'})
        self.assertAlmostEqual(report['technical_qc']['signed_volume_mm3'], 64)
        self.assertAlmostEqual(report['caps']['inlet']['area_mm2'], 16)
        for key in ('boundary_edges', 'nonmanifold_edges', 'inconsistent_winding_edges'):
            self.assertEqual(report['technical_qc'][key], 0)
        self.assertFalse(report['patient_solver_allowed'])
        np.testing.assert_array_equal(vertices, cube()[0])

    def test_oblique_clip_volume_and_rotation(self):
        v, f = cube()
        _, _, _, baseline = clip_and_cap(v, f, {'end': plane([0, 0, 2], [.2, .1, 1])})
        theta = .4
        r = np.array([[np.cos(theta), 0, np.sin(theta)], [0, 1, 0],
                      [-np.sin(theta), 0, np.cos(theta)]])
        spec = plane((np.array([0, 0, 2]) @ r.T + [20, -30, 40]).tolist(),
                     (np.array([.2, .1, 1]) @ r.T).tolist())
        spec['roi_lps_mm'] = {'min': [0, -50, 0], 'max': [50, 0, 80]}
        _, _, _, result = clip_and_cap(v @ r.T + [20, -30, 40], f, {'end': spec})
        self.assertAlmostEqual(result['technical_qc']['signed_volume_mm3'],
                               baseline['technical_qc']['signed_volume_mm3'])
        self.assertAlmostEqual(result['caps']['end']['area_mm2'],
                               baseline['caps']['end']['area_mm2'])

    def test_roi_side_cut_is_rejected(self):
        v, f = cube()
        spec = plane([0, 0, 2], [0, 0, 1])
        spec['roi_lps_mm']['max'][0] = 2
        with self.assertRaisesRegex(ValueError, 'ROI boundary'):
            clip_and_cap(v, f, {'end': spec})

    def test_open_source_or_absent_intersection_rejected(self):
        v, f = cube()
        with self.assertRaisesRegex(ValueError, 'Source must'):
            clip_and_cap(v, f[1:], {'end': plane([0, 0, 2], [0, 0, 1])})
        with self.assertRaisesRegex(ValueError, 'does not cut'):
            clip_and_cap(v, f, {'end': plane([0, 0, -2], [0, 0, 1])})


if __name__ == '__main__':
    unittest.main()
