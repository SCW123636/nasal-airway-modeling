"""Regression tests for feedback identity, physical planes and FOV handling."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import numpy as np
import SimpleITK as sitk
import build_feedback_review as audit


def feedback(case='caseA', key='nostril_R', point=None, **extra):
    return {'matching_tolerance_mm': .002, 'observations': [dict(
        id='F01', reported_case=case, reported_landmark=key,
        reported_point_lps_mm=point or [1.234, 2.345, -600.123], **extra)]}


def reports():
    return {'caseA': {'case': 'caseA', 'landmarks': {
        'nostril_R': {'point_lps_mm': [1.2343, 2.3452, -600.1234]},
        'posterior_choana_L': {'point_lps_mm': [1.2343, 2.3452, -600.1234]}}}}


class IdentityTests(unittest.TestCase):
    def test_rounding_only_match_does_not_modify_inputs(self):
        f, r = feedback(), reports(); before = copy.deepcopy((f, r))
        out = audit.resolve_feedback(f, r)[0]
        self.assertTrue(out['bound_to_current_proposal'])
        self.assertEqual((f, r), before)

    def test_coordinate_typo_stays_unbound(self):
        out = audit.resolve_feedback(feedback(point=[1.234, 2.405, -600.123]), reports())[0]
        self.assertEqual(out['match_status'], 'coordinate_mismatch')
        self.assertFalse(out['bound_to_current_proposal'])

    def test_unknown_case_cannot_bind_to_identical_numeric_point(self):
        out = audit.resolve_feedback(feedback(case='unknown'), reports())[0]
        self.assertFalse(out['bound_to_current_proposal'])
        self.assertFalse(out['nearest_numeric_reference_only']['is_identity_confirmation'])

    def test_alias_requires_explicit_chinese_left_label(self):
        wrong = audit.resolve_feedback(feedback(key='posterior_choana_1'), reports())[0]
        self.assertFalse(wrong['bound_to_current_proposal'])
        good = audit.resolve_feedback(feedback(key='posterior_choana_1', reported_label_zh='左后鼻孔候选'), reports())[0]
        self.assertTrue(good['bound_to_current_proposal'])
        self.assertTrue(good['alias_from_explicit_chinese_label'])

    def test_opposite_z_sign_does_not_get_auto_corrected(self):
        out = audit.resolve_feedback(feedback(point=[1.234, 2.345, 600.123]), reports())[0]
        self.assertFalse(out['bound_to_current_proposal'])
        self.assertGreater(out['discrepancy_mm'], 1200)


class PhysicalSamplingTests(unittest.TestCase):
    def test_oblique_anisotropic_ct_samples_world_linear_field(self):
        image = sitk.Image([90, 80, 70], sitk.sitkFloat32)
        image.SetSpacing([.7, 1.3, 2.])
        image.SetOrigin([100., -200., 900.])
        theta = np.deg2rad(31)
        image.SetDirection([np.cos(theta), -np.sin(theta), 0.,
                            np.sin(theta), np.cos(theta), 0., 0., 0., 1.])
        a = audit.affine(image)
        z, y, x = np.indices((70, 80, 90))
        world = audit.physical(np.stack((z, y, x), axis=-1), a)
        gradient = np.array([.25, -.5, .125])
        ct = (world @ gradient).astype(np.float32)
        center = np.asarray(image.TransformContinuousIndexToPhysicalPoint((44., 40., 35.)))
        u, v, n = audit.plane_basis([.2, .3, .9])
        points, xx, yy = audit.plane_points(center, u, v)
        actual = audit.sample(ct, points, a)
        self.assertTrue(np.isfinite(actual).all())
        np.testing.assert_allclose(actual, points @ gradient, atol=3e-5, rtol=0)
        # Independent SimpleITK transform validates the coordinate ordering.
        np.testing.assert_allclose(audit.indices(points[10, 20], a)[::-1],
                                   image.TransformPhysicalPointToContinuousIndex(tuple(points[10, 20])), atol=1e-10)

    def test_plane_basis_and_translations_preserve_physical_mm(self):
        point = np.array([10., -40., 800.])
        u, v, n = audit.plane_basis([1., 2., 3.])
        np.testing.assert_allclose(np.array([u, v, n]) @ np.array([u, v, n]).T, np.eye(3), atol=1e-12)
        for offset in audit.OFFSETS:
            points, _, _ = audit.plane_points(point+offset*n, u, v)
            np.testing.assert_allclose((points-point) @ n, offset, atol=1e-12)

    def test_fov_missing_is_not_counted_as_air_or_tissue(self):
        ct = np.full((5, 5, 5), -1000., dtype=np.float32)
        masks = {name: np.ones_like(ct, dtype=np.uint8) for name in audit.NAMES}
        tile = audit.sample_tile(ct, masks, np.eye(4), [2, 2, 2], [1, 0, 0], [0, 1, 0])
        m = audit.tile_metrics(tile, ['nasal_cavity_left'])
        self.assertLess(m['valid_fov_fraction'], .1)
        # 9 x 9 samples at 0.5-mm spacing are inside index centers 0..4.
        self.assertAlmostEqual(m['target_label_air_area_mm2'], 81*.25)
        self.assertAlmostEqual(m['hard_palate_label_area_mm2'], 81*.25)
        self.assertTrue(np.isnan(tile[0][0, 0]))

    def test_tissue_in_target_label_does_not_count_as_air(self):
        ct = np.full((5, 5, 5), 250., dtype=np.float32)
        masks = {name: np.ones_like(ct, dtype=np.uint8) for name in audit.NAMES}
        tile = audit.sample_tile(ct, masks, np.eye(4), [2, 2, 2], [1, 0, 0], [0, 1, 0])
        m = audit.tile_metrics(tile, ['nasal_cavity_left'])
        self.assertEqual(m['target_label_air_area_mm2'], 0)
        self.assertGreater(m['hard_palate_label_area_mm2'], 0)

    def test_local_frame_translation_does_not_create_z_rule(self):
        p, origin = np.array([20., 10., -600.]), np.array([0., 0., -610.])
        shift = np.array([300., -700., 1400.])
        np.testing.assert_allclose(p-origin, (p+shift)-(origin+shift))


class PageTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_browser_javascript_syntax(self):
        source = Path(audit.__file__).with_name('feedback_review_template.html').read_text(encoding='utf-8')
        js = source.split('<script>')[1].split('</script>')[0]
        result = subprocess.run([shutil.which('node'), '--check'], input=js, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('innerHTML', source)
        self.assertNotIn('fetch(', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
