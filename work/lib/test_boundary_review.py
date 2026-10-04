"""Boundary-review contract tests; this record is separate from landmark review."""

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from boundary_review import EVIDENCE, load_boundary_review, parameters_sha256, validate_record, write_boundary_review


HASHES = {
    "ct": "a" * 64,
    "candidate": "b" * 64,
    "landmarks": "c" * 64,
    "label": "d" * 64,
}


def plane():
    return {
        "status": "confirmed",
        "point_lps_mm": [1, 2, 3],
        "normal_lps": [0, 0, 1],
        "roi_lps_mm": {"min": [0, 0, 0], "max": [10, 10, 10]},
        "keep_positive": True,
    }


def review():
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record = {
        "schema": "boundary_review/v1",
        "case": "u_0123456789abcdef",
        "patient_id": "patient_01",
        "revision": "v_0123456789abcdef",
        "coordinate_system": "LPS",
        "unit": "mm",
        "status": "confirmed",
        "method": "human",
        "reviewer": "Dr QA",
        "reviewed_at": timestamp,
        "source": {
            "revision": "v_0123456789abcdef",
            "ct_sha256": HASHES["ct"],
            "candidate_sha256": HASHES["candidate"],
            "landmark_review_sha256": HASHES["landmarks"],
            "label_sha256": {"nasal_cavity_left": HASHES["label"]},
            "draft_preview_sha256": "e" * 64,
        },
        "openings": {
            "nostril_L": plane(), "nostril_R": plane(),
            "nasopharynx_outlet": plane(),
        },
        "oral_exclusion": {
            "confirmed": True,
            "mode": "same_as_nasopharynx_outlet",
            "boundary_ref": "nasopharynx_outlet",
            "evidence": "CT axial and sagittal review",
        },
        "sinus_policy": {
            "confirmed": True,
            "policy": "exclude_sinuses",
            "regions": ["maxillary", "frontal", "ethmoid", "sphenoid"],
            "evidence": "CT review and exclusion mask",
            "mask_sha256": HASHES["label"],
        },
        "evidence_sha256": {key: "f" * 64 for key in EVIDENCE},
    }
    record["source"]["parameters_sha256"] = parameters_sha256(record)
    return record


EXPECTED = {
    "case": "u_0123456789abcdef",
    "patient_id": "patient_01",
    "revision": "v_0123456789abcdef",
    "ct_sha256": HASHES["ct"],
    "candidate_sha256": HASHES["candidate"],
    "landmark_review_sha256": HASHES["landmarks"],
    "label_sha256": {"nasal_cavity_left": HASHES["label"]},
    "draft_preview_sha256": "e" * 64,
    "parameters_sha256": review()["source"]["parameters_sha256"],
    "evidence_sha256": {key: "f" * 64 for key in EVIDENCE},
    "sinus_mask_sha256": HASHES["label"],
}


class BoundaryReviewTests(unittest.TestCase):
    def test_valid_record_binds_all_inputs(self):
        self.assertEqual(validate_record(review(), EXPECTED)["schema"], "boundary_review/v1")

    def test_invalid_json_types_and_huge_numbers_are_validation_errors(self):
        for value in (10 ** 1000, True, "1", float("inf")):
            candidate = review()
            candidate["openings"]["nostril_L"]["point_lps_mm"][0] = value
            with self.subTest(value_type=type(value).__name__), self.assertRaisesRegex(ValueError, "finite numbers"):
                validate_record(candidate, EXPECTED)
        candidate = review()
        candidate["oral_exclusion"]["mode"] = []
        with self.assertRaisesRegex(ValueError, "oral_exclusion.mode"):
            validate_record(candidate, EXPECTED)

    def test_missing_oral_or_sinus_policy_is_rejected(self):
        for field in ("oral_exclusion", "sinus_policy"):
            candidate = review()
            candidate.pop(field)
            with self.assertRaisesRegex(ValueError, field):
                validate_record(candidate, EXPECTED)

    def test_zero_normal_and_reversed_roi_are_rejected(self):
        candidate = review()
        candidate["openings"]["nostril_L"]["normal_lps"] = [0, 0, 0]
        with self.assertRaisesRegex(ValueError, "non-zero"):
            validate_record(candidate, EXPECTED)
        candidate = review()
        candidate["openings"]["nostril_L"]["roi_lps_mm"] = {
            "min": [2, 0, 0], "max": [1, 10, 10]
        }
        with self.assertRaisesRegex(ValueError, "lower than max"):
            validate_record(candidate, EXPECTED)

    def test_hash_or_revision_mismatch_is_rejected(self):
        candidate = review()
        candidate["source"]["ct_sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "ct_sha256"):
            validate_record(candidate, EXPECTED)
        candidate = review()
        candidate["revision"] = "v_fedcba9876543210"
        with self.assertRaisesRegex(ValueError, "revision"):
            validate_record(candidate, EXPECTED)

    def test_atomic_write_and_load(self):
        with tempfile.TemporaryDirectory(prefix="boundary_review_") as directory:
            path = Path(directory) / "boundary_review.json"
            write_boundary_review(path, review(), EXPECTED)
            loaded = load_boundary_review(path, EXPECTED)
            self.assertEqual(loaded["case"], EXPECTED["case"])
            self.assertFalse(list(Path(directory).glob("*.tmp")))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "confirmed")

    def test_write_does_not_replace_existing_record_on_validation_failure(self):
        with tempfile.TemporaryDirectory(prefix="boundary_review_") as directory:
            path = Path(directory) / "boundary_review.json"
            write_boundary_review(path, review(), EXPECTED)
            before = path.read_bytes()
            broken = copy.deepcopy(review())
            broken["sinus_policy"].pop("policy")
            with self.assertRaises(ValueError):
                write_boundary_review(path, broken, EXPECTED)
            self.assertEqual(path.read_bytes(), before)

    def test_parameter_changes_require_new_preview(self):
        for field, value in (("point_lps_mm", [2, 2, 3]), ("normal_lps", [0, 1, 0]),
                             ("roi_lps_mm", {"min": [0, 0, 0], "max": [5, 5, 5]}),
                             ("keep_positive", False)):
            with self.subTest(field=field):
                candidate = review()
                candidate["openings"]["nostril_L"][field] = value
                with self.assertRaisesRegex(ValueError, "cutting controls"):
                    validate_record(candidate, EXPECTED)
                candidate["source"]["parameters_sha256"] = parameters_sha256(candidate)
                with self.assertRaisesRegex(ValueError, "current case identity"):
                    validate_record(candidate, EXPECTED)

    def test_missing_context_evidence_and_wrong_patient_are_rejected(self):
        for key in EXPECTED:
            context = copy.deepcopy(EXPECTED)
            context.pop(key)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "complete current"):
                validate_record(review(), context)
        candidate = review()
        candidate["patient_id"] = "another-patient"
        with self.assertRaisesRegex(ValueError, "patient_id"):
            validate_record(candidate, EXPECTED)
        candidate = review()
        candidate["evidence_sha256"]["axial"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "evidence_sha256"):
            validate_record(candidate, EXPECTED)

    def test_nonfinite_boolean_and_naive_timestamp_are_rejected(self):
        for value in (float('nan'), float('inf'), True):
            candidate = review()
            candidate["openings"]["nostril_L"]["normal_lps"][0] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                validate_record(candidate, EXPECTED)
        candidate = review()
        candidate["reviewed_at"] = "2026-10-04T09:00:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            validate_record(candidate, EXPECTED)

    def test_separate_oral_wall_is_explicit_and_sinus_scope_is_fixed(self):
        candidate = review()
        candidate["oral_exclusion"] = {"confirmed": True, "mode": "separate_plane",
                                       "boundary": plane(), "evidence": "Separate oral wall"}
        candidate["source"]["parameters_sha256"] = parameters_sha256(candidate)
        self.assertEqual(validate_record(candidate)["oral_exclusion"]["mode"], "separate_plane")
        candidate["sinus_policy"]["policy"] = "retain_sinuses"
        with self.assertRaisesRegex(ValueError, "G_main"):
            validate_record(candidate)

    def test_replace_failure_preserves_previous_record_and_cleans_temp(self):
        with tempfile.TemporaryDirectory(prefix="boundary_review_") as directory:
            path = Path(directory) / "boundary_review.json"
            write_boundary_review(path, review(), EXPECTED)
            before = path.read_bytes()
            with patch('boundary_review.os.replace', side_effect=OSError('injected failure')):
                with self.assertRaises(OSError):
                    write_boundary_review(path, review(), EXPECTED)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(list(Path(directory).glob('*.tmp')))


if __name__ == "__main__":
    unittest.main()
