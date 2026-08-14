from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics.audit_optimization import (  # noqa: E402
    build_audit_optimization_report,
    build_audit_statistics,
    evaluate_candidate_profiles,
    recommend_audit_optimization,
)
from agent_lifecycle.metrics.audit_samples import build_audit_sample  # noqa: E402


class AuditOptimizationTests(unittest.TestCase):
    def test_three_attested_samples_produce_quality_and_resource_statistics(self) -> None:
        samples = [build_audit_sample(_receipt(index)) for index in range(3)]

        statistics = build_audit_statistics(samples)

        self.assertEqual(statistics["status"], "PASS")
        self.assertEqual(statistics["confidence"], "MEDIUM")
        self.assertEqual(statistics["signals"]["quality"]["successRate"], 1.0)
        self.assertEqual(statistics["signals"]["tokens"]["count"], 3)
        self.assertEqual(statistics["signals"]["resources"]["cpuMs"]["availability"], "ATTESTED")

    def test_insufficient_evidence_does_not_recommend(self) -> None:
        samples = [build_audit_sample(_receipt(1))]
        statistics = build_audit_statistics(samples)
        evaluation = evaluate_candidate_profiles([_candidate("safe")])

        recommendation = recommend_audit_optimization(statistics=statistics, evaluation=evaluation)

        self.assertEqual(recommendation["status"], "NO_RECOMMENDATION")
        self.assertIn("statistics-not-sufficient", {item["code"] for item in recommendation["reasons"]})

    def test_false_acceptance_blocks_optimization(self) -> None:
        samples = [build_audit_sample(_receipt(index, false_acceptance=True)) for index in range(3)]
        statistics = build_audit_statistics(samples)
        evaluation = evaluate_candidate_profiles([_candidate("safe")])

        recommendation = recommend_audit_optimization(statistics=statistics, evaluation=evaluation)

        self.assertEqual(recommendation["status"], "NO_RECOMMENDATION")
        self.assertIn("quality-regression-signals", {item["code"] for item in recommendation["reasons"]})

    def test_quality_safe_candidate_is_selected_on_shared_holdout(self) -> None:
        samples = [build_audit_sample(_receipt(index)) for index in range(3)]
        safe = _candidate("safe")
        unsafe = _candidate("unsafe", quality=False)

        report = build_audit_optimization_report(
            samples,
            candidate_profiles=[safe, unsafe],
            task_shape="feature",
            current_profile={"packetTokenLimit": 10000},
        )

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["recommendation"]["selectedProfileId"], "safe")
        self.assertTrue(report["recommendation"]["advisoryOnly"])
        self.assertFalse(report["recommendation"]["autoApply"])
        self.assertNotIn("provider", str(report["recommendation"]).lower())

    def test_holdout_cap_is_a_hard_blocker(self) -> None:
        evaluation = evaluate_candidate_profiles(
            [_candidate("safe", task_count=3)],
            max_holdout_tasks=2,
        )

        self.assertEqual(evaluation["status"], "FAIL")
        self.assertIn("holdout-task-cap-exceeded", {item["code"] for item in evaluation["blockers"]})


def _candidate(profile_id: str, *, quality: bool = True, task_count: int = 3) -> dict[str, object]:
    return {
        "profileId": profile_id,
        "taskShape": "feature",
        "qualityFloor": "standard",
        "routeClass": "standard",
        "packetTokenLimit": 12000,
        "reviewerCountHint": 2,
        "timeoutSeconds": 900,
        "retryLimit": 1,
        "holdoutTasks": [
            {"taskId": f"{profile_id}-{index}", "qualityPass": quality, "billableTokens": 400 + index, "wallSeconds": 10 + index}
            for index in range(task_count)
        ],
    }


def _receipt(index: int, *, false_acceptance: bool = False) -> dict[str, object]:
    return {
        "operationId": f"operation-{index}",
        "runId": f"run-{index}",
        "packageId": "release-1-70",
        "taskId": f"task-{index}",
        "taskShape": "feature",
        "reviewReceipt": {
            "schemaVersion": "agent-review-mesh-result.v1",
            "status": "PASS",
            "findings": [],
            "independence": {"status": "INDEPENDENT"},
            "reviewer": {"role": "independent-reviewer", "modelClass": "standard"},
        },
        "usageReceipt": {
            "usage": {"inputTokens": 1000, "outputTokens": 500, "billableTokens": 1500, "wallSeconds": 12},
            "attestation": {"status": "ATTESTED"},
        },
        "processReceipt": {
            "resources": {
                "cpuMs": {"value": 120, "availability": "ATTESTED"},
                "peakMemoryMb": {"value": 64, "availability": "ATTESTED"},
                "processCount": {"value": 1, "availability": "ATTESTED"},
            },
            "timing": {"elapsedMs": 12000},
            "retry": {"count": 0},
            "timedOut": False,
        },
        "outcomeReceipt": {
            "status": "ACCEPTED",
            "falseAcceptance": false_acceptance,
        },
    }


if __name__ == "__main__":
    unittest.main()
