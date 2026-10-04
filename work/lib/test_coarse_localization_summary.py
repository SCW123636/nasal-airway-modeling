"""Evidence summaries must keep missing CT points and reference warnings visible."""
import copy
import unittest

from coarse_localization_summary import summarize_localization


class LocalizationSummaryTests(unittest.TestCase):
    def report(self):
        return {'case': 'target', 'coarse_localization': {
            'schema': 'coarse_anatomy_prior/v1', 'coordinate_system': 'LPS', 'unit': 'mm',
            'reference_library_sha256': 'library',
            'accepted_references': [
                {'case': 'p3', 'patient_id': 'p3'},
                {'case': 'p3t1', 'patient_id': 'p3', 'quality_warning': 'frame warning'}],
            'landmarks': {'nostril_L': {'status': 'search_prior'}}},
            'landmarks': {'nostril_L': {'point_lps_mm': [1, 2, 3], 'evidence': {
                'search_mode': 'coarse_prior_local_search', 'threshold_variants': [
                    {'search_mode': 'global_fallback_after_local_search'}, None]}}},
            'coarse_adjustment': {'schema': 'coarse_anatomy_adjustment/v1',
                'case': 'target', 'reference_library_sha256': 'library',
                'landmarks': {'nostril_L': {'coarse': {'point_lps_mm': [0, 0, 0]},
                    'refined': {'point_lps_mm': [1, 2, 3]},
                    'delta': {'distance_uas_mm': 3.74}}}}}

    def test_counts_people_and_any_threshold_fallback_preserving_warning(self):
        summary = summarize_localization(self.report())
        self.assertEqual(summary['independent_reference_patients'], 1)
        self.assertEqual(summary['fallback_landmarks'], ['nostril_L'])
        self.assertEqual(summary['reference_quality_warnings'][0]['case'], 'p3t1')
        self.assertEqual(summary['max_refinement_delta_mm'], 3.74)
        self.assertFalse(summary['clinical_acceptance'])

    def test_missing_ct_or_foreign_adjustment_has_no_displacement(self):
        report = self.report()
        missing = copy.deepcopy(report)
        missing['landmarks']['nostril_L']['point_lps_mm'] = None
        self.assertIsNone(summarize_localization(missing)['max_refinement_delta_mm'])
        report['coarse_adjustment']['reference_library_sha256'] = 'old library'
        self.assertEqual(summarize_localization(report)['compared_points'], 0)

    def test_missing_or_invalid_prior_does_not_claim_search(self):
        self.assertEqual(summarize_localization({})['status'], 'not_generated')
        report = self.report()
        report['coarse_localization']['coordinate_system'] = 'RAS'
        summary = summarize_localization(report)
        self.assertEqual(summary['status'], 'not_generated')
        self.assertEqual(summary['search_prior_points'], 0)
        self.assertEqual(summary['reference_cases'], [])
