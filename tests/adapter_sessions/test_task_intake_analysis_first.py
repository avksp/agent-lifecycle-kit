from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.task_intake import start_adapter_task


class AdapterTaskIntakeAnalysisFirstTests(unittest.TestCase):
    def test_analysis_before_feature_marks_analysis_first_without_repo_inspection(self) -> None:
        receipt = start_adapter_task(
            adapter_id="codex",
            task_text="- Analyze code before implementing the new adapter task entrypoint",
        )

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["detectedTaskShape"], "analysis-first")
        self.assertTrue(receipt["preImplementationAnalysis"]["required"])
        self.assertEqual(receipt["preImplementationAnalysis"]["purpose"], "feature-discovery")
        self.assertFalse(receipt["executionStarted"])
        self.assertNotIn("bug-forensics", receipt["recommendedQualityProfiles"])

    def test_analysis_of_bug_can_recommend_bug_forensics_too(self) -> None:
        receipt = start_adapter_task(adapter_id="codex", task_text="- Analyze code before fixing this regression")

        self.assertEqual(receipt["detectedTaskShape"], "bugfix")
        self.assertTrue(receipt["preImplementationAnalysis"]["required"])
        self.assertIn("bug-forensics", receipt["recommendedQualityProfiles"])


if __name__ == "__main__":
    unittest.main()
