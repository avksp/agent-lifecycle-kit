from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from agent_lifecycle.metrics import (  # noqa: E402
    build_quality_cost_signals,
    build_task_outcome_index,
    recommend_from_quality_cost_signals,
    recommend_lifecycle_mode,
    summarize_lifecycle_overhead,
)


class LifecycleRecommendationTests(unittest.TestCase):
    def test_multi_report_statistics_are_deterministic(self) -> None:
        reports = [_cost_report("standard"), _cost_report("standard")]

        first = summarize_lifecycle_overhead(reports)
        second = summarize_lifecycle_overhead(reports)

        self.assertEqual(canonical_digest(first), canonical_digest(second))
        self.assertEqual(first["schemaVersion"], "agent-lifecycle-overhead-statistics.v1")
        self.assertEqual(first["reportCount"], 2)
        self.assertEqual(first["status"], "PASS")

    def test_recommendation_warns_and_suggests_lighter_mode_for_small_fix(self) -> None:
        recommendation = recommend_lifecycle_mode(
            reports=[_high_overhead_report(), _high_overhead_report()],
            baseline_profile=_baselines(),
            task_shape="small-fix",
            current_mode="strict",
        )

        self.assertEqual(recommendation["status"], "PASS")
        self.assertEqual(recommendation["recommendedMode"], "light")
        self.assertEqual(recommendation["confidence"], "MEDIUM")
        self.assertIn("pipeline-token-share-high", {item["code"] for item in recommendation["warnings"]})
        self.assertFalse(recommendation["autoApply"])
        self.assertTrue(recommendation["qualityFloorPreserved"])

    def test_high_risk_work_cannot_downgrade_below_quality_floor(self) -> None:
        recommendation = recommend_lifecycle_mode(
            reports=[_high_overhead_report(), _high_overhead_report(), _high_overhead_report()],
            baseline_profile=_baselines(),
            task_shape="adapter",
            current_mode="release",
            sdd_tier="S2",
            risk_flags=["security"],
        )

        self.assertEqual(recommendation["recommendedMode"], "release")
        self.assertIn(recommendation["confidence"], {"MEDIUM", "HIGH"})
        self.assertTrue(recommendation["qualityFloorPreserved"])

    def test_low_data_keeps_current_or_floor_mode(self) -> None:
        recommendation = recommend_lifecycle_mode(
            reports=[_missing_usage_report()],
            baseline_profile=_baselines(),
            task_shape="feature",
            current_mode="standard",
        )

        self.assertEqual(recommendation["confidence"], "LOW")
        self.assertEqual(recommendation["recommendedMode"], "standard")
        self.assertIn("missing-usage", {item["code"] for item in recommendation["warnings"]})
        self.assertIn("weak-statistics", {item["code"] for item in recommendation["warnings"]})

    def test_invalid_baseline_fails_closed(self) -> None:
        profile = _baselines()
        profile["taskShapes"]["feature"]["minMode"] = "unsupported"

        recommendation = recommend_lifecycle_mode(
            reports=[_cost_report("standard"), _cost_report("standard")],
            baseline_profile=profile,
            task_shape="feature",
            current_mode="standard",
        )

        self.assertEqual(recommendation["status"], "FAIL")
        self.assertEqual(recommendation["recommendedMode"], "standard")
        self.assertTrue(recommendation["qualityFloorPreserved"])
        self.assertIn("baseline-shape-mode", {item["code"] for item in recommendation["blockers"]})

    def test_invalid_cost_report_fails_closed(self) -> None:
        report = _cost_report("standard")
        report["entries"] = []

        recommendation = recommend_lifecycle_mode(
            reports=[report],
            baseline_profile=_baselines(),
            task_shape="feature",
            current_mode="standard",
        )

        self.assertEqual(recommendation["status"], "FAIL")
        self.assertEqual(recommendation["recommendedMode"], "standard")
        self.assertIn("cost-report-invalid", {item["code"] for item in recommendation["blockers"]})

    def test_compact_summary_has_context_fields(self) -> None:
        recommendation = recommend_lifecycle_mode(
            reports=[_cost_report("standard"), _cost_report("standard")],
            baseline_profile=_baselines(),
            task_shape="feature",
        )
        summary = recommendation["compactSummary"]

        self.assertEqual(summary["schemaVersion"], "agent-lifecycle-recommendation-summary.v1")
        for field in ["latestUserIntent", "activeDecisions", "acceptedEvidence", "nextRequiredAction", "doNotDo"]:
            self.assertIn(field, summary)

    def test_learning_recommendation_uses_local_outcome_signals(self) -> None:
        signals = build_quality_cost_signals(
            build_task_outcome_index(
                [
                    _outcome("WS-01", mode="light", tokens=800),
                    _outcome("WS-02", mode="light", tokens=900),
                    _outcome("WS-03", mode="strict", tokens=4000),
                ]
            )
        )

        recommendation = recommend_from_quality_cost_signals(
            signals=signals,
            baseline_profile=_baselines(),
            task_shape="small-fix",
            current_mode="strict",
        )

        self.assertEqual(recommendation["schemaVersion"], "agent-lifecycle-recommendation.v1")
        self.assertEqual(recommendation["status"], "PASS")
        self.assertEqual(recommendation["recommendedMode"], "light")
        self.assertIn(recommendation["confidence"], {"MEDIUM", "HIGH"})
        self.assertTrue(recommendation["advisoryOnly"])
        self.assertFalse(recommendation["autoApply"])
        self.assertTrue(recommendation["qualityFloorPreserved"])
        self.assertEqual(recommendation["qualityCostSignals"]["selectedSignal"]["lifecycleMode"], "light")
        self.assertEqual(recommendation["rollback"]["requiresReview"], True)

    def test_learning_recommendation_fails_closed_for_unsafe_signals(self) -> None:
        signals = build_quality_cost_signals(
            build_task_outcome_index(
                [
                    _outcome("WS-01", mode="light", tokens=800),
                    _outcome("WS-02", mode="light", tokens=900),
                ]
            )
        )
        signals["providerModelLeaderboard"] = True

        recommendation = recommend_from_quality_cost_signals(
            signals=signals,
            baseline_profile=_baselines(),
            task_shape="small-fix",
            current_mode="strict",
        )

        self.assertEqual(recommendation["status"], "FAIL")
        self.assertEqual(recommendation["recommendedMode"], "strict")
        self.assertFalse(recommendation["autoApply"])
        self.assertIn("quality-cost-provider-leaderboard", {item["code"] for item in recommendation["blockers"]})


def _baselines() -> dict[str, object]:
    return json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))


def _cost_report(mode: str) -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-cost-report.v1",
        "mode": mode,
        "entries": [
            {"category": "implementation", "tokens": 6000, "steps": 4, "usageConfidence": "ATTESTED"},
            {"category": "productValidation", "tokens": 1500, "steps": 2, "usageConfidence": "ESTIMATED"},
            {"category": "pipelineCompliance", "tokens": 1200, "steps": 2, "usageConfidence": "ESTIMATED"},
            {"category": "coordination", "tokens": 300, "steps": 1, "usageConfidence": "ESTIMATED"},
        ],
        "productionPromotionClaimed": False,
    }


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


def _missing_usage_report() -> dict[str, object]:
    report = _cost_report("standard")
    report["entries"] = [{"category": "implementation", "tokens": 0, "steps": 1, "usageConfidence": "MISSING"}]
    return report


def _outcome(task_id: str, *, mode: str, tokens: int) -> dict[str, object]:
    return {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "packageId": "package",
        "taskId": task_id,
        "taskShape": "small-fix",
        "lifecycleMode": mode,
        "routeClass": "local-code",
        "status": "PASS",
        "commands": [{"id": "VAL", "exitCode": 0}],
        "usage": {"inputTokens": tokens, "outputTokens": 50, "billableTokens": tokens + 50, "wallSeconds": 5, "toolCalls": 1},
    }


if __name__ == "__main__":
    unittest.main()
