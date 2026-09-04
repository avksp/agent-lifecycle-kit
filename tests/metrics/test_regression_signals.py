from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from agent_lifecycle.metrics.regression_signals import (  # noqa: E402
    build_workflow_comparison_context,
    compare_workflow_economics,
    summarize_regression_signals,
    validate_workflow_economics_comparison_view,
    workflow_comparison_context_from_fixture,
)
from agent_lifecycle.metrics.release_accounting import validate_release_accounting  # noqa: E402
from agent_lifecycle.metrics.workflow_economics import WORKFLOW_METRIC_KEYS  # noqa: E402

FIXTURES = ROOT / "tests/metrics/fixtures"


class RegressionSignalTests(unittest.TestCase):
    def test_empty_regression_signals_pass(self) -> None:
        summary = summarize_regression_signals([])

        self.assertEqual(summary["schemaVersion"], "agent-lifecycle-regression-signals.v1")
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["signalCount"], 0)

    def test_blocking_signal_blocks_tuning(self) -> None:
        summary = summarize_regression_signals([{"type": "failedFinalAudit", "count": 1, "severity": "HIGH"}])

        self.assertEqual(summary["status"], "BLOCK")
        self.assertEqual(summary["blockingSignals"][0]["type"], "failedFinalAudit")

    def test_invalid_signal_fails_closed(self) -> None:
        summary = summarize_regression_signals([{"type": "rollback", "count": -1}])

        self.assertEqual(summary["status"], "FAIL")
        self.assertIn("regression-signal-count", {item["code"] for item in summary["blockers"]})

    def test_complete_equal_assurance_comparison_can_prove_improvement(self) -> None:
        before = _context("before", 100)
        after = _context("after", 80)

        comparison = compare_workflow_economics(before, after)

        self.assertEqual(comparison["status"], "IMPROVED")
        self.assertEqual(comparison["assurance"]["status"], "EQUAL_OR_STRONGER")
        self.assertTrue(all(item["direction"] == "IMPROVED" for item in comparison["metrics"].values()))
        self.assertEqual(validate_workflow_economics_comparison_view(comparison)["status"], "PASS")
        self.assertFalse(comparison["authorityClaimed"])

    def test_missing_tokens_cannot_be_improved(self) -> None:
        before = _context("before", 100)
        after = _context("after", 80)
        for context in (before, after):
            context["metrics"]["modelInputTokens"] = {"status": "UNAVAILABLE", "value": None}
            _refresh_context(context)

        comparison = compare_workflow_economics(before, after)

        self.assertEqual(comparison["status"], "MIXED")
        self.assertEqual(comparison["metrics"]["modelInputTokens"]["direction"], "UNKNOWN")

        comparison["status"] = "IMPROVED"
        comparison["comparisonDigest"] = canonical_digest(
            {key: value for key, value in comparison.items() if key != "comparisonDigest"}
        )
        self.assertEqual(validate_workflow_economics_comparison_view(comparison)["status"], "FAIL")

    def test_weaker_gate_or_acceptance_outcome_is_regression(self) -> None:
        before = _context("before", 100)
        after = _context("after", 50)
        after["gateOutcomes"]["requiredGateIds"].remove("security")
        after["gateOutcomes"]["passedGateIds"].remove("security")
        after["gateOutcomes"]["acceptanceStatus"] = "FAIL"
        _refresh_context(after)

        comparison = compare_workflow_economics(before, after)

        self.assertEqual(comparison["status"], "REGRESSED")
        self.assertEqual(comparison["assurance"]["status"], "WEAKER")
        self.assertIn("required-gates-removed", comparison["assurance"]["reasons"])
        self.assertIn("acceptance-outcome-degraded", comparison["assurance"]["reasons"])

    def test_stable_identity_mismatch_has_no_comparable_baseline(self) -> None:
        before = _context("before", 100)
        after = _context("after", 80, workload="different")

        comparison = compare_workflow_economics(before, after)

        self.assertEqual(comparison["status"], "NO_COMPARABLE_BASELINE")
        self.assertIn(
            "workflow-comparison-stable-identity-mismatch",
            {item["code"] for item in comparison["blockers"]},
        )

    def test_different_implementation_without_pair_is_not_comparable(self) -> None:
        before = _context("before", 100)
        after = _context("after", 80)
        after["implementation"]["coreVersion"] = "2.15.0"
        _refresh_context(after)

        comparison = compare_workflow_economics(before, after)

        self.assertEqual(comparison["status"], "NO_COMPARABLE_BASELINE")
        self.assertEqual(comparison["implementationStatus"], "MISMATCH")

    def test_predeclared_2_8_2_10_pair_returns_metric_deltas(self) -> None:
        before_fixture = _load("release-2-8-continuation-baseline.json")
        after_fixture = _load("release-2-10-continuation-baseline.json")
        pair = _load("release-2-10-continuation-comparison-pair.json")

        comparison = compare_workflow_economics(
            workflow_comparison_context_from_fixture(before_fixture),
            workflow_comparison_context_from_fixture(after_fixture),
            comparison_pair=pair,
        )

        self.assertEqual(comparison["implementationStatus"], "PREDECLARED_PAIR")
        self.assertEqual(comparison["status"], "MIXED")
        self.assertEqual(comparison["metrics"]["toolCalls"]["direction"], "IMPROVED")
        self.assertEqual(comparison["metrics"]["elapsedWallMs"]["direction"], "IMPROVED")

    def test_retrospective_or_mutated_pair_is_not_comparable(self) -> None:
        before_fixture = _load("release-2-8-continuation-baseline.json")
        after_fixture = _load("release-2-10-continuation-baseline.json")
        original = _load("release-2-10-continuation-comparison-pair.json")
        mutations = []
        retrospective = deepcopy(original)
        retrospective["declaredAt"] = "2026-09-01T00:00:00Z"
        _refresh_pair(retrospective)
        mutations.append(retrospective)
        same_role = deepcopy(original)
        same_role["after"]["role"] = "before"
        _refresh_pair(same_role)
        mutations.append(same_role)
        changed_source = deepcopy(original)
        changed_source["after"]["sourceRevision"] = "f" * 40
        _refresh_pair(changed_source)
        mutations.append(changed_source)

        for pair in mutations:
            with self.subTest(pair=pair["comparisonPairId"]):
                comparison = compare_workflow_economics(
                    workflow_comparison_context_from_fixture(before_fixture),
                    workflow_comparison_context_from_fixture(after_fixture),
                    comparison_pair=pair,
                )
                self.assertEqual(comparison["status"], "NO_COMPARABLE_BASELINE")

    def test_historical_fixture_digest_mutation_fails_closed(self) -> None:
        fixture = _load("release-2-12-delta-audit-baseline.json")
        fixture["routes"]["fullRepeat"]["tokens"]["inputTokens"] += 1

        context = workflow_comparison_context_from_fixture(fixture)
        comparison = compare_workflow_economics(context, _context("after", 80))

        self.assertEqual(comparison["status"], "NO_COMPARABLE_BASELINE")
        self.assertIn(
            "workflow-comparison-fixture-digest-invalid",
            {item["code"] for item in comparison["blockers"]},
        )

    def test_complete_predecessor_inventory_and_2_14_fixture_are_consumable(self) -> None:
        predecessor_names = [
            "release-2-8-continuation-baseline.json",
            "release-2-9-accounting.json",
            "release-2-10-accounting.json",
            "release-2-10-continuation-baseline.json",
            "release-2-10-continuation-comparison-pair.json",
            "release-2-11-accounting.json",
            "release-2-11-phase-packet-before.json",
            "release-2-11-phase-packet-after.json",
            "release-2-11-phase-packet-comparison-pair.json",
            "release-2-12-delta-audit-baseline.json",
            "release-2-13-strategy-baseline.json",
        ]
        pair_names = {
            "release-2-10-continuation-comparison-pair.json",
            "release-2-11-phase-packet-comparison-pair.json",
        }

        self.assertEqual(len(predecessor_names), 11)
        for name in predecessor_names:
            with self.subTest(name=name):
                fixture = _load(name)
                digest_field = "comparisonPairId" if name in pair_names else _digest_field(fixture)
                self.assertEqual(
                    fixture[digest_field],
                    canonical_digest({key: value for key, value in fixture.items() if key != digest_field}),
                )
                if name not in pair_names:
                    context = workflow_comparison_context_from_fixture(fixture)
                    codes = {item["code"] for item in context.get("blockers", [])}
                    self.assertNotIn("workflow-comparison-fixture-digest-invalid", codes)

        fixture_214 = _load("release-2-14-accounting.json")
        context_214 = workflow_comparison_context_from_fixture(fixture_214)

        self.assertEqual(validate_release_accounting(fixture_214)["status"], "PASS")
        self.assertEqual(context_214.get("blockers", []), [])
        self.assertEqual(context_214["gateOutcomes"]["acceptanceStatus"], "PASS")
        self.assertEqual(context_214["metrics"]["modelInputTokens"]["status"], "MEASURED")

    def test_unavailable_historical_value_cannot_be_backfilled(self) -> None:
        fixture = _load("release-2-13-strategy-baseline.json")
        fixture["modelTelemetry"]["inputTokens"] = 0
        fixture["fixtureDigest"] = canonical_digest(
            {key: value for key, value in fixture.items() if key != "fixtureDigest"}
        )

        context = workflow_comparison_context_from_fixture(fixture)

        self.assertIn(
            "workflow-comparison-unavailable-backfill",
            {item["code"] for item in context["blockers"]},
        )


def _context(role: str, value: int, *, workload: str = "shared") -> dict:
    workload_digest = canonical_digest({"workload": workload})
    metrics = {
        key: {"status": "MEASURED", "value": value}
        for key in WORKFLOW_METRIC_KEYS
        if key not in {"requiredGateCount", "passedGateCount", "failedGateCount"}
    }
    gates = {
        "requiredGateIds": ["architecture", "quality", "security"],
        "passedGateIds": ["architecture", "quality", "security"],
        "failedGateIds": [],
        "qualityFloorDigest": canonical_digest({"floor": "S2"}),
        "acceptanceStatus": "PASS",
    }
    return build_workflow_comparison_context(
        source_digest=canonical_digest({"role": role, "value": value, "workload": workload}),
        workload_identity_digest=workload_digest,
        implementation={"sourceRevision": "same", "coreVersion": "2.14.0", "publicationVersions": {}},
        role=role,
        metrics=metrics,
        gate_outcomes=gates,
        measured_at=f"2026-09-04T00:00:0{1 if role == 'before' else 2}Z",
    )


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _refresh_context(context: dict) -> None:
    context["contextDigest"] = canonical_digest(
        {key: value for key, value in context.items() if key != "contextDigest"}
    )


def _refresh_pair(pair: dict) -> None:
    pair["comparisonPairId"] = canonical_digest(
        {key: value for key, value in pair.items() if key != "comparisonPairId"}
    )


def _digest_field(fixture: dict) -> str:
    return next(
        field for field in ("measurementDigest", "accountingDigest", "fixtureDigest", "inputDigest") if field in fixture
    )


if __name__ == "__main__":
    unittest.main()
