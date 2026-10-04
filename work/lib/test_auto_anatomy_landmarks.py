"""Synthetic geometry and proposal-safety regressions; no patient data required.

These checks verify numerical and software behavior only. They do not establish
anatomical accuracy, exterior-air identity, or readiness for CFD.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image
import SimpleITK as sitk

import auto_anatomy_landmarks as landmarks


def oblique_image():
    image = sitk.Image([24, 25, 26], sitk.sitkFloat32)
    angle = np.deg2rad(31.0)
    direction = np.array([[np.cos(angle), -np.sin(angle), 0.0],
                          [np.sin(angle), np.cos(angle), 0.0],
                          [0.0, 0.0, 1.0]])
    image.SetDirection(direction.ravel().tolist())
    image.SetSpacing((0.3, 0.7, 1.2))
    image.SetOrigin((19.0, -47.0, 112.0))
    return image


def plane_variant(**updates):
    result = {
        "point_lps_mm": [0.0, 0.0, 0.0],
        "normal_lps": [0.0, 0.0, 1.0],
        "samples": 30,
        "rms_mm": 0.0,
        "secondary_patch_ratio": 0.0,
        "roi_lps_mm": {"min": [-2.0, -2.0, -2.0],
                       "max": [2.0, 2.0, 2.0]},
    }
    result.update(updates)
    return result


def record(variants):
    return landmarks.result_record("synthetic", "合成候选", "synthetic", variants)


class PhysicalCoordinateTests(unittest.TestCase):
    def test_known_lps_coordinate_keeps_patient_left_and_posterior_signs(self):
        image = sitk.Image([10, 10, 10], sitk.sitkFloat32)
        image.SetSpacing((0.4, 0.7, 1.2))
        image.SetOrigin((10.0, -20.0, 100.0))
        image.SetDirection((0.0, -1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0))
        point = landmarks.physical([2.0, 3.0, 4.0], landmarks.affine(image))
        # XYZ index (4, 3, 2): LPS = (10 - 3*.7, -20 + 4*.4, 100 + 2*1.2).
        np.testing.assert_allclose(point, [7.9, -18.4, 102.4], atol=1e-12)

    def test_oblique_forward_and_inverse_match_simpleitk(self):
        image = oblique_image()
        affine = landmarks.affine(image)
        zyx = np.array([[0.0, 0.0, 0.0], [2.25, 3.5, 4.75], [17.0, 9.0, 7.0]])
        expected = np.array([image.TransformContinuousIndexToPhysicalPoint(tuple(q[::-1]))
                             for q in zyx])
        np.testing.assert_allclose(landmarks.physical(zyx, affine), expected, atol=1e-12)
        np.testing.assert_allclose(landmarks.indices(expected, affine), zyx, atol=1e-12)

    def test_crop_origin_preserves_global_physical_coordinates(self):
        image = oblique_image()
        cropped_affine = landmarks.affine(image)
        offset_zyx = np.array([3, 5, 7])
        cropped_affine[:3, 3] = landmarks.physical(offset_zyx, cropped_affine)
        local_zyx = np.array([1.25, 2.5, 3.75])
        expected = image.TransformContinuousIndexToPhysicalPoint(tuple((local_zyx + offset_zyx)[::-1]))
        np.testing.assert_allclose(landmarks.physical(local_zyx, cropped_affine), expected, atol=1e-12)

    def test_linear_ct_sampling_has_independent_analytic_value(self):
        z, y, x = np.indices((6, 7, 8))
        ramp = (2*z + 3*y + 5*x).astype(float)
        image = oblique_image()
        target = image.TransformContinuousIndexToPhysicalPoint((4.25, 3.5, 2.75))
        value = landmarks.sample(ramp, np.array(target), landmarks.affine(image))
        self.assertAlmostEqual(float(value), 2*2.75 + 3*3.5 + 5*4.25)

    def test_outside_sampling_does_not_become_air(self):
        value = landmarks.sample(np.full((3, 3, 3), -1000.0), np.array([-1., 1., 1.]), np.eye(4))
        self.assertTrue(np.isnan(value))

    def test_equal_size_does_not_hide_wrong_direction(self):
        reference = oblique_image()
        wrong = sitk.Image(reference)
        wrong.SetDirection((1., 0., 0., 0., 1., 0., 0., 0., 1.))
        self.assertFalse(landmarks.geometry_matches(reference, wrong))


class SharedFaceTests(unittest.TestCase):
    def test_single_face_center_and_anisotropic_physical_area(self):
        first = np.zeros((5, 5, 5), dtype=bool)
        second = first.copy()
        first[2, 2, 1] = True
        second[2, 2, 2] = True
        affine = np.diag([0.3, 0.5, 2.0, 1.0])
        points, area = landmarks.contact_points(first, second, affine)
        np.testing.assert_allclose(points, [[0.45, 1.0, 4.0]])
        self.assertAlmostEqual(area, 0.5*2.0)

    def test_edge_and_corner_voxel_adjacency_are_not_finite_apertures(self):
        for second_index in [(2, 3, 3), (3, 3, 3)]:
            with self.subTest(second_index=second_index):
                first = np.zeros((5, 5, 5), dtype=bool)
                second = first.copy()
                first[2, 2, 2] = True
                second[second_index] = True
                points, area = landmarks.contact_points(first, second, np.eye(4))
                self.assertEqual(points.shape, (0, 3))
                self.assertEqual(area, 0.0)
                self.assertIsNone(landmarks.interface_candidate(first, second, np.eye(4), {}))

    def test_neighboring_coplanar_faces_share_an_edge(self):
        groups = landmarks.face_patches(np.array([[0, 0, 1], [0, 2, 1]]), np.array([2, 2]))
        self.assertEqual(groups[0], groups[1])

    def test_corner_only_coplanar_faces_remain_separate(self):
        groups = landmarks.face_patches(np.array([[0, 0, 1], [2, 2, 1]]), np.array([2, 2]))
        self.assertNotEqual(groups[0], groups[1])

    def test_orthogonal_faces_sharing_full_edge_join_one_patch(self):
        groups = landmarks.face_patches(np.array([[0, 0, 1], [0, 1, 0]]), np.array([2, 1]))
        self.assertEqual(groups[0], groups[1])

    def test_separate_patch_centroid_is_not_averaged_into_empty_gap(self):
        first = np.zeros((12, 30, 12), dtype=bool)
        second = first.copy()
        first[1:5, 1:6, 5] = True
        second[1:5, 1:6, 6] = True
        first[7:9, 20:23, 5] = True
        second[7:9, 20:23, 6] = True
        result = landmarks.interface_candidate(first, second, np.eye(4), {})
        self.assertEqual(result["patch_count"], 2)
        self.assertEqual(result["samples"], 20)
        self.assertAlmostEqual(result["secondary_patch_ratio"], 6/20)
        self.assertAlmostEqual(result["face_contact_area_mm2"], 20.0)
        self.assertAlmostEqual(result["total_face_contact_area_mm2"], 26.0)
        np.testing.assert_allclose(result["point_lps_mm"], [5.5, 3.0, 2.5])
        # Positive signed distance keeps the first semantic label (x=5).
        self.assertGreater(np.dot(np.array([5., 3., 2.5])-result["point_lps_mm"], result["normal_lps"]), 0)

    def test_patch_ranking_uses_mm2_instead_of_face_count(self):
        first = np.zeros((18, 18, 18), dtype=bool)
        second = first.copy()
        first[2:4, 2:5, 3] = True
        second[2:4, 2:5, 4] = True  # Six x-normal faces: 6 * (0.5 * 2) = 6 mm2.
        first[10, 11:15, 11:15] = True
        second[11, 11:15, 11:15] = True  # Sixteen z-normal faces: 16 * (0.3 * 0.5) = 2.4 mm2.
        affine = np.diag([0.3, 0.5, 2.0, 1.0])
        result = landmarks.interface_candidate(first, second, affine, {})
        self.assertEqual(result["samples"], 6)
        self.assertEqual(result["patch_count"], 2)
        self.assertAlmostEqual(result["face_contact_area_mm2"], 6.0)
        self.assertAlmostEqual(result["secondary_patch_ratio"], 0.4)
        np.testing.assert_allclose(result["point_lps_mm"], [1.05, 1.5, 5.0])


class ProposalStatusTests(unittest.TestCase):
    def test_stable_proposal_never_becomes_clinically_confirmed(self):
        base = plane_variant()
        result = record([base, base, base])
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["clinical_validation"], "not_validated")
        self.assertIsNone(result["confidence_probability"])

    def test_reversed_normal_is_180_degrees_not_stable(self):
        base = plane_variant()
        reversed_normal = plane_variant(normal_lps=[0., 0., -1.])
        result = record([base, reversed_normal, base])
        self.assertEqual(result["status"], "needs_review")
        self.assertAlmostEqual(result["evidence"]["threshold_normal_change_deg"], 180.)
        self.assertFalse(result["consistency_checks"]["threshold_direction_stable"])

    def test_positive_normal_scale_does_not_change_orientation(self):
        base = plane_variant()
        scaled = plane_variant(normal_lps=[0., 0., 7.])
        result = record([base, scaled, base])
        self.assertEqual(result["status"], "proposed")
        self.assertAlmostEqual(result["evidence"]["threshold_normal_change_deg"], 0.)

    def test_missing_secondary_threshold_requires_review(self):
        base = plane_variant()
        result = record([base, None, base])
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["consistency_checks"]["all_three_thresholds_found"])

    def test_missing_primary_threshold_does_not_silently_substitute_another(self):
        base = plane_variant()
        result = record([None, base, base])
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["point_lps_mm"])

    def test_competing_patch_at_nonprimary_threshold_requires_review(self):
        base = plane_variant()
        competitor = plane_variant(secondary_patch_ratio=0.6)
        result = record([base, base, competitor])
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["consistency_checks"]["no_competing_large_patch"])

    def test_sparse_secondary_threshold_cannot_be_hidden_by_dense_primary(self):
        base = plane_variant()
        result = record([base, plane_variant(samples=3), base])
        self.assertEqual(result['status'], 'needs_review')
        self.assertFalse(result['consistency_checks']['enough_patch_samples'])

    def test_warped_secondary_plane_cannot_be_hidden_by_primary_fit(self):
        base = plane_variant()
        result = record([base, base, plane_variant(rms_mm=4.)])
        self.assertEqual(result['status'], 'needs_review')
        self.assertFalse(result['consistency_checks']['plane_residual_within_engineering_limit'])

    def test_absent_patch_measurement_cannot_be_reported_as_passed(self):
        missing = plane_variant()
        del missing["secondary_patch_ratio"]
        result = record([missing, missing, missing])
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["consistency_checks"]["no_competing_large_patch"])


class RayProposalTests(unittest.TestCase):
    def setUp(self):
        self.ct = np.full((40, 40, 40), -1000., dtype=np.float32)
        self.side = np.zeros(self.ct.shape, dtype=bool)
        self.side[20:23, 20:25, 20:25] = True
        self.frame = {"posterior_lps": [0., 1., 0.],
                      "superior_lps": [0., 0., 1.],
                      "origin_lps_mm": [0., 0., 0.]}

    def propose(self, flow=None, ct=None, side=None):
        with mock.patch.dict(landmarks.PARAMETERS, {"outward_ray_angles_deg": [90.]}):
            return landmarks.nostril_candidate(self.side if side is None else side,
                self.side if flow is None else flow,
                self.ct if ct is None else ct, np.eye(4), self.frame, -300.)

    def test_clear_finite_ray_is_a_proposal_without_exterior_claim(self):
        result = self.propose()
        self.assertIsNotNone(result)
        self.assertFalse(result["external_air_independently_established"])
        self.assertAlmostEqual(result["point_lps_mm"][2], 20.)
        self.assertGreater(result["normal_lps"][2], 0.99)

    def test_semantic_reentry_rejects_otherwise_clear_air_ray(self):
        flow = self.side.copy()
        flow[14, :, :] = True
        self.assertIsNone(self.propose(flow=flow))

    def test_tissue_along_ray_is_rejected(self):
        ct = self.ct.copy()
        ct[14, :, :] = 100.
        self.assertIsNone(self.propose(ct=ct))

    def test_ray_leaving_field_of_view_is_rejected(self):
        side = np.zeros_like(self.side)
        side[8:11, 20:25, 20:25] = True
        self.assertIsNone(self.propose(flow=side, side=side))


class PlaneDisplayTests(unittest.TestCase):
    def test_rounding_slice_position_shifts_horizontal_intersection(self):
        # Physical plane y + 2*z = 5 + 2*2.4. Displayed z=2 requires y=5.8.
        line = landmarks.plane_slice_line([2.4, 5., 4.], [0., 1., 2.], np.eye(4), (2, 1), 2, (3., 3.))
        np.testing.assert_allclose(line[0], [1., 7.])
        np.testing.assert_allclose(line[1], [5.8, 5.8])

    def test_rounding_slice_position_shifts_vertical_intersection(self):
        # Physical plane x + 2*z = 4 + 2*2.4. Displayed z=2 requires x=4.8.
        line = landmarks.plane_slice_line([2.4, 5., 4.], [1., 0., 2.], np.eye(4), (2, 1), 2, (3., 3.))
        np.testing.assert_allclose(line[0], [4.8, 4.8])
        np.testing.assert_allclose(line[1], [2., 8.])

    def test_all_oblique_display_lines_satisfy_original_physical_plane(self):
        image = oblique_image()
        affine = landmarks.affine(image)
        q = np.array([4.2, 7.4, 8.3])
        point = np.array(image.TransformContinuousIndexToPhysicalPoint(tuple(q[::-1])))
        normal = np.array([0.7, -0.3, 1.1])
        for axes in [(2, 1), (2, 0), (1, 0)]:
            with self.subTest(axes=axes):
                fixed = next(i for i in range(3) if i not in axes)
                displayed = int(round(q[fixed]))
                x, y = landmarks.plane_slice_line(q, normal, affine, axes, displayed, (2., 3.))
                for xx, yy in zip(x, y):
                    index = q.copy()
                    index[axes[0]], index[axes[1]], index[fixed] = xx, yy, displayed
                    endpoint = np.array(image.TransformContinuousIndexToPhysicalPoint(tuple(index[::-1])))
                    self.assertAlmostEqual(float(normal @ (endpoint-point)), 0., places=11)

    def test_parallel_slice_has_no_unique_intersection_line(self):
        self.assertIsNone(landmarks.plane_slice_line([2.4, 5., 4.], [0., 0., 1.], np.eye(4), (2, 1), 2, (3., 3.)))

    def test_no_candidate_still_writes_valid_png(self):
        with tempfile.TemporaryDirectory(prefix="nasal_landmarks_test_") as tmp:
            destination = Path(tmp)/"review.png"
            landmarks.plot_review(np.zeros((2, 2, 2)), {}, np.eye(4),
                                  {"case": "synthetic", "landmarks": {}}, destination)
            with Image.open(destination) as image:
                image.verify()
            self.assertGreater(destination.stat().st_size, 0)

    def test_empty_markups_is_valid_lps_json(self):
        with tempfile.TemporaryDirectory(prefix="nasal_landmarks_test_") as tmp:
            destination = Path(tmp)/"landmarks.mrk.json"
            landmarks.markups({"landmarks": {}}, destination)
            markup = json.loads(destination.read_text(encoding="utf-8"))["markups"][0]
            self.assertEqual(markup["coordinateSystem"], "LPS")
            self.assertEqual(markup["coordinateUnits"], "mm")
            self.assertEqual(markup["controlPoints"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
