"""Known-answer coordinates and fail-closed HTTP behavior for T030."""
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
from upper_airway_workspace import (
    UpperAirwayWorkspace, SOURCE, BUNDLE, SOURCE_HASHES,
    checked_source, surface_from_mask, verified_bytes,
)
import serve_cfd_workspace as server


class GeometryKnownAnswers(unittest.TestCase):
    def test_rotated_lps_spacing_origin_not_array_axes(self):
        mask = np.zeros((5, 5, 5), bool)
        mask[1:3, 1:3, 1:3] = True
        vertices, faces, facts = surface_from_mask(mask, [2, 3, 5], [10, 20, 30],
                                                  [0, -1, 0, 1, 0, 0, 0, 0, 1])
        # Analytic binary voxel interface at native indices 0.5 and 2.5;
        # L=10-3*j, P=20+2*i, S=30+5*k. No source coordinate inferred by output.
        np.testing.assert_allclose(vertices.min(axis=0), [2.5, 21, 32.5], atol=1e-6)
        np.testing.assert_allclose(vertices.max(axis=0), [8.5, 25, 42.5], atol=1e-6)
        self.assertEqual(facts['source_voxels'], 8)
        self.assertEqual(facts['open_boundary_edges'], 0)
        self.assertEqual(vertices.dtype, np.dtype('<f4'))
        self.assertEqual(faces.dtype, np.dtype('<u4'))

    def test_scanned_face_stays_open_without_padding(self):
        mask = np.zeros((5, 5, 5), bool)
        mask[0:2, 1:3, 1:3] = True
        vertices, _, facts = surface_from_mask(mask, [1, 1, 1], [0, 0, 0], np.eye(3))
        self.assertEqual(vertices[:, 2].min(), 0)
        self.assertGreater(facts['open_boundary_edges'], 0)
        self.assertTrue(np.array_equal(mask[:, 1, 1], [1, 1, 0, 0, 0]))

    def test_empty_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '空掩膜'):
            surface_from_mask(np.zeros((3, 3, 3)), [1]*3, [0]*3, np.eye(3))


class FrozenInputChecks(unittest.TestCase):
    def test_five_real_known_boundary_answers_and_no_identity_mapping(self):
        data = UpperAirwayWorkspace().catalog()
        self.assertEqual([x['inferior_face_air_voxels'] for x in data['cases']], [2105, 1348, 926, 930, 905])
        for item in data['cases']:
            self.assertEqual(item['patient_symptom_mapping'], 'unknown')
            self.assertTrue(item['hypopharynx_empty'])
            self.assertFalse(item['larynx_air_exists'])
            self.assertFalse(item['CFD_admitted'])
            self.assertFalse(item['outlet_selected'])
            self.assertEqual(item['candidate_status'] == 'available', item['case'] == 'p3')

    def test_frozen_p3_source_counts_and_open_inferior_face(self):
        result = UpperAirwayWorkspace().case('p3')
        manifest = result['candidate']
        self.assertEqual(manifest['case'], 'p3')
        self.assertEqual(manifest['surfaces']['baseline']['source_voxels'], 397783)
        self.assertEqual(manifest['surfaces']['added']['source_voxels'], 47809)
        self.assertEqual(manifest['surfaces']['added']['open_boundary_edges'], 170)
        self.assertLess(manifest['surfaces']['baseline']['float32_max_abs_error_mm'], 2e-5)
        self.assertEqual(manifest['source_sha256'], SOURCE_HASHES)

    def test_unknown_case_and_asset_do_not_fallback(self):
        store = UpperAirwayWorkspace()
        for case in ['unknown', '../p3', 'u_0123456789abcdef', 'P3', '']:
            with self.assertRaises(FileNotFoundError):
                store.case(case)
        for case, name in [('p0', 'baseline.vertices.bin'), ('p3', '../manifest.json'),
                           ('p3', 'manifest.json'), ('p3', '/baseline.vertices.bin')]:
            with self.assertRaises(FileNotFoundError):
                store.asset_bytes(case, name)

    def test_missing_changed_source_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(FileNotFoundError):
                checked_source(root)
            (root / 'p0_audit.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, '指纹变化'):
                checked_source(root)

    def test_missing_changed_bundle_rejects_no_partial_available(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = UpperAirwayWorkspace(bundle=root)
            with self.assertRaises(FileNotFoundError):
                store.case('p3')
            shutil.copy(BUNDLE / 'manifest.json', root / 'manifest.json')
            with self.assertRaises(FileNotFoundError):
                store.case('p3')
            (root / 'manifest.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, '指纹变化'):
                store.case('p3')

    def test_changed_binary_rejects_verified_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            value = Path(temp) / 'asset'
            value.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '指纹变化'):
                verified_bytes(value, '0'*64)


class ReadOnlyHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), partial(server.Handler, directory=str(server.BASE)))
        cls.worker = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f'http://127.0.0.1:{cls.httpd.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.worker.join(); cls.httpd.server_close()

    def request(self, path, method='GET'):
        request = Request(self.base + path, method=method,
                          data=b'{}' if method == 'POST' else None,
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_read_endpoints_and_exact_asset(self):
        self.assertEqual(self.request('/api/upper-airway/catalog')[0], 200)
        for case in ['p0', 'p1', 'p2', 'p3t1']:
            status, body = self.request('/api/upper-airway/cases/' + case)
            self.assertEqual(status, 200)
            data = json.loads(body)
            self.assertEqual(data['case'], case)
            self.assertNotIn('candidate', data)
        status, body = self.request('/upper-airway-assets/p3/added.vertices.bin')
        self.assertEqual(status, 200)
        self.assertEqual(body, (BUNDLE / 'added.vertices.bin').read_bytes())

    def test_unknown_traversal_encoded_and_write_paths_rejected(self):
        for path in ['/api/upper-airway/cases/p4', '/api/upper-airway/cases/p3/extra',
                     '/api/upper-airway/cases/u_0123456789abcdef',
                     '/upper-airway-assets/p1/added.vertices.bin',
                     '/upper-airway-assets/p3/../manifest.json',
                     '/upper-airway-assets/p3/%2e%2e%2fmanifest.json',
                     '/upper-airway-assets/p3/manifest.json', '/api/upper-airway/other']:
            self.assertEqual(self.request(path)[0], 404, path)
        self.assertEqual(self.request('/api/upper-airway/cases/p3', 'POST')[0], 404)


if __name__ == '__main__':
    unittest.main(verbosity=2)
