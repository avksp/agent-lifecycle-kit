from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.benchmarks import (
    compare_reference_task_evaluations,
    evaluate_reference_task,
    validate_reference_task_comparison,
)
from agent_lifecycle.benchmarks.reporting import build_measurements
from agent_lifecycle.contracts import canonical_digest

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"
FIXTURES = ROOT / "tests/benchmarks/fixtures"


class ReferenceTaskComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = evaluate_reference_task(
            suite_path=SUITE,
            artifact_path=FIXTURES / "accepted-pass.json",
        )

    def test_attested_quality_preserving_savings_are_eligible(self) -> None:
        baseline = _complete_measurements(self.baseline)
        candidate = _replace_tokens(baseline, confidence="ATTESTED", total=150)

        comparison = compare_reference_task_evaluations(baseline, candidate)

        self.assertEqual(comparison["status"], "PASS")
        self.assertEqual(comparison["resources"]["exactDeltas"]["tokens"], -50)
        self.assertTrue(comparison["resources"]["exactSavingsClaimed"])
        self.assertTrue(comparison["resources"]["measurementComplete"])
        self.assertTrue(comparison["decision"]["automaticStrategyAdoptionEligible"])
        self.assertEqual(validate_reference_task_comparison(comparison)["status"], "PASS")

    def test_estimated_savings_remain_advisory(self) -> None:
        baseline = _replace_tokens(self.baseline, confidence="ESTIMATED", total=200)
        candidate = _replace_tokens(self.baseline, confidence="ESTIMATED", total=100)

        comparison = compare_reference_task_evaluations(baseline, candidate)

        self.assertEqual(comparison["status"], "PASS")
        self.assertIsNone(comparison["resources"]["exactDeltas"])
        self.assertEqual(comparison["resources"]["advisoryEstimatedTokenDelta"], -100)
        self.assertFalse(comparison["decision"]["automaticStrategyAdoptionEligible"])

    def test_new_false_acceptance_blocks_before_savings(self) -> None:
        candidate = _replace_tokens(self.baseline, confidence="ATTESTED", total=1)
        candidate["summary"]["falseAcceptanceCount"] = 1
        candidate["evaluationDigest"] = canonical_digest(
            {key: value for key, value in candidate.items() if key != "evaluationDigest"}
        )

        comparison = compare_reference_task_evaluations(self.baseline, candidate)

        self.assertEqual(comparison["status"], "FAIL")
        self.assertIn("comparison-new-false-acceptance", {item["code"] for item in comparison["blockers"]})
        self.assertFalse(comparison["decision"]["exactSavingsSupported"])
        self.assertFalse(comparison["decision"]["automaticStrategyAdoptionEligible"])

    def test_lineage_mismatch_blocks_comparison(self) -> None:
        candidate = _replace_tokens(self.baseline, confidence="ATTESTED", total=150)
        candidate["task"]["oracleDigest"] = "0" * 64
        candidate["evaluationDigest"] = canonical_digest(
            {key: value for key, value in candidate.items() if key != "evaluationDigest"}
        )

        comparison = compare_reference_task_evaluations(self.baseline, candidate)

        self.assertEqual(comparison["status"], "FAIL")
        self.assertIn("comparison-task-lineage-mismatch", {item["code"] for item in comparison["blockers"]})

    def test_reporting_surfaces_invocation_retry_and_remediation_counts(self) -> None:
        submission = json.loads((FIXTURES / "accepted-pass.json").read_text(encoding="utf-8"))
        submission["evidence"]["outcomeIndex"]["records"][0]["remediationLoops"] = 2

        measurements, blockers = build_measurements(submission, {"status": "PASS", "checks": []})

        self.assertEqual(blockers, [])
        self.assertEqual(measurements["invocations"]["count"], 1)
        self.assertEqual(measurements["retries"]["count"], 1)
        self.assertEqual(measurements["remediations"]["count"], 2)

    def test_savings_with_missing_measurements_remain_advisory(self) -> None:
        candidate = _replace_tokens(self.baseline, confidence="ATTESTED", total=150)

        comparison = compare_reference_task_evaluations(self.baseline, candidate)

        self.assertTrue(comparison["resources"]["exactSavingsClaimed"])
        self.assertFalse(comparison["resources"]["measurementComplete"])
        self.assertFalse(comparison["decision"]["automaticStrategyAdoptionEligible"])

    def test_resource_regression_blocks_automatic_adoption(self) -> None:
        baseline = _complete_measurements(self.baseline)
        candidate = _replace_tokens(baseline, confidence="ATTESTED", total=150)
        candidate["measurements"]["retries"]["count"] += 1
        candidate["evaluationDigest"] = canonical_digest(
            {key: value for key, value in candidate.items() if key != "evaluationDigest"}
        )

        comparison = compare_reference_task_evaluations(baseline, candidate)

        self.assertEqual(comparison["status"], "PASS")
        self.assertEqual(comparison["resources"]["observedRegressionFields"], ["retries"])
        self.assertFalse(comparison["resources"]["resourceRegressionFree"])
        self.assertFalse(comparison["decision"]["automaticStrategyAdoptionEligible"])


def _replace_tokens(evaluation: dict, *, confidence: str, total: int) -> dict:
    payload = deepcopy(evaluation)
    payload["measurements"]["tokens"]["headline"] = {"confidence": confidence, "total": total}
    buckets = payload["measurements"]["tokens"]["byConfidence"]
    for key in ("ATTESTED", "ESTIMATED"):
        buckets[key] = {
            "entryCount": 1 if key == confidence else 0,
            "input": total if key == confidence else 0,
            "output": 0,
            "total": total if key == confidence else 0,
        }
    payload["evaluationDigest"] = canonical_digest(
        {key: value for key, value in payload.items() if key != "evaluationDigest"}
    )
    return payload


def _complete_measurements(evaluation: dict) -> dict:
    payload = deepcopy(evaluation)
    payload["measurements"]["remediations"] = {
        "count": 0,
        "source": "agent-task-outcome-index.v1",
    }
    payload["measurements"]["measurementGaps"] = []
    payload["evaluationDigest"] = canonical_digest(
        {key: value for key, value in payload.items() if key != "evaluationDigest"}
    )
    return payload


if __name__ == "__main__":
    unittest.main()
