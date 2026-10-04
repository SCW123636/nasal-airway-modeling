"""Content reuse must fail closed when inputs or outputs change."""
import tempfile
from pathlib import Path
import unittest

from run_auto_anatomy import LABELS, can_reuse, file_sha256, input_identity


class ContentReuseTests(unittest.TestCase):
    def test_only_exact_verified_successful_content_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'landmarks.json'
            output.write_text('{"point": [1,2,3]}', encoding='utf-8')
            identity = {'input_sha256': {'ct.nii.gz': 'known-synthetic-content'}}
            receipt = {'identity': identity, 'status': 'generated',
                       'output_sha256': {str(output): file_sha256(output)}}
            self.assertTrue(can_reuse(receipt, identity))
            self.assertFalse(can_reuse(receipt, {'input_sha256': {'ct.nii.gz': 'changed'}}))
            output.write_text('{"point": [4,5,6]}', encoding='utf-8')
            self.assertFalse(can_reuse(receipt, identity))
            output.unlink()
            self.assertFalse(can_reuse(receipt, identity))

    def test_incomplete_or_failed_receipt_cannot_be_reused(self):
        self.assertFalse(can_reuse({}, {}))
        self.assertFalse(can_reuse({'identity':{},'status':'generated','output_sha256':{}}, {}))
        self.assertFalse(can_reuse({'identity':{},'status':'failed','output_sha256':{}}, {}))

    def test_reference_library_change_invalidates_candidate_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data/'masks').mkdir()
            (data/'ct.nii.gz').write_bytes(b'synthetic CT content')
            for name in LABELS:
                (data/'masks'/f'{name}.nii.gz').write_bytes(name.encode())
            library = data/'references.json'
            library.write_text('{"references":[]}', encoding='utf-8')
            before = input_identity(data, library)
            library.write_text('{"references":["changed"]}', encoding='utf-8')
            after = input_identity(data, library)
            self.assertEqual(before['input_sha256'], after['input_sha256'])
            self.assertNotEqual(before['coarse_reference'], after['coarse_reference'])


if __name__ == '__main__':
    unittest.main()
