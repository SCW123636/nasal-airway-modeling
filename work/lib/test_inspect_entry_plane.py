"""Numerical ray checks only; these tests do not validate anatomy."""
import json
import unittest
import warnings
from unittest import mock

import numpy as np

import inspect_entry_plane as entry


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.ct = np.full((5, 5, 40), -1000.0)
        self.a = np.eye(4)

    def test_ray_ends_exactly_at_requested_length_without_overshoot(self):
        for length, step in [(30.0, 0.35), (1.0, 0.3), (0.6, 0.2), (0.1, 0.35)]:
            with self.subTest(length=length, step=step):
                ss, hu = entry.sample_hu(self.ct, self.a, [1, 2, 2], [1, 0, 0], length, step)
                self.assertEqual(ss[0], 0.0)
                self.assertEqual(ss[-1], length)
                self.assertTrue(np.all(ss <= length))
                self.assertTrue(np.all(np.diff(ss) > 0))
                self.assertEqual(len(ss), len(hu))

    def test_outside_fov_samples_remain_nan_instead_of_edge_air(self):
        ss, hu = entry.sample_hu(self.ct, self.a, [38, 2, 2], [1, 0, 0], 3, 0.5)
        np.testing.assert_allclose(hu[ss <= 1], -1000.0)
        self.assertTrue(np.all(np.isnan(hu[ss > 1])))

    def test_outside_fov_does_not_repeat_edge_tissue(self):
        self.ct[:, :, -1] = 50.0
        ss, hu = entry.sample_hu(self.ct, self.a, [39, 2, 2], [1, 0, 0], 1, 0.5)
        self.assertEqual(hu[0], 50.0)
        self.assertTrue(np.all(np.isnan(hu[ss > 0])))

    def test_oblique_anisotropic_sampling_uses_lps_millimeters(self):
        z, y, x = np.indices((6, 7, 8))
        ct = (2 * z + 3 * y + 5 * x).astype(float)
        # LPS X = 10 - 2*j; LPS Y = -20 + 0.5*i; LPS Z = 100 + 3*k.
        a = np.array([[0., -2., 0., 10.], [0.5, 0., 0., -20.],
                      [0., 0., 3., 100.], [0., 0., 0., 1.]])
        ss, hu = entry.sample_hu(ct, a, [4., -18.5, 106.], [0., 4., 0.], 1., 0.25)
        np.testing.assert_allclose(hu, 2 * 2 + 3 * 3 + 5 * (3 + ss / 0.5))

    def test_invalid_directions_raise_without_runtime_warnings(self):
        for direction in ([0, 0, 0], [np.nan, 1, 0], [np.inf, 0, 0],
                          [1, 0], [[1, 0, 0]], [1, 0, 0, 0]):
            with self.subTest(direction=direction), warnings.catch_warnings():
                warnings.simplefilter('error', RuntimeWarning)
                with self.assertRaises(ValueError):
                    entry.sample_hu(self.ct, self.a, [1, 2, 2], direction, 2)
                with self.assertRaises(ValueError):
                    entry.analyse_side(self.ct, self.a, [1, 2, 2], direction, 'left')

    def test_nonfinite_or_nonpositive_ray_dimensions_are_rejected(self):
        for bad in (0, -1, np.nan, np.inf):
            with self.subTest(length=bad), self.assertRaises(ValueError):
                entry.sample_hu(self.ct, self.a, [1, 2, 2], [1, 0, 0], bad, 0.35)
            with self.subTest(step=bad), self.assertRaises(ValueError):
                entry.sample_hu(self.ct, self.a, [1, 2, 2], [1, 0, 0], 1, bad)

    def test_invalid_origins_and_affines_are_rejected(self):
        for point in ([1, 2], [1, 2, np.nan], [np.inf, 1, 2]):
            with self.subTest(point=point), self.assertRaises(ValueError):
                entry.sample_hu(self.ct, self.a, point, [1, 0, 0], 1)
        for affine in (np.eye(3), np.full((4, 4), np.nan)):
            with self.subTest(affine=affine), self.assertRaises(ValueError):
                entry.sample_hu(self.ct, affine, [1, 2, 2], [1, 0, 0], 1)


class RayReportTests(unittest.TestCase):
    def test_first_tissue_hit_does_not_bridge_unknown_samples(self):
        ss = np.arange(4, dtype=float)
        self.assertIsNone(entry.first_tissue_distance(ss, [-1000., -900., np.nan, 0.]))
        self.assertIsNone(entry.first_tissue_distance(ss, [np.nan, 0., 0., 0.]))
        self.assertEqual(entry.first_tissue_distance(ss, [-1000., 0., np.nan, 0.]), 1.)

    def test_air_run_stops_at_first_unknown_sample(self):
        ss = np.arange(4, dtype=float)
        self.assertEqual(entry.air_run_from_origin(ss, [-1000., -900., np.nan, -1000.]), 1.)
        self.assertIsNone(entry.air_run_from_origin(ss, [np.nan, -1000., -1000., -1000.]))
        self.assertEqual(entry.air_run_from_origin(ss, [0., -1000., -1000., -1000.]), 0.)

    def test_truncated_air_ray_is_never_reported_as_full_length(self):
        ct = np.full((3, 3, 6), -1000.0)
        report, (ss, hu) = entry.analyse_side(ct, np.eye(4), [1, 1, 1], [-1, 0, 0], 'left')
        self.assertTrue(report['fov_truncated'])
        self.assertLess(report['observed_ray_mm'], 4.01)
        self.assertGreater(report['observed_ray_mm'], 3.5)
        self.assertEqual(report['air_run_from_point_mm'], round(report['observed_ray_mm'], 2))
        self.assertEqual(report['verdict'], 'no_tissue_hit_in_observed_ray')
        self.assertEqual(report['anatomical_verdict'], 'undetermined')
        self.assertTrue(np.isnan(hu[-1]))
        self.assertEqual(ss[-1], entry.FORWARD_MM)

    def test_tissue_hit_has_no_anatomical_verdict(self):
        ct = np.full((3, 3, 40), -1000.0)
        ct[:, :, 3:] = 0.0
        report, _ = entry.analyse_side(ct, np.eye(4), [1, 1, 1], [-1, 0, 0], 'right')
        self.assertEqual(report['forward_tissue_distance_mm'], 2.1)
        self.assertEqual(report['verdict'], 'tissue_hit_in_observed_ray')
        self.assertEqual(report['anatomical_verdict'], 'undetermined')
        self.assertIn('命中结构未识别', report['verdict_zh'])
        self.assertIn('不能据此确认', report['verdict_zh'])

    def test_full_air_ray_ends_at_thirty_not_thirty_point_one(self):
        ct = np.full((3, 3, 40), -1000.0)
        report, _ = entry.analyse_side(ct, np.eye(4), [1, 1, 1], [-1, 0, 0], 'left')
        self.assertEqual(report['air_run_from_point_mm'], 30.)
        self.assertEqual(report['observed_ray_mm'], 30.)
        self.assertFalse(report['fov_truncated'])
        self.assertEqual(report['anatomical_verdict'], 'undetermined')

    def test_origin_outside_fov_does_not_claim_observation_after_entry(self):
        ct = np.zeros((3, 3, 40))
        report, _ = entry.analyse_side(ct, np.eye(4), [-1, 1, 1], [-1, 0, 0], 'left')
        self.assertEqual(report['verdict'], 'origin_outside_fov')
        self.assertEqual(report['observed_ray_mm'], 0.)
        self.assertIsNone(report['air_run_from_point_mm'])
        self.assertFalse(report['air_run_is_observed_lower_bound'])
        self.assertIsNone(report['forward_tissue_distance_mm'])

    def test_observed_length_stops_at_first_gap(self):
        with mock.patch.object(entry, 'sample_hu', return_value=(
                np.array([0., 1., 2., 3.]), np.array([-1000., -900., np.nan, -1000.]))):
            report, _ = entry.analyse_side(None, None, [0, 0, 0], [-1, 0, 0], 'left')
        self.assertEqual(report['observed_ray_mm'], 1.)
        self.assertEqual(report['air_run_from_point_mm'], 1.)

    def test_profile_serializes_unknown_values_as_strict_json_null(self):
        ct = np.full((3, 3, 6), -1000.0)
        report, _ = entry.analyse_side(ct, np.eye(4), [1, 1, 1], [-1, 0, 0], 'left')
        text = json.dumps(report, allow_nan=False)
        self.assertNotIn('NaN', text)
        self.assertNotIn('Infinity', text)
        reloaded = json.loads(text)
        self.assertIn(None, reloaded['hu_profile']['hu'])
        self.assertEqual(len(reloaded['hu_profile']['hu']), len(reloaded['hu_profile']['distances_mm']))


if __name__ == '__main__':
    unittest.main()
