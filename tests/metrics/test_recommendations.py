from __future__ import annotations

import unittest
from copy import deepcopy

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.metrics.recommendations import recommend_from_workflow_comparison
from agent_lifecycle.metrics.regression_signals import (
    build_workflow_comparison_context,
    compare_workflow_economics,
)
from agent_lifecycle.metrics.workflow_economics import WORKFLOW_METRIC_KEYS
from agent_lifecycle.policy.proposals import build_policy_proposal


class WorkflowEconomicsRecommendationTests(unittest.TestCase):
    def test_improvement_is_advisory_and_cannot_mutate_policy(self) -> None:
        comparison = compare_workflow_economics(_context("before", 100), _context("after", 80))

        recommendation = recommend_from_workflow_comparison(
            comparison=comparison,
            task_shape="release",
            current_mode="release",
            required_mode="release",
            protected_work=True,
        )
        proposal = build_policy_proposal(recommendation)

        self.assertEqual(recommendation["status"], "PASS")
        self.assertFalse(recommendation["authorityClaimed"])
        self.assertFalse(recommendation["policyMutationAllowed"])
        self.assertFalse(recommendation["workflowMutationAllowed"])
        self.assertFalse(recommendation["acceptanceMutationAllowed"])
        self.assertFalse(recommendation["gateRemovalAllowed"])
        self.assertFalse(proposal["applyAllowed"])
        self.assertIn("policy-no-change", {item["code"] for item in proposal["refusalReasons"]})

    def test_missing_evidence_returns_low_confidence_without_downgrade(self) -> None:
        before = _context("before", 100)
        after = _context("after", 80)
        after["metrics"]["modelInputTokens"] = {"status": "UNAVAILABLE", "value": None}
        after["contextDigest"] = canonical_digest(
            {key: value for key, value in after.items() if key != "contextDigest"}
        )
        comparison = compare_workflow_economics(before, after)

        recommendation = recommend_from_workflow_comparison(
            comparison=comparison,
            task_shape="feature",
            current_mode="strict",
            required_mode="strict",
        )

        self.assertEqual(comparison["status"], "MIXED")
        self.assertEqual(recommendation["recommendedMode"], "strict")
        self.assertEqual(recommendation["confidence"], "LOW")
        self.assertFalse(recommendation["autoApply"])

    def test_tampered_comparison_fails_recommendation(self) -> None:
        comparison = compare_workflow_economics(_context("before", 100), _context("after", 80))
        tampered = deepcopy(comparison)
        tampered["assurance"]["status"] = "WEAKER"

        recommendation = recommend_from_workflow_comparison(
            comparison=tampered,
            task_shape="feature",
            current_mode="strict",
            required_mode="strict",
        )

        self.assertEqual(recommendation["status"], "FAIL")
        self.assertTrue(recommendation["qualityFloorPreserved"])
        self.assertFalse(recommendation["policyMutationAllowed"])


def _context(role: str, value: int) -> dict:
    metrics = {
        key: {"status": "MEASURED", "value": value}
        for key in WORKFLOW_METRIC_KEYS
        if key not in {"requiredGateCount", "passedGateCount", "failedGateCount"}
    }
    gates = {
        "requiredGateIds": ["architecture", "quality", "security"],
        "passedGateIds": ["architecture", "quality", "security"],
        "failedGateIds": [],
        "qualityFloorDigest": canonical_digest({"floor": "strict"}),
        "acceptanceStatus": "PASS",
    }
    return build_workflow_comparison_context(
        source_digest=canonical_digest({"role": role, "value": value}),
        workload_identity_digest=canonical_digest({"workload": "same"}),
        implementation={"sourceRevision": "same", "coreVersion": "2.14.0", "publicationVersions": {}},
        role=role,
        metrics=metrics,
        gate_outcomes=gates,
        measured_at=f"2026-09-04T00:00:0{1 if role == 'before' else 2}Z",
    )


if __name__ == "__main__":
    unittest.main()
