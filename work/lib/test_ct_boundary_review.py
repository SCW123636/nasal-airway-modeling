"""Synthetic byte artifacts verify review persistence, not CT anatomy or rendering."""

import copy
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from boundary_review import EVIDENCE, OPENINGS, parameters_sha256, write_boundary_review
from build_auto_landmark_review import build_review
from confirm_landmark_review import load_proposal_bundle
import ct_case_pipeline as pipeline
from test_boundary_review import review


class CTBoundaryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ct_boundary_review_')
        self.root = Path(self.temp.name)
        self.manager = pipeline.CaseManager(self.root / 'cases')
        self.case = self.manager.create({'kind': 'dicom', 'files': [{'name': 'synthetic.dcm', 'size': 2}]})['id']
        self.manager.upload(self.case, 0, io.BytesIO(b'CT'), 2)
        self.directory = self.manager.root / self.case
        (self.directory / 'ct.nii.gz').write_bytes(b'synthetic CT identity, not an image')
        (self.directory / 'masks').mkdir()
        (self.directory / 'masks/nasal_cavity_left.nii.gz').write_bytes(b'synthetic label identity')
        public = self.directory / 'public'
        report = {'case': self.case, 'coordinate_system': 'LPS', 'unit': 'mm',
                  'landmarks': {key: {'status': 'proposed', 'point_lps_mm': [1, 2, 3],
                                     'normal_lps': [0, 0, 1], 'roi_lps_mm': [6, 6, 6]} for key in OPENINGS}}
        pipeline.write_json(public / 'review' / self.case / 'landmarks.json', report)
        build_review(public / 'review', cases=[self.case])
        self.bundle = load_proposal_bundle(public / 'review/index.html')
        self.inputs = {key: pipeline.sha256(self.directory / key)
                       for key in ('ct.nii.gz', 'masks/nasal_cavity_left.nii.gz')}
        self.patient = 'synthetic_patient'
        hashes = {path.relative_to(public).as_posix(): pipeline.sha256(path)
                  for path in public.rglob('*') if path.is_file()}
        pipeline.write_json(self.directory / 'receipt.json', {
            'schema': 'ct_case_receipt/v1', 'case': self.case, 'output_sha256': hashes,
            'identity': {'input_sha256': self.inputs, 'coarse_reference': {'patient_id': self.patient}}})
        pipeline.update(self.directory, status='awaiting_review')
        self.decisions = self.accepted_decisions()
        self.manager.save_review(self.case, self.decisions)
        self.draft_id = 'd_0123456789abcdef'
        self.record = self.make_draft(self.directory, 'original')

    def tearDown(self):
        self.manager.pool.shutdown(wait=True)
        self.temp.cleanup()

    def accepted_decisions(self):
        source = self.bundle['cases'][0]
        return {'artifact_type': 'landmark_review_decisions', 'coordinate_system': 'LPS', 'unit': 'mm',
                'reviewer': 'Synthetic QA', 'proposal_bundle_sha256': self.bundle['proposal_bundle_sha256'],
                'cases': [{'case': self.case, 'source_sha256': source['source_sha256'], 'decisions': [
                    {'landmark_id': item['id'], 'proposal_sha256': item['proposal_sha256'],
                     'original_point_lps_mm': item['proposal']['point_lps_mm'],
                     'original_normal_lps': item['proposal']['normal_lps'], 'decision': 'accept'}
                    for item in source['landmarks']]}]}

    def make_draft(self, private, revision):
        self.draft = private / 'draft_previews' / self.draft_id
        self.draft.mkdir(parents=True)
        inputs = private / 'boundary_inputs'
        inputs.mkdir(parents=True, exist_ok=True)
        airway_input = inputs / 'airway_T300_provisional.nii.gz'
        sinus_input = inputs / 'sinus_exclusion_mask.nii.gz'
        airway_input.write_bytes(b'synthetic airway identity')
        sinus_input.write_bytes(b'synthetic sinus identity')
        record = review()
        record.update(case=self.case, patient_id=self.patient, revision=revision)
        outputs = {}
        for key in EVIDENCE + ('sinus_exclusion_mask',):
            path = self.draft / (key + '.test-bytes')
            path.write_bytes(('synthetic evidence: ' + key).encode('ascii'))
            outputs[key] = {'path': path.name, 'sha256': pipeline.sha256(path)}
        record['sinus_policy']['mask_sha256'] = outputs['sinus_exclusion_mask']['sha256']
        binding = {'case': self.case, 'patient_id': self.patient, 'revision': revision,
                   'ct_sha256': self.inputs['ct.nii.gz'],
                   'label_sha256': {key: digest for key, digest in self.inputs.items() if key.startswith('masks/')},
                   'candidate_sha256': self.bundle['proposal_bundle_sha256'],
                   'landmark_review_sha256': pipeline.sha256(private / 'review_config_confirmed.json')}
        manifest = {'schema': 'boundary_draft_preview/v1', 'status': 'generated', 'binding': binding,
                    'parameters_sha256': parameters_sha256(record), 'outputs': outputs,
                    'source_sha256': {'ct': pipeline.sha256(private / 'ct.nii.gz') if (private / 'ct.nii.gz').is_file() else self.inputs['ct.nii.gz'],
                                      'airway': pipeline.sha256(airway_input),
                                      'sinus_exclusion': pipeline.sha256(sinus_input)}}
        pipeline.write_json(self.draft / 'manifest.json', manifest)
        record['source'] = {key: value for key, value in binding.items() if key not in ('case', 'patient_id')}
        record['source'].update(draft_preview_sha256=pipeline.sha256(self.draft / 'manifest.json'),
                                parameters_sha256=manifest['parameters_sha256'])
        record['evidence_sha256'] = {key: outputs[key]['sha256'] for key in EVIDENCE}
        return record

    def save(self, record=None):
        return self.manager.save_boundary_review(self.case, self.draft_id, record or self.record)

    def test_save_load_and_server_restart_keep_solver_locked(self):
        state = self.save()
        self.assertEqual(state['boundary_review']['revision'], 'original')
        self.assertEqual(state['stages']['geometry'], 'waiting')
        for key in ('mesh', 'solver', 'results'):
            self.assertEqual(state['stages'][key], 'pending')
        self.assertEqual(state['patient_cfd_results'], 0)
        self.assertEqual(self.manager.load_boundary_review(self.case), self.record)
        other = pipeline.CaseManager(self.manager.root)
        try:
            self.assertEqual(other.load_boundary_review(self.case), self.record)
        finally:
            other.pool.shutdown(wait=True)

    def test_missing_preview_or_incomplete_landmark_review_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            self.manager.save_boundary_review(self.case, 'd_fedcba9876543210', self.record)
        pipeline.update(self.directory, status='awaiting_review')
        with self.assertRaisesRegex(ValueError, '点位审核'):
            self.save()

    def test_confirmed_record_must_match_current_proposal_source(self):
        path = self.directory / 'review_config_confirmed.json'
        confirmed = pipeline.read_json(path)
        confirmed['source_sha256'] = '0' * 64
        pipeline.write_json(path, confirmed)
        with self.assertRaisesRegex(ValueError, '候选来源'):
            self.save()

    def test_wrong_identity_or_new_cutting_controls_do_not_replace_previous_review(self):
        state = self.save()
        reference = state['boundary_review']
        original = (self.directory / reference['record_path']).read_bytes()
        for field, value in (('patient_id', 'other_patient'), ('revision', 'v_aaaaaaaaaaaaaaaa')):
            bad = copy.deepcopy(self.record)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.save(bad)
        bad = copy.deepcopy(self.record)
        bad['openings']['nostril_L']['keep_positive'] = False
        bad['source']['parameters_sha256'] = parameters_sha256(bad)
        with self.assertRaisesRegex(ValueError, 'parameters_sha256'):
            self.save(bad)
        self.assertEqual(self.manager.get(self.case)['boundary_review'], reference)
        self.assertEqual((self.directory / reference['record_path']).read_bytes(), original)
        self.assertEqual(self.manager.load_boundary_review(self.case), self.record)

    def test_changed_ct_labels_or_public_candidates_reject_old_review(self):
        self.save()
        for relative in ('ct.nii.gz', 'masks/nasal_cavity_left.nii.gz', 'public/review/index.html'):
            path = self.directory / relative
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            try:
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    self.manager.load_boundary_review(self.case)
            finally:
                path.write_bytes(original)

    def test_changed_evidence_mask_or_review_record_is_rejected(self):
        reference = self.save()['boundary_review']
        paths = [self.draft / (key + '.test-bytes') for key in ('axial', 'sinus_exclusion_mask')]
        paths.append(self.directory / reference['record_path'])
        paths.append(self.draft / 'manifest.json')
        for path in paths:
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            try:
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    self.manager.load_boundary_review(self.case)
            finally:
                path.write_bytes(original)

    def test_preview_outputs_cannot_escape_draft_directory(self):
        outside = self.directory / 'outside.test-bytes'
        outside.write_bytes(b'outside')
        manifest = pipeline.read_json(self.draft / 'manifest.json')
        for value in ('../../outside.test-bytes', str(outside.resolve())):
            manifest['outputs']['axial'] = {'path': value, 'sha256': pipeline.sha256(outside)}
            pipeline.write_json(self.draft / 'manifest.json', manifest)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '缺失或变化'):
                self.save()

    def test_point_rereview_invalidates_boundary_pointer_and_keeps_history(self):
        reference = self.save()['boundary_review']
        path = self.directory / reference['record_path']
        original = path.read_bytes()
        decisions = copy.deepcopy(self.decisions)
        decisions['reviewer'] = 'Second synthetic QA'
        self.manager.save_review(self.case, decisions)
        self.assertEqual(self.manager.get(self.case)['boundary_review']['status'], 'stale')
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaisesRegex(ValueError, '过期'):
            self.manager.load_boundary_review(self.case)
        with self.assertRaisesRegex(ValueError, '点位审核版本'):
            self.save()

    def test_versioned_case_uses_private_revision_and_rejects_original_draft(self):
        self.save()
        revision = 'v_aaaaaaaaaaaaaaaa'
        old_public = self.root / 'public_copy'
        shutil.copytree(self.directory / 'public', old_public)
        shutil.copytree(old_public, self.directory / 'public/versions' / revision)
        private = self.directory / 'runs' / revision
        private.mkdir(parents=True)
        for name in ('receipt.json', 'review_config_confirmed.json'):
            shutil.copy2(self.directory / name, private / name)
        pipeline.update(self.directory, current_revision=revision)
        with self.assertRaises(FileNotFoundError):
            self.manager.load_boundary_review(self.case)
        new_record = self.make_draft(private, revision)
        with self.assertRaises(ValueError):
            self.save(self.record)
        state = self.save(new_record)
        self.assertTrue(state['boundary_review']['record_path'].startswith('runs/' + revision + '/'))
        self.assertEqual(self.manager.load_boundary_review(self.case), new_record)

    def test_write_failure_preserves_previous_pointer(self):
        reference = self.save()['boundary_review']
        with patch('boundary_review.os.replace', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.save()
        self.assertEqual(self.manager.get(self.case)['boundary_review'], reference)
        self.assertFalse(list(self.directory.rglob('*.tmp')))
        self.assertEqual(self.manager.load_boundary_review(self.case), self.record)

    def test_case_state_change_during_save_does_not_publish_old_record(self):
        reference = self.save()['boundary_review']

        def write_then_change_case(*args, **kwargs):
            write_boundary_review(*args, **kwargs)
            pipeline.update(self.directory, status='awaiting_review')

        with patch.object(pipeline, 'write_boundary_review', side_effect=write_then_change_case):
            with self.assertRaisesRegex(ValueError, '保存期间'):
                self.save()
        self.assertEqual(self.manager.get(self.case)['boundary_review'], reference)


if __name__ == '__main__':
    unittest.main()
