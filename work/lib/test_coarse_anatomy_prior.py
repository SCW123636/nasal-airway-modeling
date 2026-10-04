"""Numerical regressions for the CT coarse-position prior."""
import unittest
from copy import deepcopy
from pathlib import Path
import tempfile
from unittest import mock

import numpy as np

import coarse_anatomy_prior as prior


def descriptor(scale=1.0, origin=(0., 0., 0.)):
    frame = {'origin_lps_mm': list(origin), 'left_lps': [1., 0., 0.],
             'posterior_lps': [0., 1., 0.], 'superior_lps': [0., 0., 1.],
             'palate_fit': {'rms_mm': 0.2}}
    low = np.zeros(3)
    span = np.array([10., 20., 30.]) * scale
    return {'schema': 'coarse_anatomy_descriptor/v1', 'coordinate_system': 'LPS', 'unit': 'mm',
            'frame': frame, 'structure': 'bilateral semantic nasal cavity',
            'axes': ['patient_left', 'posterior', 'superior'], 'bounds_quantiles': [.005, .995],
            'local_bounds_mm': {'min': low.tolist(), 'max': span.tolist()}, 'span_mm': span.tolist(),
            'exact_extrema_local_mm': {'min': low.tolist(), 'max': span.tolist()},
            'exact_extrema_lps_mm': {'min': low.tolist(), 'max': span.tolist()},
            'fov_truncated_labels': {key: False for key in prior.FRAME_LABELS},
            'eligible': True, 'reasons': []}


def reference(case, patient, point=(2., 4., 6.)):
    return {'case': case, 'patient_id': patient, 'descriptor': descriptor(),
            'landmarks': {'nostril_L': {'status': 'confirmed', 'point_lps_mm': list(point),
                         'review': {'method': 'human', 'reviewer': 'r', 'reviewed_at': '2026-01-01',
                                    'decision': 'accept'}}},
            'provenance': {'ct_sha256': case.ljust(64, '0')[:64]}}


class CoarsePriorTests(unittest.TestCase):
    def test_transfer_uses_three_axis_anatomical_scale(self):
        target = descriptor(origin=(20., -50., 100.))
        target['span_mm'] = target['local_bounds_mm']['max'] = [20., 10., 90.]
        angle = np.deg2rad(31.)
        rotation = np.array([[np.cos(angle), -np.sin(angle), 0.],
                             [np.sin(angle), np.cos(angle), 0.], [0., 0., 1.]])
        for axis, key in enumerate(('left_lps', 'posterior_lps', 'superior_lps')):
            target['frame'][key] = rotation[:, axis].tolist()
        # Independent analytic expectation: three scales, then head pose and offset.
        expected = rotation @ [4., 2., 18.] + [20., -50., 100.]
        np.testing.assert_allclose(prior.transfer([2., 4., 6.], descriptor(), target), expected)

    def test_unified_coordinate_roundtrip_and_normalized_position(self):
        desc = descriptor(origin=(10., -20., 30.))
        point = [12., -16., 36.]
        coords = prior.point_coordinates(point, desc)
        np.testing.assert_allclose(coords['point_uas_mm'], [2., 4., 6.])
        np.testing.assert_allclose(coords['point_uas_normalized'], [.2, .2, .2])
        np.testing.assert_allclose(prior.to_lps(coords['point_uas_mm'], desc['frame']), point)
        self.assertEqual(coords['coordinate_systems']['unified'], 'UAS')

    def test_coarse_adjustment_records_coarse_refined_and_delta(self):
        target = descriptor()
        rough = {'point_lps_mm': [2., 4., 6.], 'status': 'search_prior',
                 'independent_patients': 2, 'reference_spread_local_mm': [1., 0., 0.],
                 'local_search_box_mm': {'min': [0., 0., 0.], 'max': [4., 8., 12.]}}
        prior_result = {'reference_library_sha256': 'a' * 64, 'reviewed_reference_count': 2,
                        'accepted_references': [{'case': 'a'}], 'excluded_references': [],
                        'landmarks': {'nostril_L': rough}}
        landmarks = {'nostril_L': {'point_lps_mm': [3., 4., 6.], 'normal_lps': [1., 0., 0.],
                                   'status': 'proposed'}}
        result = prior.build_coarse_adjustment('target', target, prior_result, landmarks)
        item = result['landmarks']['nostril_L']
        self.assertEqual(result['unified_coordinate_system'], 'UAS')
        self.assertEqual(result['normalized_coordinate_system'], 'UAS-NORM')
        self.assertEqual(item['coarse']['point_uas_mm'], [2., 4., 6.])
        self.assertEqual(item['refined']['point_uas_mm'], [3., 4., 6.])
        self.assertEqual(item['delta']['delta_uas_mm'], [1., 0., 0.])
        self.assertEqual(item['coarse']['search_box_uas']['min_uas_mm'], [0., 0., 0.])

    def test_same_patient_is_not_counted_as_independent_reference(self):
        result = prior.predict(descriptor(), [reference('a', 'person-a'), reference('b', 'person-a')],
                               'target', 'person-a', 'f' * 64)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['accepted_references'], [])

    def test_two_people_create_search_prior_and_mad_style_spread(self):
        second = reference('b', 'person-b', point=(3., 4., 6.))
        result = prior.predict(descriptor(), [reference('a', 'person-a'), second],
                               'target', 'person-target', 'f' * 64)
        self.assertEqual(result['status'], 'available')
        point = result['landmarks']['nostril_L']
        self.assertEqual(point['status'], 'search_prior')
        np.testing.assert_allclose(point['point_lps_mm'], [2.5, 4., 6.])
        self.assertGreaterEqual(point['reference_spread_local_mm'][0], .49)

    def test_incomplete_target_stops_prior_before_point_generation(self):
        target = descriptor()
        target['fov_truncated_labels']['hard_palate'] = True
        target['eligible'] = False
        target['reasons'] = ['hard_palate: label touches CT boundary']
        result = prior.predict(target, [reference('a', 'person-a'), reference('b', 'person-b')],
                               'target', 'person-target', 'f' * 64)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('nostril_L', result['landmarks'])

    def test_an_isolated_mislabel_does_not_expand_the_scale_to_its_extreme(self):
        mask = np.zeros((30, 30, 100), bool)
        mask[5:25, 5:25, 5:25] = True
        mask[15, 15, 99] = True
        masks = {'nasal_cavity_left': mask, 'nasal_cavity_right': np.zeros_like(mask)}
        desc = prior.describe(masks, np.eye(4), descriptor()['frame'],
                              {name: False for name in prior.FRAME_LABELS})
        self.assertEqual(desc['exact_extrema_local_mm']['max'][0], 99.)
        self.assertLess(desc['span_mm'][0], 20.)

    def test_duplicate_timepoints_do_not_outvote_a_second_person(self):
        refs = [reference('a', 'one', (0., 4., 6.)), reference('b', 'two', (10., 4., 6.))]
        refs += [reference(str(i), 'one', (0., 4., 6.)) for i in range(10)]
        pred = prior.predict(descriptor(), refs, 't', 't', 'f' * 64)['landmarks']['nostril_L']
        self.assertEqual(pred['independent_patients'], 2)
        self.assertAlmostEqual(pred['point_lps_mm'][0], 5.)

    def test_same_ct_renamed_as_a_different_case_is_excluded(self):
        ref = reference('a', 'one')
        pred = prior.predict(descriptor(), [ref], 't', 't', ref['provenance']['ct_sha256'])
        self.assertEqual(pred['landmarks'], {})

    def test_unreasonable_size_ratio_does_not_create_a_search_region(self):
        pred = prior.predict(descriptor(5.), [reference('a', 'one')], 't', 't', 'f' * 64)
        self.assertEqual(pred['landmarks'], {})
        self.assertIn('size ratios', pred['excluded_references'][0]['reason'])

    def test_single_person_or_disagreement_only_displays_expected_position(self):
        for refs in ([reference('a', 'one')],
                     [reference('a', 'one', (0., 4., 6.)), reference('b', 'two', (100., 4., 6.))]):
            pred = prior.predict(descriptor(), refs, 't', 't', 'f' * 64)['landmarks']['nostril_L']
            self.assertEqual(pred['status'], 'display_only')
            self.assertIsNone(pred['normal_lps'])

    def test_unconfirmed_or_undated_library_is_rejected(self):
        ref = reference('a', 'one')
        ref['provenance'] = {key: 'a' * 64 for key in ('ct_sha256', 'proposal_sha256', 'confirmation_sha256')}
        library = {'schema': prior.SCHEMA, 'coordinate_system': 'LPS', 'unit': 'mm', 'references': [ref]}
        prior.validate_library(library)
        for field, value in (('status', 'proposed'), ('review', {})):
            bad = deepcopy(library)
            bad['references'][0]['landmarks']['nostril_L'][field] = value
            with self.assertRaises(ValueError):
                prior.validate_library(bad)

    def test_bad_library_falls_back_without_inventing_points(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'reference.json'
            path.write_text('{"schema":"old","references":[]}', encoding='utf-8')
            pred = prior.build_prior(descriptor(), path, 't', 't', 'f' * 64)
            self.assertEqual(pred['landmarks'], {})
            self.assertIn('Invalid reference library', pred['reason'])

    def test_template_never_fills_missing_image_evidence(self):
        pred = prior.predict(descriptor(), [reference('a', 'one'), reference('b', 'two')], 't', 't', 'f' * 64)
        lm = {'point_lps_mm': None, 'status': 'unavailable', 'evidence': {},
              'consistency_checks': {}, 'review_reasons': []}
        prior.compare_candidates(pred, {'nostril_L': lm}, descriptor()['frame'])
        self.assertIsNone(lm['point_lps_mm'])
        self.assertEqual(lm['status'], 'unavailable')

    def test_image_disagreement_is_recorded_instead_of_moving_point(self):
        pred = prior.predict(descriptor(), [reference('a', 'one'), reference('b', 'two')], 't', 't', 'f' * 64)
        lm = {'point_lps_mm': [50., 4., 6.], 'status': 'proposed', 'evidence': {},
              'consistency_checks': {}, 'review_reasons': []}
        prior.compare_candidates(pred, {'nostril_L': lm}, descriptor()['frame'])
        self.assertEqual(lm['point_lps_mm'], [50., 4., 6.])
        self.assertEqual(lm['status'], 'needs_review')

    def test_failed_local_air_evidence_retries_original_search(self):
        import auto_anatomy_landmarks as landmarks
        global_fit = {'samples': 30, 'rms_mm': 0., 'secondary_patch_ratio': 0.}
        with mock.patch.object(landmarks, 'nostril_candidate', side_effect=[None, global_fit]) as detector:
            fit = landmarks.nostril_with_prior(None, None, None, None, None, -300, {'status': 'search_prior'})
        self.assertEqual(detector.call_count, 2)
        self.assertEqual(fit['search_mode'], 'global_fallback_after_local_search')

    def test_reviewed_reference_import_binds_inputs_and_keeps_adjusted_point(self):
        from auto_anatomy_landmarks import NAMES
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'masks').mkdir()
            (root / 'ct.nii.gz').write_bytes(b'synthetic ct identity')
            for name in NAMES:
                (root / 'masks' / (name + '.nii.gz')).write_bytes(name.encode())
            inputs = {'ct.nii.gz': prior.sha256(root / 'ct.nii.gz')}
            inputs.update({f'masks/{name}.nii.gz': prior.sha256(root / 'masks' / (name + '.nii.gz')) for name in NAMES})
            prop_path, conf_path, library_path = root / 'proposal.json', root / 'confirmed.json', root / 'library.json'
            prior.write_json(prop_path, {'case': 's', 'coordinate_system': 'LPS', 'unit': 'mm',
                'input_provenance': {'input_sha256': inputs}, 'landmarks': {'nostril_L': {'point_lps_mm': [1., 2., 3.]}}})
            confirmation = {'schema': 'anatomy_barrier_review/v2', 'case': 's', 'coordinate_system': 'LPS',
                'unit': 'mm', 'source_sha256': prior.sha256(prop_path), 'planes_lps': {'nostril_L': {
                    'status': 'confirmed', 'point_lps_mm': [2., 3., 4.], 'review': {
                        'method': 'human', 'reviewer': 'synthetic reviewer', 'reviewed_at': '2026-01-01', 'decision': 'adjust'}}}}
            prior.write_json(conf_path, confirmation)
            with mock.patch.object(prior, 'load_descriptor', return_value=(descriptor(), None)):
                entry = prior.add_reference(library_path, 's', root, prop_path, conf_path, 'person')
                self.assertEqual(entry['landmarks']['nostril_L']['point_lps_mm'], [2., 3., 4.])
                saved = library_path.read_bytes()
                (root / 'ct.nii.gz').write_bytes(b'changed ct content')
                with self.assertRaisesRegex(ValueError, 'CT/labels differ'):
                    prior.add_reference(library_path, 's', root, prop_path, conf_path, 'person')
                self.assertEqual(library_path.read_bytes(), saved)

    def test_target_ct_is_not_modified_by_prior_generation(self):
        import SimpleITK as sitk
        image = sitk.Image([30, 30, 30], sitk.sitkInt16)
        image.SetSpacing([.7, .8, 1.])
        geometry = (image.GetSize(), image.GetSpacing(), image.GetOrigin(), image.GetDirection())
        prior.predict(descriptor(), [reference('a', 'one'), reference('b', 'two')], 't', 't', 'f' * 64, image)
        self.assertEqual(geometry, (image.GetSize(), image.GetSpacing(), image.GetOrigin(), image.GetDirection()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
