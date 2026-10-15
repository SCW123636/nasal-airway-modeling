import unittest
import numpy as np
import SimpleITK as sitk
from continuous_air_candidate import connected_air, index_to_lps, same_grid
from anatomy_barrier_seg import plane_keep_mask


class ContinuousAirKnownAnswers(unittest.TestCase):
    def test_strict_threshold_and_six_neighbours(self):
        ct = np.full((3, 3, 5), 0, dtype=np.int16)
        ct[1, 1, 1:4] = [-1000, -300, -301]
        ct[2, 2, 2] = -1000
        seed = np.zeros(ct.shape, bool); seed[1, 1, 1] = True
        result, _ = connected_air(ct, seed)
        expected = np.zeros(ct.shape, bool); expected[1, 1, 1] = True
        self.assertTrue(np.array_equal(result, expected))

    def test_barrier_stops_crossing_and_all_seed_components_retained(self):
        ct = np.full((3, 3, 7), 0, dtype=np.int16); ct[1, 1, 1:6] = -1000
        seed = np.zeros(ct.shape, bool); seed[1, 1, 1] = True
        allowed = np.ones(ct.shape, bool); allowed[:, :, 3] = False
        result, _ = connected_air(ct, seed, allowed)
        expected = np.zeros(ct.shape, bool); expected[1, 1, 1:3] = True
        self.assertTrue(np.array_equal(result, expected))
        seed[1, 1, 5] = True
        result, report = connected_air(ct, seed, allowed)
        expected[1, 1, 4:6] = True
        self.assertTrue(np.array_equal(result, expected)); self.assertEqual(len(report['seed_component_ids']), 2)

    def test_empty_mismatch_and_exterior_rejected(self):
        ct = np.full((3, 3, 3), -1000, dtype=np.int16); seed = np.zeros(ct.shape, bool)
        with self.assertRaisesRegex(ValueError, 'empty'): connected_air(ct, seed)
        with self.assertRaisesRegex(ValueError, 'shape'): connected_air(ct, np.ones((1, 1, 1), bool))
        seed[1, 1, 1] = True; exterior = np.zeros(ct.shape, bool); exterior[0] = True
        with self.assertRaisesRegex(ValueError, 'external-air'): connected_air(ct, seed, exterior_seed=exterior)
        result, report = connected_air(ct, seed, exterior_seed=exterior, reject_leak=False)
        self.assertTrue(result.all()); self.assertTrue(report['exterior_leak_detected'])

    def test_nonidentity_lps_and_barrier_known_answer(self):
        image = sitk.Image([3, 3, 3], sitk.sitkInt16)
        image.SetOrigin((10, 20, 30)); image.SetSpacing((2, 3, 4))
        image.SetDirection((0, -1, 0, 1, 0, 0, 0, 0, 1))
        self.assertTrue(np.array_equal(index_to_lps([[1, 2, 1]], image), [[4, 22, 34]]))
        plane = {'point_lps_mm': [7, 20, 30], 'normal_lps': [1, 0, 0], 'keep_positive': True,
                 'roi_lps_mm': {'min': [-100, -100, -100], 'max': [100, 100, 100]}}
        expected = np.ones((3, 3, 3), bool); expected[:, 2, :] = False
        self.assertTrue(np.array_equal(plane_keep_mask(image, plane, expected.shape), expected))
        other = sitk.Image(image); other.SetOrigin((11, 20, 30))
        self.assertFalse(same_grid(image, other))


if __name__ == '__main__': unittest.main()
