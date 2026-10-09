"""Independent shape controls for local diagnosis, including adjacency folds."""
from pathlib import Path
import tempfile
import unittest
import shutil
from unittest.mock import patch

import numpy as np
from ct_case_pipeline import sha256
from locate_surface_intersections import pair_contact, locate, triangle_metrics, native_style_segment_query
from validate_surface_origin import translation_control


class ContactTests(unittest.TestCase):
    def test_geometry_controls_under_translation_rotation_and_scale(self):
        a = np.array([[0., 0, 0], [2, 0, 0], [0, 2, 0]])
        fixtures = [
            (a + [0, 0, 1], 'disjoint'),
            (np.array([[0., 0, 0], [2, 0, 0], [0, -2, 0]]), 'expected_shared_edge'),
            (np.array([[0., 0, 0], [-2, 0, 0], [0, -2, 0]]), 'expected_shared_vertex'),
            (a + [.2, .2, 0], 'coplanar_area_overlap'),
            (np.array([[0., 0, 0], [1, 0, 0], [0, -1, 0]]), 'coplanar_contact_beyond_shared'),
            (np.array([[0., 0, 0], [1, .1, 1], [.1, 1, -1]]), 'crossing_beyond_shared_contact'),
            (np.array([[.3, .3, -1], [.3, .3, 1], [1., .3, 0]]), 'crossing_beyond_shared_contact'),
            (np.array([[2., 0, 0], [3, 0, 1], [3, 1, 1]]), 'expected_shared_vertex'),
        ]
        rng = np.random.default_rng(42)
        for scale in (.001, 1, 100):
            for rotation_index in range(4):
                rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
                translation = np.array([23., -238, 845])
                for b, expected in fixtures:
                    with self.subTest(scale=scale, rotation=rotation_index, expected=expected):
                        result = pair_contact(a @ rotation * scale + translation,
                                              b @ rotation * scale + translation)
                        self.assertEqual(result['kind'], expected)

    def test_equilateral_quality_is_one(self):
        triangle = np.array([[0., 0, 0], [.001, 0, 0], [.0005, np.sqrt(3) / 2000, 0]])
        self.assertAlmostEqual(triangle_metrics(triangle)['quality_equilateral_1'], 1)

    def test_real_native_fixture_localization(self):
        # Reuse previously executed native crossing control, not patients.
        fixture = Path(__file__).resolve().parents[2] / '.tools/native-surface-controls-20261008-r9/crossing'
        if not fixture.is_dir():
            self.skipTest('Existing native control is unavailable')
        report = locate(fixture, coordinate_mode='native_stl_float32')
        self.assertGreater(report['hits_with_suspicious_contact'], 0)
        self.assertTrue(report['precision']['native_vtp_vertex_set_match'])
        self.assertFalse(report['patient_solver_allowed'])
        self.assertTrue(report['all_components_retained'])

    def test_input_tampering_refused(self):
        fixture = Path(__file__).resolve().parents[2] / '.tools/native-surface-controls-20261008-r9/crossing'
        if not fixture.is_dir():
            self.skipTest('Existing native control is unavailable')
        for filename in ('combined.stl', 'wall.stl', 'selfInterPoints.obj'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / 'input'
                shutil.copytree(fixture, target)
                with (target / filename).open('a') as stream:
                    stream.write('\n# tampered\n')
                with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                    locate(target)

    def test_empty_hit_control_is_covered_without_gate_promotion(self):
        fixture = Path(__file__).resolve().parents[2] / '.tools/native-surface-controls-20261008-r9/clean'
        if not fixture.is_dir():
            self.skipTest('Existing native control is unavailable')
        report = locate(fixture, coordinate_mode='native_stl_float32')
        self.assertEqual(report['hit_count'], 0)
        self.assertEqual(report['candidate_triangles'], [])
        self.assertFalse(report['patient_solver_allowed'])

    def test_unperturbed_edge_query(self):
        triangle = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]])
        hit = native_style_segment_query(np.array([.2, .2, -1]), np.array([.2, .2, 1]), triangle)
        np.testing.assert_allclose(hit['point_m'], [.2, .2, 0])
        self.assertIsNone(native_style_segment_query(np.array([2., 2, -1]), np.array([2., 2, 1]), triangle))
        self.assertIsNone(native_style_segment_query(np.array([.1, .1, 0]), np.array([.2, .1, 0]), triangle))

    def test_translation_retains_all_triangles_and_rejects_overwrite(self):
        fixture = Path(__file__).resolve().parents[2] / '.tools/native-surface-controls-20261008-r9/crossing'
        if not fixture.is_dir():
            self.skipTest('Existing native control is unavailable')
        # Native execution itself was validated separately in r13; this test
        # covers the serializer and inverse coordinate/topology contracts.
        with tempfile.TemporaryDirectory() as temp, patch('validate_surface_origin.native_check'):
            target = Path(temp) / 'control'
            before = sha256(fixture / 'combined.stl')
            report = translation_control(fixture, target)
            self.assertEqual(report['original_qc']['triangles'], report['translated_qc']['triangles'])
            self.assertLessEqual(report['maximum_inverse_coordinate_error_m'], 1e-14)
            self.assertTrue(report['all_components_retained'])
            self.assertFalse(report['geometry_repaired'])
            self.assertFalse(report['patient_solver_allowed'])
            self.assertEqual(sha256(fixture / 'combined.stl'), before)
            with self.assertRaises(FileExistsError):
                translation_control(fixture, target)


if __name__ == '__main__':
    unittest.main()
