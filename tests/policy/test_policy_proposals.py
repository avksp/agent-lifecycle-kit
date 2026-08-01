from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.metrics import recommend_lifecycle_mode  # noqa: E402
from agent_lifecycle.policy import apply_policy_proposal, build_policy_proposal, build_policy_summary  # noqa: E402


class PolicyProposalTests(unittest.TestCase):
    def test_low_risk_overhead_reduction_can_be_applied_explicitly(self) -> None:
        proposal = build_policy_proposal(_small_fix_recommendation())

        self.assertEqual(proposal["schemaVersion"], "agent-lifecycle-policy-proposal.v1")
        self.assertEqual(proposal["status"], "PASS")
        self.assertTrue(proposal["applyAllowed"])
        self.assertEqual(proposal["candidateChanges"][0]["before"], "strict")
        self.assertEqual(proposal["candidateChanges"][0]["after"], "light")
        self.assertTrue(proposal["qualityConstraints"]["qualityFloorPreserved"])

    def test_protected_downgrade_is_not_applyable(self) -> None:
        recommendation = _recommendation(task_shape="adapter", current_mode="release", recommended_mode="strict")

        proposal = build_policy_proposal(recommendation, risk_flags=["security"])

        self.assertEqual(proposal["status"], "PASS")
        self.assertFalse(proposal["applyAllowed"])
        self.assertIn("policy-protected-downgrade", {item["code"] for item in proposal["refusalReasons"]})

    def test_low_confidence_refuses_apply(self) -> None:
        recommendation = _recommendation(confidence="LOW", current_mode="standard", recommended_mode="light")

        proposal = build_policy_proposal(recommendation)

        self.assertFalse(proposal["applyAllowed"])
        self.assertIn("policy-low-confidence", {item["code"] for item in proposal["refusalReasons"]})

    def test_regression_signals_block_apply(self) -> None:
        proposal = build_policy_proposal(
            _small_fix_recommendation(),
            regression_signals=[{"type": "reopenedWork", "count": 1, "severity": "HIGH"}],
        )

        self.assertFalse(proposal["applyAllowed"])
        self.assertIn("policy-regression-signals", {item["code"] for item in proposal["refusalReasons"]})

    def test_invalid_recommendation_fails_closed(self) -> None:
        proposal = build_policy_proposal({"schemaVersion": "wrong.v1"})

        self.assertEqual(proposal["status"], "FAIL")
        self.assertFalse(proposal["applyAllowed"])
        self.assertIn("policy-recommendation-schema", {item["code"] for item in proposal["refusalReasons"]})

    def test_apply_writes_tuned_policy_only_for_allowed_proposal(self) -> None:
        proposal = build_policy_proposal(_small_fix_recommendation())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tuned-policy.json"
            result = apply_policy_proposal(proposal, out)
            payload = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(result["schemaVersion"], "agent-lifecycle-policy-apply-result.v1")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-tuned-policy.v1")
        self.assertEqual(payload["changes"][0]["after"], "light")

    def test_apply_rejects_refused_proposal(self) -> None:
        proposal = build_policy_proposal(_recommendation(confidence="LOW"))

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LifecycleError):
                apply_policy_proposal(proposal, Path(tmp) / "tuned-policy.json")

    def test_compact_summary_has_required_context_fields(self) -> None:
        summary = build_policy_summary(build_policy_proposal(_small_fix_recommendation()))

        self.assertEqual(summary["schemaVersion"], "agent-lifecycle-policy-summary.v1")
        for field in ["latestUserIntent", "activeDecisions", "acceptedEvidence", "nextRequiredAction", "doNotDo"]:
            self.assertIn(field, summary)

    def test_learning_recommendation_preserves_local_benefit_metadata(self) -> None:
        recommendation = _recommendation(current_mode="strict", recommended_mode="light")
        recommendation["statistics"] = {
            "schemaVersion": "agent-quality-cost-learning-statistics.v1",
            "selectedSignal": {"averageTokens": 900, "successRate": 1.0},
        }

        proposal = build_policy_proposal(recommendation)

        self.assertEqual(proposal["expectedBenefit"]["localAverageTokens"], 900)
        self.assertEqual(proposal["expectedBenefit"]["localSuccessRate"], 1.0)


def _small_fix_recommendation() -> dict[str, object]:
    return recommend_lifecycle_mode(
        reports=[_high_overhead_report(), _high_overhead_report()],
        baseline_profile=_baselines(),
        task_shape="small-fix",
        current_mode="strict",
    )


def _baselines() -> dict[str, object]:
    return json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))


def _high_overhead_report() -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-cost-report.v1",
        "mode": "release",
        "entries": [
            {"category": "implementation", "tokens": 1500, "steps": 2, "usageConfidence": "ATTESTED"},
            {"category": "productValidation", "tokens": 600, "steps": 2, "usageConfidence": "ESTIMATED"},
            {"category": "pipelineCompliance", "tokens": 2500, "steps": 3, "usageConfidence": "ESTIMATED"},
            {"category": "coordination", "tokens": 900, "steps": 1, "usageConfidence": "ESTIMATED"},
        ],
        "overLimitReason": "Release-sensitive checks were intentionally broad.",
        "productionPromotionClaimed": False,
    }


def _recommendation(
    *,
    task_shape: str = "small-fix",
    current_mode: str = "strict",
    recommended_mode: str = "light",
    confidence: str = "HIGH",
) -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-recommendation.v1",
        "status": "PASS",
        "taskShape": task_shape,
        "currentMode": current_mode,
        "recommendedMode": recommended_mode,
        "confidence": confidence,
        "advisoryOnly": True,
        "autoApply": False,
        "qualityFloor": "strict" if task_shape == "adapter" else "light",
        "qualityFloorPreserved": True,
        "warnings": [],
        "reasons": [],
        "statistics": {"totals": {"pipelineCompliance": {"tokens": 1000}, "coordination": {"tokens": 100}}, "ratios": {}},
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    unittest.main()
