"""HTTP import and private/public boundaries, without invoking inference."""
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from functools import partial
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import serve_cfd_workspace as server
from ct_case_pipeline import CaseManager


class LocalHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ct_http_')
        self.old_manager, self.old_root = server.CASE_MANAGER, server.CASE_ROOT
        server.CASE_ROOT = Path(self.temp.name)
        server.CASE_MANAGER = CaseManager(server.CASE_ROOT)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.BASE)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True);self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.thread.join();self.server.server_close()
        server.CASE_MANAGER.pool.shutdown(wait=True)
        server.CASE_MANAGER, server.CASE_ROOT = self.old_manager, self.old_root
        self.temp.cleanup()

    def call(self, path, payload=None, method='GET', headers=None):
        raw = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.url + path, data=raw, method=method,
                          headers={'Content-Type':'application/json', **(headers or {})})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def create(self):
        status, body = self.call('/api/cases', {'kind':'dicom','files':[{'name':'../private-name.dcm','size':8}]}, 'POST')
        self.assertEqual(status, 201)
        return json.loads(body)['id']

    def test_create_upload_and_persist_private_files(self):
        case = self.create()
        request = Request(self.url+f'/api/cases/{case}/files/0',data=b'12345678',method='PUT',headers={'Content-Type':'application/octet-stream'})
        with urlopen(request) as response:
            self.assertEqual(json.load(response)['uploaded_files'], 1)
        status, body = self.call('/api/cases/'+case)
        self.assertEqual(status, 200);self.assertNotIn(b'private-name', body);self.assertNotIn(b'stored_name', body)
        self.assertEqual((server.CASE_ROOT/case/'raw/000000.dcm').read_bytes(), b'12345678')
        for suffix in ['/raw/000000.dcm','/case.json','/../raw/000000.dcm']:
            self.assertEqual(self.call('/case-assets/'+case+suffix)[0], 404)
        public = server.CASE_ROOT/case/'public';public.mkdir()
        (public/'test.json').write_text('{"generated":true}', encoding='utf-8')
        self.assertEqual(self.call('/case-assets/'+case+'/test.json')[0], 200)
        self.assertEqual(self.call('/case-assets/'+case+'/../case.json')[0], 404)

    def test_cross_origin_and_wrong_host_writes_are_rejected(self):
        payload = {'kind':'zip','files':[{'name':'ct.zip','size':10}]}
        self.assertEqual(self.call('/api/cases',payload,'POST',{'Origin':'http://example.com'})[0],400)
        self.assertEqual(self.call('/api/cases',payload,'POST',{'Host':'example.com'})[0],400)
        self.assertEqual(self.call('/api/cases',payload,'POST',{'Origin':self.url})[0],201)

    def test_delete_case_removes_private_case_and_requires_local_origin(self):
        case = self.create()
        raw = server.CASE_ROOT / case / 'raw' / '000000.dcm'
        raw.write_bytes(b'CT')
        status, body = self.call('/api/cases/' + case, method='DELETE')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {'id': case, 'deleted': True})
        self.assertFalse((server.CASE_ROOT / case).exists())
        self.assertEqual(self.call('/api/cases/' + case)[0], 404)
        self.assertNotIn(case, [item['id'] for item in json.loads(self.call('/api/cases')[1])['cases']])
        self.assertEqual(self.call('/api/cases/' + case, method='DELETE', headers={'Origin':'http://example.com'})[0], 400)

    def test_delete_rejects_processing_case_and_invalid_id(self):
        case = self.create()
        server.CASE_MANAGER.pending.add(case)
        try:
            self.assertEqual(self.call('/api/cases/' + case, method='DELETE')[0], 400)
        finally:
            server.CASE_MANAGER.pending.discard(case)
        self.assertEqual(self.call('/api/cases/not-a-case', method='DELETE')[0], 404)

    def test_start_and_review_fail_until_candidate_exists(self):
        case = self.create()
        self.assertEqual(self.call('/api/cases/'+case+'/start',{},'POST')[0],400)
        self.assertEqual(self.call('/api/cases/'+case+'/review',{},'POST')[0],400)
        self.assertEqual(self.call('/api/cases/'+case+'/regenerate',{},'POST')[0],400)
        self.assertEqual(self.call('/api/cases/not-a-case')[0],404)
        self.assertEqual(self.call('/api/cases/'+case+'/unknown',{},'POST')[0],404)
        self.assertEqual(json.loads(self.call('/health.json')[1])['ct_import'], True)

    def test_boundary_routes_are_explicit_and_local_only(self):
        case = self.create()
        generated = {'id': case, 'boundary_preview': {'status': 'generated', 'draft_id': 'd_0123456789abcdef'},
                     'boundary_preview_manifest': {'schema': 'boundary_draft_preview/v1'}}
        with patch.object(server.CASE_MANAGER, 'generate_boundary_preview', return_value=generated) as generate:
            status, body = self.call('/api/cases/' + case + '/boundary-preview',
                                     {'oral_exclusion_confirmed': True, 'sinus_policy_confirmed': True}, 'POST')
            self.assertEqual(status, 201)
            self.assertEqual(json.loads(body)['boundary_preview']['draft_id'], 'd_0123456789abcdef')
            generate.assert_called_once()
        with patch.object(server.CASE_MANAGER, 'upload_boundary_mask', return_value={'id': case}) as upload:
            request = Request(self.url + f'/api/cases/{case}/boundary-mask', data=b'NIFTI', method='PUT',
                              headers={'Content-Type': 'application/octet-stream'})
            with urlopen(request) as response:
                self.assertEqual(response.status, 200)
            upload.assert_called_once()
        with patch.object(server.CASE_MANAGER, 'save_boundary_review', return_value={'id': case}) as save:
            status, body = self.call('/api/cases/' + case + '/boundary-review',
                                     {'draft_id': 'd_0123456789abcdef', 'record': {}}, 'POST')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['id'], case)
            save.assert_called_once_with(case, 'd_0123456789abcdef', {})


if __name__ == '__main__':
    unittest.main()
