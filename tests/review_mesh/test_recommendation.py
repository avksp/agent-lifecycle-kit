from __future__ import annotations

import unittest

from agent_lifecycle.review_mesh.recommendation import (
    recommend_review_mesh_for_plan_manifest,
    recommend_review_mesh_for_text,
    validate_review_mesh_recommendation,
)


class ReviewMeshRecommendationTests(unittest.TestCase):
    def test_low_risk_task_recommends_off_with_skip_rationale(self) -> None:
        receipt = recommend_review_mesh_for_text("Update the README typo")

        self.assertEqual(receipt["recommendedMode"], "off")
        self.assertEqual(receipt["requiredReviewers"], 0)
        self.assertTrue(receipt["skipRationale"])
        self.assertEqual(validate_review_mesh_recommendation(receipt)["status"], "PASS")

    def test_analysis_task_recommends_parallel_research(self) -> None:
        receipt = recommend_review_mesh_for_text("Research the codebase and create an architecture plan")

        self.assertEqual(receipt["recommendedMode"], "parallel-research-synthesis")
        self.assertEqual(receipt["phaseCoverage"], ["research", "planning"])
        self.assertFalse(receipt["blockingGateActivated"])
        self.assertFalse(receipt["assignmentsGenerated"])
        self.assertIn("strong-reasoning", receipt["providerNeutralModelClassHints"])

    def test_bug_task_recommends_leader_review(self) -> None:
        receipt = recommend_review_mesh_for_text("Find and fix the flaky regression")

        self.assertEqual(receipt["recommendedMode"], "leader-draft-multi-review")
        self.assertEqual(receipt["phaseCoverage"], ["planning", "plan-review"])

    def test_implementation_audit_task_recommends_audit_panel(self) -> None:
        receipt = recommend_review_mesh_for_text("Run implementation audit over the completed evidence")

        self.assertEqual(receipt["recommendedMode"], "implementation-audit-panel")
        self.assertEqual(receipt["phaseCoverage"], ["implementation-audit", "final-audit"])

    def test_s2_plan_recommends_leader_review_from_manifest_signals(self) -> None:
        manifest = {
            "schemaVersion": "agent-plan-manifest.v1",
            "status": "FROZEN",
            "package": {"id": "release-x", "title": "Release X"},
            "specification": {
                "tier": "S2",
                "tierResolutionRequest": {"riskFlags": {"architecture": True}},
                "requirements": [{"description": "Add a shared architecture gate"}],
            },
        }

        receipt = recommend_review_mesh_for_plan_manifest(manifest)

        self.assertEqual(receipt["recommendedMode"], "leader-draft-multi-review")
        self.assertEqual(receipt["source"]["kind"], "PLAN_MANIFEST")

    def test_provider_and_money_fields_fail_validation(self) -> None:
        receipt = recommend_review_mesh_for_text("Investigate a security regression")
        receipt["budgetCap"] = {**receipt["budgetCap"], "costUsd": 1}
        receipt["provider"] = "example"
        receipt["recommendationDigest"] = "0" * 64

        validation = validate_review_mesh_recommendation(receipt)

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("review-mesh-recommendation-money-cap-not-allowed", codes)
        self.assertIn("review-mesh-recommendation-provider-model-name-not-portable", codes)


if __name__ == "__main__":
    unittest.main()
