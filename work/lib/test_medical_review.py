"""Version-bound offline feedback, using isolated synthetic artifacts."""
import base64
import copy
from functools import partial
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
import zipfile

from build_auto_landmark_review import build_review
import ct_case_pipeline as pipeline
from medical_review import MedicalReviewStore, safe_asset
import serve_cfd_workspace as server
from test_build_auto_landmark_review import fixture
import test_ct_boundary_review as boundary_fixture

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=')


class MedicalFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='medical_feedback_')
        self.root = Path(self.temp.name)
        self.manager = pipeline.CaseManager(self.root / 'cases')
        self.review = self.root / 'existing'
        self.store = MedicalReviewStore(self.manager, self.review)
        self.ct = self.root / 'ct.nii.gz'
        self.ct.write_bytes(b'synthetic input identity')
        self.make_case('p0', self.review)
        self.case = self.manager.create({'kind':'dicom', 'files':[{'name':'fixture.dcm','size':2}]})['id']
        self.manager.upload(self.case, 0, io.BytesIO(b'CT'), 2)
        directory = self.manager.root / self.case
        (directory / 'ct.nii.gz').write_bytes(b'synthetic input identity')
        self.make_case(self.case, directory / 'public/review')
        public = directory / 'public'
        pipeline.write_json(directory / 'receipt.json', {
            'schema':'ct_case_receipt/v1', 'case':self.case,
            'output_sha256':{p.relative_to(public).as_posix():pipeline.sha256(p) for p in public.rglob('*') if p.is_file()},
            'identity':{'input_sha256':{'ct.nii.gz':pipeline.sha256(directory / 'ct.nii.gz')}}})
        pipeline.update(directory, status='awaiting_review', artifacts={'review':f'/case-assets/{self.case}/review/index.html'})

    def tearDown(self):
        self.manager.pool.shutdown(wait=True)
        self.temp.cleanup()

    def make_case(self, case, root):
        data = fixture(); data['case'] = case
        data['source_ct'] = str(self.ct)
        data['input_provenance'] = {'input_sha256':{'ct.nii.gz':pipeline.sha256(self.ct)}}
        pipeline.write_json(root / case / 'landmarks.json', data)
        (root / case / 'review.png').write_bytes(PNG)
        build_review(root, cases=[case])

    def reply(self, case='p0', stage='landmarks'):
        _, digest = self.store.export(case, stage)
        manifest = pipeline.read_json(self.store.storage(case) / 'packages' / (digest + '.json'))
        return {'schema':'medical_review_feedback/v1', 'case':case, 'stage':stage, 'package_sha256':digest,
                'coordinate_system':'LPS', 'unit':'mm', 'reviewer':'Synthetic QA',
                'reviewed_at':'2026-10-06T12:00:00+08:00',
                'items':[{'id':i['id'], 'decision':'accept' if i['reviewable'] else 'insufficient', 'note':'',
                          'adjusted_point_lps_mm':None, 'adjusted_normal_lps':None} for i in manifest['items']]}

    def test_export_is_standalone_and_escapes_untrusted_labels(self):
        path = self.review / 'p0/landmarks.json'
        data = pipeline.read_json(path)
        attack = '</script><img src=x onerror=alert(1)>'
        data['landmarks']['nostril_L']['label_zh'] = attack
        pipeline.write_json(path, data); build_review(self.review)
        html, digest = self.store.export('p0', 'landmarks')
        text = html.decode('utf-8')
        self.assertIn('data:image/png;base64,', text)
        self.assertIn("connect-src 'none'", text)
        self.assertNotIn(attack, text)
        self.assertNotIn(str(self.root), text)
        self.assertEqual(len(digest), 64)

    def test_roundtrip_and_duplicate_import_are_idempotent(self):
        for case in ('p0', self.case):
            with self.subTest(case=case):
                reply = self.reply(case)
                first = self.store.import_feedback(case, reply)
                self.assertEqual(first, self.store.import_feedback(case, copy.deepcopy(reply)))
                records = self.store.list_feedback(case)['records']
                self.assertEqual(len(records), 1)
                self.assertTrue(records[0]['current'])

    def test_batch_has_standalone_pages_and_independent_feedback_bindings(self):
        archive = self.store.export_batch(['p0', self.case], ['landmarks', 'boundary'])
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            expected = {f'{case}_{label}_医学复核.html' for case in ('p0', self.case) for label in ('切片', '边界')}
            self.assertEqual(set(package.namelist()), expected | {'医学复核使用说明.txt'})
            self.assertIsNone(package.testzip())
            for filename in expected:
                html = package.read(filename).decode('utf-8')
                payload = json.loads(re.search(r'<script id="package-data" type="application/json">(.*?)</script>', html, re.S)[1])
                manifest = payload['manifest']
                self.assertIn("connect-src 'none'", html)
                self.assertNotIn(str(self.root), html)
                self.assertEqual(len(manifest['items']), 2 if manifest['stage'] == 'landmarks' else 9)
                if manifest['stage'] == 'landmarks':
                    self.assertIn('data:image/png;base64,', html)
                stored = pipeline.read_json(self.store.storage(manifest['case']) / 'packages' / (payload['package_sha256'] + '.json'))
                self.assertEqual(stored, manifest)
                reply = {'schema':'medical_review_feedback/v1', 'case':manifest['case'], 'stage':manifest['stage'],
                         'package_sha256':payload['package_sha256'], 'coordinate_system':'LPS', 'unit':'mm',
                         'reviewer':'Synthetic batch QA', 'reviewed_at':'2026-10-06T12:00:00+08:00',
                         'items':[{'id':i['id'], 'decision':'pending', 'note':'',
                                   'adjusted_point_lps_mm':None, 'adjusted_normal_lps':None} for i in manifest['items']]}
                record = self.store.import_feedback(manifest['case'], reply)
                saved = next(r for r in self.store.list_feedback(manifest['case'])['records'] if r['id'] == record['id'])
                self.assertTrue(saved['current'])
                self.assertEqual(saved['feedback']['stage'], manifest['stage'])
        for case in ('p0', self.case):
            self.assertEqual(len(self.store.list_feedback(case)['records']), 2)

    def test_batch_rejects_empty_duplicate_and_invalid_selections(self):
        for cases, stages in [(None,['landmarks']), ([],['landmarks']), ('p0',['landmarks']),
                              (['p0','p0'],['landmarks']), ([{}],['landmarks']), (['unknown'],['landmarks']),
                              (['p0'],[]), (['p0'],None), (['p0'],['landmarks','landmarks']),
                              (['p0'],[{}]), (['p0'],['unknown'])]:
            with self.subTest(cases=cases, stages=stages):
                with self.assertRaises(ValueError): self.store.export_batch(cases, stages)

    def test_batch_failure_or_changed_evidence_does_not_register_partial_packages(self):
        original = self.store.build
        def fail_second(case, stage):
            if case == self.case: raise ValueError('不可用的证据')
            return original(case, stage)
        with patch.object(self.store, 'build', side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, self.case):
                self.store.export_batch(['p0', self.case], ['landmarks'])
        self.assertFalse(list(self.manager.root.rglob('packages/*.json')))
        write = zipfile.ZipFile.writestr
        def change_after_compression(archive, filename, data, *args, **kwargs):
            result = write(archive, filename, data, *args, **kwargs)
            if filename.endswith('.txt'):
                (self.review / 'p0/review.png').write_bytes(PNG + b'changed while compressing')
            return result
        with patch.object(zipfile.ZipFile, 'writestr', change_after_compression):
            with self.assertRaisesRegex(ValueError, '发生变化'):
                self.store.export_batch(['p0', self.case], ['landmarks'])
        self.assertFalse(list(self.manager.root.rglob('packages/*.json')))

    def test_batch_compression_failure_does_not_register_packages(self):
        with patch.object(zipfile.ZipFile, 'writestr', side_effect=OSError('isolated zip failure')):
            with self.assertRaises(OSError): self.store.export_batch(['p0', self.case], ['landmarks'])
        self.assertFalse(list(self.manager.root.rglob('packages/*.json')))

    def test_wrong_case_stage_version_and_units_are_rejected(self):
        reply = self.reply()
        for field, value in [('case','p1'), ('stage','boundary'), ('package_sha256','0'*64), ('unit','m'), ('coordinate_system','RAS')]:
            with self.subTest(field=field):
                changed = copy.deepcopy(reply); changed[field] = value
                with self.assertRaises(ValueError): self.store.import_feedback('p0', changed)

    def test_changed_evidence_and_inputs_cannot_accept_old_feedback(self):
        reply = self.reply(); record = self.store.import_feedback('p0', reply)
        (self.review / 'p0/review.png').write_bytes(PNG + b'changed')
        with self.assertRaisesRegex(ValueError, '过期'): self.store.import_feedback('p0', reply)
        self.assertFalse(self.store.list_feedback('p0')['records'][0]['current'])
        with self.assertRaisesRegex(ValueError, '过期'): self.store.decisions('p0', record['id'], ['nostril_L'])
        self.ct.write_bytes(b'new input')
        with self.assertRaisesRegex(ValueError, '变化'): self.store.export('p0', 'landmarks')

    def test_missing_and_duplicate_items_cannot_be_imported(self):
        reply = self.reply()
        for items in (reply['items'][:1], [reply['items'][0]] * 2):
            changed = copy.deepcopy(reply); changed['items'] = items
            with self.assertRaises(ValueError): self.store.import_feedback('p0', changed)

    def test_adjustment_and_rejection_require_valid_details(self):
        reply = self.reply(); item = reply['items'][0]
        item.update(decision='adjust', note='建议调整', adjusted_point_lps_mm=[2, 3, 4])
        self.store.import_feedback('p0', reply)
        for point, normal in [([True,2,3],None), ([float('nan'),2,3],None), ([2,3,4],[0,0,0]), ([1,2],None)]:
            changed = copy.deepcopy(reply); changed['items'][0].update(adjusted_point_lps_mm=point, adjusted_normal_lps=normal)
            with self.assertRaises(ValueError): self.store.import_feedback('p0', changed)
        item.update(decision='reject', adjusted_point_lps_mm=None, note='')
        with self.assertRaises(ValueError): self.store.import_feedback('p0', reply)
        reply['reviewed_at'] = '2026-10-06T12:00:00'; item['note'] = '不符合'
        with self.assertRaisesRegex(ValueError, '时区'): self.store.import_feedback('p0', reply)

    def test_incomplete_evidence_cannot_pass_or_adjust(self):
        reply = self.reply(stage='boundary')
        for decision in ('accept','adjust'):
            reply['items'][0].update(decision=decision, note='test')
            with self.assertRaisesRegex(ValueError, '证据未齐'): self.store.import_feedback('p0', reply)
        point = self.reply(); point['items'][1]['decision'] = 'accept'
        with self.assertRaisesRegex(ValueError, '证据未齐'): self.store.import_feedback('p0', point)

    def test_registration_corruption_and_export_import_races_are_rejected(self):
        reply = self.reply()
        path = self.store.storage('p0') / 'packages' / (reply['package_sha256'] + '.json')
        manifest = pipeline.read_json(path); manifest['items'][1]['reviewable'] = True
        pipeline.write_json(path, manifest)
        with self.assertRaisesRegex(ValueError, '损坏'): self.store.import_feedback('p0', reply)
        reply = self.reply(); result = self.store.build('p0', 'landmarks')
        changed = copy.deepcopy(result); changed[0]['package_sha256'] = '0'*64
        with patch.object(self.store, 'build', side_effect=[result,changed]):
            with self.assertRaisesRegex(ValueError, '发生变化'): self.store.import_feedback('p0', reply)
        with patch.object(self.store, 'build', side_effect=[result,changed]):
            with self.assertRaisesRegex(ValueError, '发生变化'): self.store.export('p0', 'landmarks')

    def test_selection_conversion_preserves_saved_review_and_rejects_invalid_ids(self):
        reply = self.reply(self.case); record = self.store.import_feedback(self.case, reply)
        directory = self.manager.root / self.case
        saved = directory / 'review_decisions.json'; saved.write_bytes(b'prior review unchanged')
        converted = self.store.decisions(self.case, record['id'], ['nostril_L'])
        self.assertEqual([i['landmark_id'] for i in converted['cases'][0]['decisions']], ['nostril_L'])
        self.assertEqual(saved.read_bytes(), b'prior review unchanged')
        for selected in ([], [{}], [['nostril_L']], ['nostril_L']*2, ['unknown']):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError): self.store.decisions(self.case, record['id'], selected)

    def test_paths_stay_in_evidence_directory(self):
        with self.assertRaises(ValueError): safe_asset(self.review, '../ct.nii.gz')
        with self.assertRaises(ValueError): safe_asset(self.review, '%2e%2e/ct.nii.gz')

    def test_real_boundary_context_includes_each_generated_evidence(self):
        fixture_test = boundary_fixture.CTBoundaryReviewTests()
        fixture_test.setUp()
        try:
            manifest_path = fixture_test.draft / 'manifest.json'
            manifest = pipeline.read_json(manifest_path)
            for name, item in manifest['outputs'].items():
                if name != 'sinus_exclusion_mask':
                    target = fixture_test.draft / item['path']; target.write_bytes(PNG)
                    item['sha256'] = pipeline.sha256(target)
            manifest['controls'] = {'openings':fixture_test.record['openings'], 'oral_exclusion':fixture_test.record['oral_exclusion']}
            pipeline.write_json(manifest_path, manifest)
            pipeline.update(fixture_test.directory, boundary_preview={'status':'generated','draft_id':fixture_test.draft_id,'sha256':pipeline.sha256(manifest_path)})
            store = MedicalReviewStore(fixture_test.manager, self.review)
            payload = store.build(fixture_test.case, 'boundary')[0]
            self.assertEqual(sum(i['reviewable'] for i in payload['manifest']['items']), 8)
            self.assertFalse(payload['manifest']['items'][-1]['reviewable'])
            self.assertEqual(len(payload['manifest']['items'][0]['evidence']), 4)
            (fixture_test.draft / manifest['outputs']['axial']['path']).write_bytes(PNG + b'changed')
            with self.assertRaisesRegex(ValueError, '变化'): store.export(fixture_test.case, 'boundary')
        finally:
            fixture_test.tearDown()

    def test_http_export_import_selection_and_cross_origin(self):
        previous = (server.CASE_MANAGER, server.CASE_ROOT, server.MEDICAL_REVIEW)
        server.CASE_MANAGER, server.CASE_ROOT, server.MEDICAL_REVIEW = self.manager, self.manager.root, self.store
        http = ThreadingHTTPServer(('127.0.0.1',0), partial(server.Handler, directory=str(server.BASE)))
        thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
        url = f'http://127.0.0.1:{http.server_port}'
        def call(path, data=None, origin=None):
            headers = {'Content-Type':'application/json'}
            if origin: headers['Origin'] = origin
            request = Request(url+path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
            try:
                with urlopen(request,timeout=10) as response: return response.status,response.read()
            except HTTPError as error: return error.code,error.read()
        try:
            self.assertEqual(call('/api/medical-review/catalog')[0],200)
            status,html = call('/api/cases/p0/medical-review-export?stage=landmarks')
            self.assertEqual(status,200); self.assertIn(b'data:image/png;base64,',html)
            selection = {'cases':['p0',self.case], 'stages':['landmarks','boundary']}
            self.assertEqual(call('/api/medical-review/export', selection, 'http://example.com')[0], 400)
            status,archive = call('/api/medical-review/export', selection, url)
            self.assertEqual(status, 200)
            with zipfile.ZipFile(io.BytesIO(archive)) as package:
                self.assertEqual(len(package.namelist()), 5)
                self.assertIsNone(package.testzip())
            self.assertEqual(call('/api/medical-review/export', {'cases':[], 'stages':['landmarks']}, url)[0], 400)
            reply = self.reply(); path = '/api/cases/p0/medical-feedback'
            self.assertEqual(call(path,reply,'http://example.com')[0],400)
            status,body = call(path,reply,url); self.assertEqual(status,201)
            record = json.loads(body)['id']
            self.assertEqual(call(path+'/'+record+'/decisions',{'items':['nostril_L']})[0],200)
            self.assertEqual(call(path+'/'+record+'/decisions',{'items':[{}]})[0],400)
            self.assertEqual(call(path+'/'+record+'/adopt',{'items':['nostril_L']})[0],404)
            self.assertTrue(json.loads(call(path)[1])['records'][0]['current'])
        finally:
            http.shutdown(); thread.join(); http.server_close()
            server.CASE_MANAGER, server.CASE_ROOT, server.MEDICAL_REVIEW = previous


if __name__ == '__main__':
    unittest.main()
