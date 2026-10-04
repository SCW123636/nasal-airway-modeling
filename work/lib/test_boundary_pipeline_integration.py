"""End-to-end boundary preview API with real SimpleITK image artifacts."""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import SimpleITK as sitk

import ct_case_pipeline as pipeline
from boundary_review import EVIDENCE, OPENINGS, parameters_sha256
from build_auto_landmark_review import build_review
from confirm_landmark_review import load_proposal_bundle
from test_boundary_review import review


class BoundaryPipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='boundary_pipeline_')
        self.manager = pipeline.CaseManager(Path(self.temp.name) / 'cases')
        self.case = self.manager.create({'kind': 'dicom', 'files': [{'name': 'scan.dcm', 'size': 2}]})['id']
        self.manager.upload(self.case, 0, BytesIO(b'CT'), 2)
        self.directory = self.manager.root / self.case
        self._write_artifacts()

    def tearDown(self):
        self.manager.pool.shutdown(wait=True)
        self.temp.cleanup()

    def _write_artifacts(self):
        size = (20, 20, 20)
        values = np.full((20, 20, 20), -900, dtype=np.float32)
        values[2:17, 2:17, 2:17] = 50
        ct = sitk.GetImageFromArray(values)
        ct.SetSpacing((1.0, 1.0, 1.0))
        ct.SetOrigin((0.0, 0.0, 0.0))
        airway = sitk.GetImageFromArray((values > -100).astype(np.uint8))
        airway.CopyInformation(ct)
        sinus = sitk.Image(size, sitk.sitkUInt8)
        sinus.CopyInformation(ct)
        ct_path = self.directory / 'ct.nii.gz'
        label_path = self.directory / 'masks' / 'nasal_cavity_left.nii.gz'
        label_path.parent.mkdir(parents=True)
        sitk.WriteImage(ct, str(ct_path))
        sitk.WriteImage(airway, str(label_path))
        anatomy = self.directory / 'anatomy'
        anatomy.mkdir()
        sitk.WriteImage(airway, str(anatomy / 'main_nasal_airway_T300_provisional.nii.gz'))

        report = {'case': self.case, 'coordinate_system': 'LPS', 'unit': 'mm',
                  'landmarks': {key: {'status': 'proposed', 'point_lps_mm': [5, 5, 5],
                                     'normal_lps': [0, 0, 1],
                                     'roi_lps_mm': {'min': [0, 0, 0], 'max': [19, 19, 19]}}
                               for key in OPENINGS}}
        public = self.directory / 'public'
        pipeline.write_json(public / 'review' / self.case / 'landmarks.json', report)
        build_review(public / 'review', cases=[self.case])
        bundle = load_proposal_bundle(public / 'review' / 'index.html')
        inputs = {'ct.nii.gz': pipeline.sha256(ct_path),
                  'masks/nasal_cavity_left.nii.gz': pipeline.sha256(label_path)}
        output_hashes = {str(path.relative_to(public)).replace('\\', '/'): pipeline.sha256(path)
                         for path in public.rglob('*') if path.is_file()}
        pipeline.write_json(self.directory / 'receipt.json', {
            'schema': 'ct_case_receipt/v1', 'case': self.case,
            'output_sha256': output_hashes,
            'identity': {'input_sha256': inputs, 'coarse_reference': {'patient_id': 'synthetic_patient'}}})
        pipeline.update(self.directory, status='awaiting_review')
        decisions = {'artifact_type': 'landmark_review_decisions', 'coordinate_system': 'LPS', 'unit': 'mm',
                     'reviewer': 'Synthetic QA', 'proposal_bundle_sha256': bundle['proposal_bundle_sha256'],
                     'cases': [{'case': self.case, 'source_sha256': bundle['cases'][0]['source_sha256'],
                                'decisions': [{'landmark_id': item['id'], 'proposal_sha256': item['proposal_sha256'],
                                               'original_point_lps_mm': item['proposal']['point_lps_mm'],
                                               'original_normal_lps': item['proposal']['normal_lps'],
                                               'decision': 'accept'} for item in bundle['cases'][0]['landmarks']]}]}
        self.manager.save_review(self.case, decisions)
        self.sinus_path = Path(self.temp.name) / 'sinus.nii.gz'
        sitk.WriteImage(sinus, str(self.sinus_path))

    def test_mask_preview_manifest_and_boundary_save(self):
        mask_bytes = self.sinus_path.read_bytes()
        state = self.manager.upload_boundary_mask(self.case, BytesIO(mask_bytes), len(mask_bytes))
        self.assertEqual(state['boundary_inputs']['sinus_exclusion_mask']['path'],
                         'boundary_inputs/sinus_exclusion_mask.nii.gz')
        generated = self.manager.generate_boundary_preview(self.case, {
            'oral_exclusion_confirmed': True, 'sinus_policy_confirmed': True,
            'pixels': 65, 'field_mm': 30.0})
        manifest = generated['boundary_preview_manifest']
        self.assertEqual(manifest['status'], 'generated')
        self.assertFalse(manifest['cfd_ready'])
        draft_id = generated['boundary_preview']['draft_id']
        self.assertEqual(self.manager.load_boundary_preview_manifest(self.case, draft_id)['draft_id'], draft_id)
        self.assertGreater(self.manager.boundary_preview_asset(self.case, draft_id, 'axial').stat().st_size, 100)

        record = review()
        record.update(case=self.case, patient_id='synthetic_patient', revision='original',
                     reviewed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        record['openings'] = manifest['controls']['openings']
        record['oral_exclusion'] = {'confirmed': True, 'mode': 'same_as_nasopharynx_outlet',
                                    'boundary_ref': 'nasopharynx_outlet', 'evidence': 'synthetic CT review'}
        record['sinus_policy'] = {'confirmed': True, 'policy': 'exclude_sinuses',
                                  'regions': ['maxillary', 'frontal', 'ethmoid', 'sphenoid'],
                                  'evidence': 'synthetic exclusion mask',
                                  'mask_sha256': manifest['controls']['sinus_policy']['mask_sha256']}
        record['source'] = dict(manifest['binding'])
        record['source']['draft_preview_sha256'] = pipeline.sha256(
            self.directory / generated['boundary_preview']['manifest_path'])
        record['source']['parameters_sha256'] = manifest['parameters_sha256']
        record['evidence_sha256'] = {key: manifest['outputs'][key]['sha256'] for key in EVIDENCE}
        record['source']['revision'] = 'original'
        record['source']['label_sha256'] = manifest['binding']['label_sha256']
        record['source']['parameters_sha256'] = parameters_sha256(record)
        saved = self.manager.save_boundary_review(self.case, draft_id, record)
        self.assertEqual(saved['boundary_review']['status'], 'recorded')
        self.assertEqual(saved['patient_cfd_results'], 0)
        self.assertEqual(saved['stages']['solver'], 'pending')

    def test_failed_generation_does_not_publish_preview_pointer(self):
        with self.assertRaises(FileNotFoundError):
            self.manager.generate_boundary_preview(self.case, {})
        state = self.manager.get(self.case)
        self.assertNotEqual((state.get('boundary_preview') or {}).get('status'), 'generated')


if __name__ == '__main__':
    unittest.main()
