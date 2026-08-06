from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.task_intake import start_adapter_task


class AdapterTaskIntakeBugForensicsTests(unittest.TestCase):
    def test_defect_shaped_input_recommends_bug_forensics_only_as_draft_marker(self) -> None:
        receipt = start_adapter_task(adapter_id="codex", task_text="- Find and fix the flaky regression")

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["detectedTaskShape"], "bugfix")
        self.assertIn("bug-forensics", receipt["recommendedQualityProfiles"])
        self.assertEqual(receipt["bugForensicsAdvisory"]["recommendation"], "SUGGEST")
        self.assertTrue(receipt["bugForensicsAdvisory"]["gateBoundary"]["advisoryOnly"])
        self.assertFalse(receipt["bugForensicsAdvisory"]["gateBoundary"]["activeWorkflowGateClaimed"])
        self.assertFalse(receipt["preImplementationAnalysis"]["activeWorkflowGateClaimed"])
        self.assertFalse(receipt["lifecycleCoverageClaimed"])

    def test_feature_input_does_not_recommend_bug_forensics(self) -> None:
        receipt = start_adapter_task(adapter_id="codex", task_text="- Add adapter task intake docs")

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertNotIn("bug-forensics", receipt["recommendedQualityProfiles"])
        self.assertEqual(receipt["bugForensicsAdvisory"]["recommendation"], "NOT_APPLICABLE")


if __name__ == "__main__":
    unittest.main()
