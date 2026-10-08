"""Human feedback adoption tests use temporary synthetic review evidence."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import adopt_landmark_feedback as module
from ct_case_pipeline import CaseManager, read_json, sha256, write_json
from medical_review import MedicalReviewStore
from build_auto_landmark_review import build_review
from test_build_auto_landmark_review import fixture
from test_medical_review import PNG
from build_reviewed_surface_drafts import load_adopted


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manager = CaseManager(self.root / 'cases')
        review_root = self.root / 'review'
        self.ct = self.root / 'ct.nii.gz'
        self.ct.write_bytes(b'synthetic CT identity')
        data = fixture()
        data['case'] = 'p0'
        del data['landmarks']['unknown']
        data['source_ct'] = str(self.ct)
        data['input_provenance'] = {'input_sha256': {'ct.nii.gz': sha256(self.ct)}}
        write_json(review_root / 'p0' / 'landmarks.json', data)
        (review_root / 'p0' / 'review.png').write_bytes(PNG)
        build_review(review_root, cases=['p0'])
        self.store = MedicalReviewStore(self.manager, review_root)
        _, digest = self.store.export('p0', 'landmarks')
        self.reply = {'schema': 'medical_review_feedback/v1', 'case': 'p0', 'stage': 'landmarks',
                      'package_sha256': digest, 'coordinate_system': 'LPS', 'unit': 'mm',
                      'reviewer': 'Synthetic QA', 'reviewed_at': '2026-10-08T10:00:00+08:00',
                      'items': [{'id': 'nostril_L', 'decision': 'accept', 'note': '',
                                 'adjusted_point_lps_mm': None, 'adjusted_normal_lps': None}]}
        self.store.import_feedback('p0', self.reply)

    def tearDown(self):
        self.manager.pool.shutdown(wait=True)
        self.temp.cleanup()

    def test_current_feedback_adopted_and_repeat_reuses_generation(self):
        first = module.adopt(self.store, 'p0')
        second = module.adopt(self.store, 'p0')
        self.assertEqual(first['revision'], second['revision'])
        self.assertEqual(len(list((self.store.storage('p0') / 'adopted_landmarks').glob('l_*'))), 1)
        config, _ = load_adopted(self.store, 'p0')
        self.assertEqual(config['planes_lps']['nostril_L']['status'], 'confirmed')
        self.assertFalse(config['boundary_confirmations']['oral_exclusion_confirmed'])
        self.assertFalse(first['patient_solver_allowed'])
        self.assertIsNone(config['geometry_binding']['reviewed_geometry_sha256'])

    def test_changed_input_or_artifact_refused(self):
        result = module.adopt(self.store, 'p0')
        path = Path(result['directory']) / 'review_config_confirmed.json'
        config = read_json(path)
        config['boundary_confirmations']['oral_exclusion_confirmed'] = True
        write_json(path, config)
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            load_adopted(self.store, 'p0')
        self.ct.write_bytes(b'changed source')
        with self.assertRaises(ValueError):
            module.adopt(self.store, 'p0')

    def test_publish_failure_leaves_no_current_pointer(self):
        original = module.write_json
        def fail(path, data):
            if Path(path).name == 'landmarks_current.json':
                raise OSError('synthetic publish failure')
            original(path, data)
        with patch.object(module, 'write_json', side_effect=fail):
            with self.assertRaises(OSError):
                module.adopt(self.store, 'p0')
        self.assertFalse((self.store.storage('p0') / 'landmarks_current.json').exists())
        self.assertFalse(list(self.store.storage('p0').rglob('.pending-*')))
        module.adopt(self.store, 'p0')
        self.assertTrue((self.store.storage('p0') / 'landmarks_current.json').exists())

    def test_reused_generation_rechecks_input_before_publish(self):
        module.adopt(self.store, 'p0')
        pointer = self.store.storage('p0') / 'landmarks_current.json'
        old_pointer = pointer.read_bytes()
        original = self.store.point_source
        calls = 0
        def changed(case):
            nonlocal calls
            calls += 1
            result = original(case)
            if calls == 3:
                return (*result[:3], dict(result[3], changed=True))
            return result
        with patch.object(self.store, 'point_source', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed during adoption'):
                module.adopt(self.store, 'p0')
        self.assertEqual(pointer.read_bytes(), old_pointer)

    def test_rejected_latest_feedback_cannot_inherit_older_pass(self):
        module.adopt(self.store, 'p0')
        self.reply['items'][0]['decision'] = 'reject'
        self.reply['items'][0]['note'] = 'Synthetic negative decision'
        self.store.import_feedback('p0', self.reply)
        # Imported timestamps have second precision; explicitly order the new entry.
        records = self.store.list_feedback('p0')['records']
        rejected = next(r for r in records if r['feedback']['items'][0]['decision'] == 'reject')
        with patch.object(self.store, 'list_feedback', return_value={'records': [rejected]}):
            with self.assertRaisesRegex(ValueError, 'Every point'):
                module.adopt(self.store, 'p0')
            with self.assertRaisesRegex(ValueError, 'Every point'):
                load_adopted(self.store, 'p0')

    def test_same_time_feedback_conflict_is_refused(self):
        records = self.store.list_feedback('p0')['records']
        duplicate = dict(records[0], id='different_record')
        with patch.object(self.store, 'list_feedback', return_value={'records': records + [duplicate]}):
            with self.assertRaisesRegex(ValueError, 'Ambiguous'):
                module.adopt(self.store, 'p0')


if __name__ == '__main__':
    unittest.main()
