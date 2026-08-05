from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.task_intake import start_adapter_task


class AdapterTaskIntakeReviewMeshTests(unittest.TestCase):
    def test_raw_analysis_input_includes_advisory_review_mesh_recommendation(self) -> None:
        receipt = start_adapter_task(
            adapter_id="codex",
            task_text="Research the codebase and produce a plan before implementation",
        )

        recommendation = receipt["reviewMeshRecommendation"]
        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(recommendation["schemaVersion"], "agent-review-mesh-recommendation.v1")
        self.assertEqual(recommendation["recommendedMode"], "parallel-research-synthesis")
        self.assertFalse(recommendation["modelCallsStarted"])
        self.assertFalse(recommendation["hostLaunchStarted"])
        self.assertFalse(recommendation["blockingGateActivated"])
        self.assertFalse(receipt["executionStarted"])

    def test_raw_feature_input_can_recommend_off_without_changing_intake_status(self) -> None:
        receipt = start_adapter_task(adapter_id="codex", task_text="Update the docs index")

        self.assertEqual(receipt["status"], "REVIEW_REQUIRED")
        self.assertEqual(receipt["reviewMeshRecommendation"]["recommendedMode"], "off")
        self.assertTrue(receipt["requiresReview"])


if __name__ == "__main__":
    unittest.main()
