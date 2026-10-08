"""Synthetic masks test immutable history and publication failures."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import mask_revision_store as module
from mask_revision_store import MaskRevisionStore


class MaskRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MaskRevisionStore(self.root)
        self.mask = np.zeros((4, 5, 6), np.uint8)
        self.mask[1:3, 1:4, 1:5] = 1
        self.geometry = {'coordinate_system': 'LPS', 'unit': 'mm', 'shape_zyx': [4, 5, 6],
                         'spacing_mm': [1.4, 1.2, 1.0], 'origin_lps_mm': [10, 20, 30],
                         'axis_dirs': [[0, 0, 1], [0, 1, 0], [1, 0, 0]]}
        self.original = self.commit(self.mask, None, action='initial')

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, mask, expected, **extra):
        kwargs = {'ct_sha256': 'a' * 64, 'geometry': self.geometry,
                  'expected_revision': expected, 'reviewer': 'Synthetic QA'}
        kwargs.update(extra)
        return self.store.commit(mask, mask, **kwargs)

    def edited(self):
        mask = self.mask.copy()
        mask[0, 0, 0] = 1
        return mask, self.commit(mask, self.original)

    def test_history_undo_and_reset_always_require_review(self):
        _, edited = self.edited()
        restored = self.store.restore(self.original, expected_revision=edited, reviewer='Synthetic QA')
        revision, record, masks = self.store.load()
        self.assertEqual(revision, restored)
        self.assertNotEqual(restored, self.original)
        self.assertEqual(record['sequence'], 3)
        self.assertEqual(record['parent'], edited)
        self.assertEqual(record['restored_from'], self.original)
        self.assertEqual(record['review_status'], 'pending')
        self.assertEqual(record['external_air_validation'], 'pending')
        self.assertFalse(record['patient_solver_allowed'])
        self.assertEqual(set(record['downstream_status'].values()), {'stale'})
        np.testing.assert_array_equal(masks['main'], self.mask)
        self.store.load(self.original)
        self.store.load(edited)
        reset = self.store.restore(self.original, expected_revision=restored,
                                   reviewer='Synthetic QA', action='reset')
        self.assertEqual(self.store.load(reset)[1]['sequence'], 4)

    def test_stale_edit_and_undo_rejected(self):
        mask, edited = self.edited()
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.commit(mask, self.original)
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.store.restore(self.original, expected_revision=self.original, reviewer='Synthetic QA')
        self.assertEqual(self.store.load()[0], edited)

    def test_content_change_rejected_even_if_revision_unchanged(self):
        path = self.root / 'versions' / self.original / 'main.npy'
        altered = self.mask.copy()
        altered[0, 0, 0] = 1
        np.save(path, altered)
        with self.assertRaisesRegex(ValueError, 'content hash'):
            self.store.load()

    def test_record_tamper_rejected(self):
        path = self.root / 'versions' / self.original / 'record.json'
        record = module.read_json(path)
        record['review_status'] = 'confirmed'
        module.write_json(path, record)
        with self.assertRaisesRegex(ValueError, 'record content hash'):
            self.store.load()

    def test_failed_pointer_publish_preserves_current_and_history(self):
        pointer = (self.root / 'current.json').read_bytes()
        original_write = module.write_json

        def deny_pointer(path, record):
            if Path(path) == self.root / 'current.json':
                raise PermissionError('synthetic publish failure')
            return original_write(path, record)

        mask = self.mask.copy()
        mask[0, 0, 0] = 1
        with patch.object(module, 'write_json', side_effect=deny_pointer):
            with self.assertRaises(PermissionError):
                self.commit(mask, self.original)
        self.assertEqual((self.root / 'current.json').read_bytes(), pointer)
        self.assertEqual(self.store.load()[0], self.original)
        self.assertFalse(list((self.root / 'versions').glob('.pending-*')))

    def test_changed_ct_and_geometry_rejected(self):
        geometry = copy.deepcopy(self.geometry)
        geometry['origin_lps_mm'][0] += 1
        for extra in ({'ct_sha256': 'b' * 64}, {'geometry': geometry}):
            with self.assertRaisesRegex(ValueError, 'identity or image geometry'):
                self.commit(self.mask, self.original, **extra)

    def test_invalid_masks_rejected(self):
        invalid = self.mask.astype(float)
        invalid[0, 0, 0] = float('nan')
        for mask in (np.zeros_like(self.mask), self.mask * 2, invalid, self.mask[0]):
            with self.assertRaises(ValueError):
                self.commit(mask, self.original)
        with self.assertRaises(ValueError):
            self.store.commit(np.ones_like(self.mask), self.mask, ct_sha256='a' * 64,
                              geometry=self.geometry, expected_revision=self.original, reviewer='QA')

    def test_reviewer_paths_and_restore_labels_rejected(self):
        with self.assertRaises(ValueError):
            self.commit(self.mask, self.original, reviewer='')
        with self.assertRaises(ValueError):
            self.store.load('../outside')
        with self.assertRaises(ValueError):
            self.store.restore(self.original, expected_revision=self.original, reviewer='QA', action='edit')


if __name__ == '__main__':
    unittest.main()
