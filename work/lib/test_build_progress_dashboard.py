"""Progress dashboard tests use only temporary JSON fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import build_progress_dashboard as dashboard


class ProgressDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="nasal_progress_test_")
        self.root = Path(self.tmp.name) / "work"
        self.audit_path = self.root / "06_auto_landmarks" / "feedback_review" / "audit.json"
        self.patch = mock.patch.object(dashboard, "WORK", str(self.root))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def write_audit(self, **overrides):
        audit = {
            "schema": "landmark_feedback_audit/v1",
            "coordinate_system": "LPS",
            "unit": "mm",
            "feedback": [
                {"bound_to_current_proposal": True},
                {"bound_to_current_proposal": False},
            ],
            "input_integrity_verified": True,
        }
        audit.update(overrides)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_path.write_text(json.dumps(audit), encoding="utf-8")

    def test_valid_audit_is_summarized_without_clinical_claim(self):
        self.write_audit()
        summary = dashboard.load_feedback_audit()
        self.assertEqual(summary["status"], "diagnostic_review_complete")
        self.assertEqual(summary["observations"], 2)
        self.assertEqual(summary["matched"], 1)
        html = dashboard.render([], summary)
        self.assertIn("2 条人工意见", html)
        self.assertIn("1 条可绑定当前候选", html)
        self.assertIn("不代表临床接受", html)

    def test_missing_or_invalid_identity_fails_closed(self):
        self.assertEqual(dashboard.load_feedback_audit()["status"], "not_generated")
        self.write_audit(coordinate_system="RAS")
        summary = dashboard.load_feedback_audit()
        self.assertEqual(summary["status"], "invalid")
        html = dashboard.render([], summary)
        self.assertIn("审计摘要身份不符合预期", html)


if __name__ == "__main__":
    unittest.main()
