"""Synthetic imports exercise physical sorting, upload bounds and review gates."""
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid
import SimpleITK as sitk

import ct_case_pipeline as pipeline
from build_auto_landmark_review import build_review
from confirm_landmark_review import load_proposal_bundle


def dicom_slices(root, zs=(0., .8, 1.6, 2.4), uid=None):
    uid = uid or generate_uid()
    study, frame = generate_uid(), generate_uid()
    result = []
    for index, z in enumerate(zs):
        file = root / f'{uid[-8:]}_{index}.dcm'
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = CTImageStorage
        meta.MediaStorageSOPInstanceUID = generate_uid()
        ds = FileDataset(str(file), {}, file_meta=meta, preamble=b'\0' * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = meta.MediaStorageSOPClassUID, meta.MediaStorageSOPInstanceUID
        ds.Modality, ds.SeriesInstanceUID, ds.StudyInstanceUID, ds.FrameOfReferenceUID = 'CT', uid, study, frame
        ds.PatientName = 'Synthetic^DoNotExpose'
        ds.Rows = ds.Columns = 8
        ds.ImagePositionPatient, ds.ImageOrientationPatient = [3, 4, z], [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing, ds.SliceThickness = [.6, .5], .8
        ds.InstanceNumber = 500 - index  # Physical positions must win over instance/file order.
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, 'MONOCHROME2'
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit, ds.PixelRepresentation = 15, 1
        ds.RescaleSlope, ds.RescaleIntercept, ds.RescaleType = 1, 0, 'HU'
        array = np.full((8, 8), -900 + index, dtype='<i2')
        array[2:4, 2:4] = 300
        ds.PixelData = array.tobytes()
        ds.save_as(file, enforce_file_format=True)
        result.append(file)
    return result


class CTCaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ct_case_tests_')
        self.root = Path(self.temp.name)
        self.manager = pipeline.CaseManager(self.root / 'cases')

    def tearDown(self):
        self.manager.pool.shutdown(wait=True)
        self.temp.cleanup()

    def upload(self, paths, kind='dicom', hu=True):
        data = self.manager.create({'kind': kind, 'hu_confirmed': hu,
                                    'files': [{'name': p.name, 'size': p.stat().st_size} for p in paths]})
        for i, path in enumerate(paths):
            with path.open('rb') as source:
                self.manager.upload(data['id'], i, source, path.stat().st_size)
        return self.manager.root / data['id']

    def test_sorts_physical_positions_and_keeps_ct_geometry(self):
        files = dicom_slices(self.root, (2.4, 0., 1.6, .8))
        series = pipeline.discover_dicom(files)
        self.assertTrue(series[0]['valid'])
        self.assertEqual(series[0]['files'][0], str(files[1]))
        directory = self.upload(files)
        self.assertTrue(pipeline.import_ct(directory))
        image = sitk.ReadImage(str(directory / 'ct.nii.gz'))
        np.testing.assert_allclose(image.GetSpacing(), [.5, .6, .8], atol=1e-6)
        np.testing.assert_allclose(image.GetOrigin(), [3, 4, 0], atol=1e-6)
        self.assertEqual(image.GetSize(), (8, 8, 4))
        self.assertNotIn('Synthetic', json.dumps(self.manager.public(self.manager.get(directory.name))))

    def test_multiple_series_waits_for_selection(self):
        directory = self.upload(dicom_slices(self.root) + dicom_slices(self.root))
        self.assertFalse(pipeline.import_ct(directory))
        self.assertFalse((directory / 'ct.nii.gz').exists())
        data = self.manager.get(directory.name)
        self.assertEqual(data['status'], 'awaiting_series')
        self.assertEqual(len(data['series']), 2)
        with self.assertRaises(ValueError):
            self.manager.start(directory.name)
        pipeline.update(directory, selected_series='s2')
        self.assertTrue(pipeline.import_ct(directory))

    def test_missing_and_repeated_slice_positions_fail(self):
        for zs in [(0, 1, 3, 4), (0, 1, 1, 2)]:
            record = pipeline.discover_dicom(dicom_slices(self.root, zs))[0]
            self.assertFalse(record['valid'])

    def test_inconsistent_orientation_and_multiframe_fail(self):
        for field, value in [('ImageOrientationPatient', [0, 1, 0, 1, 0, 0]), ('NumberOfFrames', 2)]:
            files = dicom_slices(self.root)
            ds = pydicom.dcmread(files[-1]);setattr(ds, field, value);ds.save_as(files[-1], enforce_file_format=True)
            self.assertFalse(pipeline.discover_dicom(files)[0]['valid'])

    def test_exact_duplicate_instance_is_deduplicated(self):
        files = dicom_slices(self.root)
        duplicate = self.root / 'copy.dcm';duplicate.write_bytes(files[0].read_bytes())
        record = pipeline.discover_dicom(files + [duplicate])[0]
        self.assertTrue(record['valid']);self.assertEqual(record['slice_count'], 4)

    def test_bad_archive_member_cannot_escape(self):
        for member in ['../evil.dcm', '/evil.dcm', 'C:/evil.dcm', 'a/../../evil.dcm']:
            archive = self.root / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as stream:
                stream.writestr(member, b'content')
            with self.assertRaises(ValueError):
                pipeline.unpack_archive(archive, self.root / 'extract')
        self.assertFalse((self.root / 'evil.dcm').exists())

    def test_nested_zip_decodes_ct_using_generated_names(self):
        files = dicom_slices(self.root)
        archive = self.root / 'ct.zip'
        with zipfile.ZipFile(archive, 'w') as stream:
            for index, file in enumerate(files):
                stream.write(file, f'patient-name/folder/{index}.dcm')
        directory = self.upload([archive], 'zip')
        self.assertTrue(pipeline.import_ct(directory))
        self.assertEqual(len(list((directory / 'extracted').iterdir())), 4)
        self.assertFalse((directory / 'extracted/patient-name').exists())

    def test_nifti_requires_hu_confirmation_and_finite_volume(self):
        array = np.full((5, 6, 7), -900, dtype=np.int16);array[:, 2:4, 2:4] = 300
        image = sitk.GetImageFromArray(array);image.SetSpacing([.35, .6, .8])
        file = self.root / 'ct.nii.gz';sitk.WriteImage(image, str(file))
        bad = self.upload([file], 'nifti', hu=False)
        with self.assertRaises(ValueError):pipeline.import_ct(bad)
        good = self.upload([file], 'nifti')
        self.assertTrue(pipeline.import_ct(good))
        with self.assertRaises(ValueError):pipeline.validate_ct(sitk.GetImageFromArray(np.ones((5,5,5))))

    def test_incomplete_upload_and_length_mismatch_do_not_start(self):
        data = self.manager.create({'kind': 'dicom', 'files': [{'name': '../patient.dcm', 'size': 8}]})
        with self.assertRaises(ValueError):self.manager.start(data['id'])
        with self.assertRaises(ValueError):self.manager.upload(data['id'], 0, io.BytesIO(b'x'), 1)
        with self.assertRaises(ValueError):self.manager.upload(data['id'], 0, io.BytesIO(b'abc'), 8)
        self.assertEqual(self.manager.public(self.manager.get(data['id']))['uploaded_files'], 0)
        self.assertFalse(list((self.manager.root / data['id'] / 'raw').iterdir()))

    def test_restarts_are_explicit_and_duplicate_start_is_rejected(self):
        file = self.root / 'ct.dcm';file.write_bytes(b'CT')
        directory = self.upload([file])
        with patch.object(self.manager.pool, 'submit'):
            self.assertEqual(self.manager.start(directory.name)['status'], 'queued')
            with self.assertRaises(ValueError):self.manager.start(directory.name)
        other = pipeline.CaseManager(self.manager.root)
        self.assertEqual(other.get(directory.name)['status'], 'interrupted')
        other.pool.shutdown(wait=True)

    def test_bad_ids_never_resolve_outside_root(self):
        for key in ['../p0', 'p0', 'u_x', 'u_' + 'a' * 16 + '/../../p0']:
            with self.assertRaises(ValueError):pipeline.case_dir(self.root, key)

    def test_live_worker_is_retained_across_server_restart(self):
        import os
        file = self.root / 'ct.dcm';file.write_bytes(b'CT')
        directory = self.upload([file])
        pipeline.update(directory, status='running', worker_pid=os.getpid())
        self.assertTrue(pipeline.process_alive(os.getpid()))
        other = pipeline.CaseManager(self.manager.root)
        try:
            self.assertEqual(other.get(directory.name)['status'], 'running')
            pipeline.update(directory, status='failed')
            with self.assertRaises(ValueError):other.start(directory.name)
        finally:
            other.pool.shutdown(wait=True)

    def test_pending_review_does_not_confirm_geometry_or_solver(self):
        file = self.root / 'ct.dcm';file.write_bytes(b'CT')
        directory = self.upload([file])
        case = directory.name
        proposals = directory / 'public/review'
        report = {'case': case, 'coordinate_system': 'LPS', 'unit': 'mm', 'landmarks': {
            'nostril_L': {'status': 'proposed', 'point_lps_mm': [1,2,3], 'normal_lps': [0,1,0], 'roi_lps_mm': [6,6,6]}}}
        pipeline.write_json(proposals / case / 'landmarks.json', report)
        build_review(proposals, cases=[case])
        pipeline.write_json(directory / 'receipt.json', {'output_sha256': {'review/index.html': pipeline.sha256(proposals/'index.html')}, 'identity': {'input_sha256': {}}})
        pipeline.update(directory, status='awaiting_review')
        bundle = load_proposal_bundle(proposals / 'index.html')
        src = bundle['cases'][0]; lm = src['landmarks'][0]
        decisions = {'artifact_type':'landmark_review_decisions','coordinate_system':'LPS','unit':'mm','reviewer':'QA',
                     'proposal_bundle_sha256':bundle['proposal_bundle_sha256'], 'cases':[{'case':case,'source_sha256':src['source_sha256'],
                     'decisions':[{'landmark_id':'nostril_L','proposal_sha256':lm['proposal_sha256'], 'original_point_lps_mm':[1,2,3],
                                   'original_normal_lps':[0,1,0],'decision':'pending'}]}]}
        state = self.manager.save_review(case, decisions)
        self.assertEqual(state['status'], 'awaiting_review');self.assertEqual(state['stages']['solver'], 'pending')
        confirmed = pipeline.read_json(directory / 'review_config_confirmed.json')
        self.assertFalse(confirmed['boundary_confirmations']['oral_exclusion_confirmed'])
        self.assertIsNone(confirmed['geometry_binding']['reviewed_geometry_sha256'])
        stale = copy.deepcopy(decisions);stale['proposal_bundle_sha256'] = 'wrong'
        with self.assertRaises(ValueError):self.manager.save_review(case, stale)
        with (proposals / 'index.html').open('a') as out:out.write('changed')
        with self.assertRaises(ValueError):self.manager.save_review(case, decisions)


if __name__ == '__main__':
    unittest.main()
