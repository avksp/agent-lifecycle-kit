from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.metrics.audit_efficiency import (
    build_audit_efficiency_input,
    build_audit_efficiency_report,
    validate_audit_efficiency_input,
    validate_audit_efficiency_report,
)
from agent_lifecycle.metrics.regression_signals import build_workflow_comparison_context
from agent_lifecycle.metrics.workflow_economics import WORKFLOW_METRIC_KEYS

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests/metrics/fixtures/release-2-6-accounting-baseline.json"
DELTA_BASELINE = ROOT / "tests/metrics/fixtures/release-2-12-delta-audit-baseline.json"


class AuditEfficiencyTests(unittest.TestCase):
    def test_release_2_12_delta_baseline_preserves_raw_measurement_and_fallback(self) -> None:
        baseline = json.loads(DELTA_BASELINE.read_text(encoding="utf-8"))

        self.assertEqual(baseline["releaseId"], "2.12.0")
        self.assertEqual(baseline["fixtureDigest"], _fixture_digest(baseline))
        identity = baseline["workloadIdentity"]
        self.assertEqual(
            identity["workloadIdentityDigest"],
            canonical_digest({key: value for key, value in identity.items() if key != "workloadIdentityDigest"}),
        )
        full = baseline["routes"]["fullRepeat"]
        raw_tokens = full["tokens"]
        self.assertEqual(
            raw_tokens["totalReportedTokens"],
            sum(
                raw_tokens[key]
                for key in (
                    "inputTokens",
                    "cacheCreationInputTokens",
                    "cacheReadInputTokens",
                    "outputTokens",
                )
            ),
        )
        self.assertEqual(full["reviewerInput"]["bytes"], 2790)
        self.assertEqual(full["time"]["elapsedMs"], 727_368)
        self.assertEqual(full["toolCalls"], {"status": "UNAVAILABLE", "value": None})

        delta = baseline["routes"]["deltaReview"]
        self.assertEqual(delta["status"], "UNAVAILABLE")
        self.assertEqual(delta["fallback"]["selectedRoute"], "FULL_AUDIT")
        self.assertTrue(delta["fallback"]["observed"])
        self.assertEqual(baseline["comparison"]["status"], "UNAVAILABLE")
        self.assertIsNone(baseline["comparison"]["tokenReductionPercent"])
        self.assertIsNone(baseline["comparison"]["wallReductionPercent"])
        self.assertTrue(baseline["qualityFloorPreserved"])
        self.assertTrue(baseline["independentAcceptanceRequired"])
        self.assertTrue(baseline["freshFinalAuditRequired"])
        self.assertFalse(baseline["commandsExecutedByDeltaBuilder"])

    def test_release_2_12_delta_baseline_cannot_replace_unavailable_with_zero(self) -> None:
        baseline = json.loads(DELTA_BASELINE.read_text(encoding="utf-8"))
        original_digest = baseline["fixtureDigest"]

        baseline["routes"]["deltaReview"]["tokens"] = {"status": "UNAVAILABLE", "value": 0}

        self.assertNotEqual(original_digest, _fixture_digest(baseline))

    def test_release_2_6_fixture_preserves_measured_and_unavailable_values(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

        report = build_audit_efficiency_report(baseline)

        self.assertEqual(validate_audit_efficiency_input(baseline)["status"], "PASS")
        self.assertEqual(report["status"], "NO_COMPARISON")
        self.assertEqual(report["metrics"]["auditTokens"], {"status": "MEASURED", "value": 29_195_208})
        self.assertEqual(report["metrics"]["auditWallMs"], {"status": "MEASURED", "value": 9_278_567})
        self.assertEqual(report["metrics"]["auditComputeMs"], {"status": "MEASURED", "value": 12_228_901})
        self.assertEqual(baseline["views"]["implementation"]["tokens"], {"status": "UNAVAILABLE", "value": None})
        self.assertEqual(baseline["views"]["postAuditRemediation"]["tokens"], {"status": "UNAVAILABLE", "value": None})
        self.assertEqual(
            report["comparison"]["tokenReductionPercent"],
            {"status": "UNAVAILABLE", "value": None, "reason": "comparison-sample-required"},
        )
        self.assertEqual(validate_audit_efficiency_report(report)["status"], "PASS")

    def test_unavailable_metric_cannot_be_substituted_with_zero(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        baseline["views"]["implementation"]["tokens"]["value"] = 0
        baseline["inputDigest"] = canonical_digest(
            {key: value for key, value in baseline.items() if key != "inputDigest"}
        )

        validation = validate_audit_efficiency_input(baseline)
        report = build_audit_efficiency_report(baseline)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "audit-efficiency-unavailable-has-value",
            {item["code"] for item in validation["blockers"]},
        )
        self.assertEqual(report["status"], "FAIL")

    def test_quality_outcomes_produce_bounded_efficiency_metrics(self) -> None:
        measurement = _measurement()

        report = build_audit_efficiency_report(measurement)

        metrics = report["metrics"]
        self.assertEqual(metrics["tokensPerConfirmedFinding"]["value"], 250.0)
        self.assertEqual(metrics["wallMsPerConfirmedFinding"]["value"], 2500.0)
        self.assertEqual(metrics["noAcceptanceEffectShare"]["value"], 0.25)
        self.assertEqual(metrics["rejectedFindingShare"]["value"], 0.333333)
        self.assertEqual(metrics["postAuditRemediationShare"]["value"], 0.2)
        self.assertTrue(report["qualityFloorPreserved"])
        self.assertTrue(report["advisoryOnly"])
        self.assertFalse(report["autoApply"])

    def test_two_comparable_releases_can_report_reduction_without_auto_apply(self) -> None:
        current = _measurement(release_id="2.7.0", audit_tokens=800, audit_wall=8000)
        baseline = _measurement(release_id="2.6.0", audit_tokens=1000, audit_wall=10000)

        report = build_audit_efficiency_report(current, comparison_measurements=[baseline])

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["comparison"]["tokenReductionPercent"]["value"], 20.0)
        self.assertEqual(report["comparison"]["wallReductionPercent"]["value"], 20.0)
        self.assertFalse(report["autoApply"])

    def test_current_input_reused_as_comparison_fails_before_reduction(self) -> None:
        current = _measurement()

        report = build_audit_efficiency_report(current, comparison_measurements=[deepcopy(current)])

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["comparison"]["sampleCount"], 1)
        self.assertEqual(report["comparison"]["tokenReductionPercent"]["status"], "UNAVAILABLE")
        self.assertEqual(
            _duplicate_axes(report),
            {"contentDigest", "releaseId", "sourceLineageDigest", "sourceRevision"},
        )

    def test_repeated_comparison_does_not_inflate_sample_count(self) -> None:
        current = _measurement(release_id="2.7.0", audit_tokens=800, audit_wall=8000)
        baseline = _measurement(release_id="2.6.0", audit_tokens=1000, audit_wall=10000)

        report = build_audit_efficiency_report(
            current,
            comparison_measurements=[baseline, deepcopy(baseline)],
        )

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["comparison"]["sampleCount"], 2)
        self.assertEqual(
            _duplicate_axes(report, index=1),
            {"contentDigest", "releaseId", "sourceLineageDigest", "sourceRevision"},
        )

    def test_repeated_release_id_fails_with_distinct_content_and_lineage(self) -> None:
        current = _measurement(release_id="2.7.0", audit_tokens=800, audit_wall=8000)
        baseline = _measurement(release_id="2.6.0", audit_tokens=1000, audit_wall=10000)
        baseline["releaseId"] = current["releaseId"]
        _refresh_input_digest(baseline)

        report = build_audit_efficiency_report(current, comparison_measurements=[baseline])

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(_duplicate_axes(report), {"releaseId"})

    def test_release_label_only_copy_fails_on_content_and_lineage(self) -> None:
        current = _measurement(release_id="2.7.0")
        relabelled = deepcopy(current)
        relabelled["releaseId"] = "2.6.0-relabelled"
        _refresh_input_digest(relabelled)

        report = build_audit_efficiency_report(current, comparison_measurements=[relabelled])

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(
            _duplicate_axes(report),
            {"contentDigest", "sourceLineageDigest", "sourceRevision"},
        )

    def test_retained_source_lineage_fails_even_when_metrics_change(self) -> None:
        current = _measurement(release_id="2.7.0", audit_tokens=800, audit_wall=8000)
        baseline = _measurement(release_id="2.6.0", audit_tokens=1000, audit_wall=10000)
        baseline["sourceRevision"] = current["sourceRevision"]
        baseline["sourceLineageDigest"] = current["sourceLineageDigest"]
        _refresh_input_digest(baseline)

        report = build_audit_efficiency_report(current, comparison_measurements=[baseline])

        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(_duplicate_axes(report), {"sourceLineageDigest", "sourceRevision"})

    def test_missing_controller_or_implementation_telemetry_blocks_comparison(self) -> None:
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        current = deepcopy(baseline)
        current["releaseId"] = "2.7.0"
        current["sourceRevision"] = "source-2.7.0"
        current["sourceLineageDigest"] = canonical_digest({"release": "2.7.0"})
        current["inputDigest"] = canonical_digest(
            {key: value for key, value in current.items() if key != "inputDigest"}
        )

        report = build_audit_efficiency_report(current, comparison_measurements=[baseline])

        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "audit-efficiency-comparison-telemetry-unavailable",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(
            report["comparison"]["tokenReductionPercent"]["status"],
            "UNAVAILABLE",
        )

    def test_quality_floor_mismatch_blocks_comparison(self) -> None:
        current = _measurement(release_id="2.7.0")
        baseline = deepcopy(_measurement(release_id="2.6.0"))
        baseline["qualityFloor"] = "lower"
        baseline["inputDigest"] = canonical_digest(
            {key: value for key, value in baseline.items() if key != "inputDigest"}
        )

        report = build_audit_efficiency_report(current, comparison_measurements=[baseline])

        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "audit-efficiency-comparison-quality-floor-mismatch",
            {item["code"] for item in report["blockers"]},
        )

    def test_comparison_without_stable_context_cannot_claim_reduction(self) -> None:
        current = _measurement(release_id="2.7.0", audit_tokens=800, audit_wall=8000)
        baseline = _measurement(release_id="2.6.0", audit_tokens=1000, audit_wall=10000)
        current.pop("comparisonContext")
        baseline.pop("comparisonContext")
        _refresh_input_digest(current)
        _refresh_input_digest(baseline)

        report = build_audit_efficiency_report(current, comparison_measurements=[baseline])

        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "audit-efficiency-comparison-context-unavailable",
            {item["code"] for item in report["blockers"]},
        )
        self.assertEqual(report["comparison"]["tokenReductionPercent"]["status"], "UNAVAILABLE")

    def test_apparent_savings_with_weaker_gate_are_not_reported_as_reduction(self) -> None:
        current = _measurement(release_id="2.7.0", audit_tokens=500, audit_wall=5000)
        baseline = _measurement(release_id="2.6.0", audit_tokens=1000, audit_wall=10000)
        context = current["comparisonContext"]
        context["gateOutcomes"]["requiredGateIds"].remove("security")
        context["gateOutcomes"]["passedGateIds"].remove("security")
        context["contextDigest"] = canonical_digest(
            {key: value for key, value in context.items() if key != "contextDigest"}
        )
        _refresh_input_digest(current)

        report = build_audit_efficiency_report(current, comparison_measurements=[baseline])

        self.assertEqual(report["comparison"]["workflowStatus"], "REGRESSED")
        self.assertEqual(report["comparison"]["tokenReductionPercent"]["status"], "UNAVAILABLE")
        self.assertFalse(report["comparison"]["qualityFloorPreserved"])

    def test_mixed_is_not_valid_as_source_metric_status(self) -> None:
        measurement = _measurement()
        measurement["views"]["audit"]["tokens"]["status"] = "MIXED"
        _refresh_input_digest(measurement)

        validation = validate_audit_efficiency_input(measurement)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn(
            "audit-efficiency-view-metric-invalid",
            {item["code"] for item in validation["blockers"]},
        )

    def test_agentic_tendercrm_and_board_shapes_preserve_outcome_distinctions(self) -> None:
        shapes = {
            "agentic": (3, 1, 2, 1),
            "tendercrm": (5, 2, 0, 2),
            "board": (8, 3, 1, 1),
        }

        for shape, (confirmed, rejected, no_verdict, remediation) in shapes.items():
            with self.subTest(shape=shape):
                report = build_audit_efficiency_report(
                    _measurement(
                        release_id=f"synthetic-{shape}",
                        confirmed=confirmed,
                        rejected=rejected,
                        no_verdict=no_verdict,
                        remediation=remediation,
                    )
                )
                self.assertEqual(report["metrics"]["confirmedFindings"]["value"], confirmed)
                self.assertEqual(report["metrics"]["rejectedFindings"]["value"], rejected)
                self.assertEqual(report["metrics"]["noVerdictSessions"]["value"], no_verdict)
                self.assertEqual(report["metrics"]["remediationEvents"]["value"], remediation)


def _measurement(
    *,
    release_id: str = "2.7.0",
    audit_tokens: int = 1000,
    audit_wall: int = 10000,
    confirmed: int = 4,
    rejected: int = 2,
    no_verdict: int = 2,
    remediation: int = 1,
) -> dict:
    role = "before" if release_id.startswith("2.6") else "after"
    comparison_metrics = {
        key: {"status": "MEASURED", "value": audit_tokens if "Token" in key else audit_wall}
        for key in WORKFLOW_METRIC_KEYS
        if key not in {"requiredGateCount", "passedGateCount", "failedGateCount"}
    }
    comparison_context = build_workflow_comparison_context(
        source_digest=canonical_digest({"release": release_id, "kind": "audit-efficiency"}),
        workload_identity_digest=canonical_digest({"workload": "audit-efficiency-synthetic"}),
        implementation={"sourceRevision": "shared", "coreVersion": "2.14.0", "publicationVersions": {}},
        role=role,
        metrics=comparison_metrics,
        gate_outcomes={
            "requiredGateIds": ["architecture", "quality", "security"],
            "passedGateIds": ["architecture", "quality", "security"],
            "failedGateIds": [],
            "qualityFloorDigest": canonical_digest({"floor": "release-standard"}),
            "acceptanceStatus": "PASS",
        },
        measured_at=f"2026-09-04T00:00:0{1 if role == 'before' else 2}Z",
    )
    return build_audit_efficiency_input(
        release_id=release_id,
        source_revision=f"source-{release_id}",
        source_lineage_digest=canonical_digest({"release": release_id}),
        quality_floor="release-standard",
        views={
            "alkProcess": {"tokens": _metric(100), "elapsedWallMs": _metric(1000), "computeMs": _unavailable()},
            "implementation": {"tokens": _metric(200), "elapsedWallMs": _metric(2000), "computeMs": _unavailable()},
            "audit": {
                "tokens": _metric(audit_tokens),
                "elapsedWallMs": _metric(audit_wall),
                "computeMs": _metric(12000),
            },
            "postAuditRemediation": {
                "tokens": _metric(50),
                "elapsedWallMs": _metric(4000),
                "computeMs": _unavailable(),
            },
        },
        outcomes={
            "confirmedFindings": _metric(confirmed),
            "rejectedFindings": _metric(rejected),
            "noVerdictSessions": _metric(no_verdict),
            "auditSessions": _metric(8),
            "remediationEvents": _metric(remediation),
        },
        totals={"elapsedWallMs": _metric(20000)},
        comparison_context=comparison_context,
    )


def _metric(value: int) -> dict:
    return {"status": "MEASURED", "value": value}


def _unavailable() -> dict:
    return {"status": "UNAVAILABLE", "value": None}


def _refresh_input_digest(value: dict) -> None:
    value["inputDigest"] = canonical_digest({key: item for key, item in value.items() if key != "inputDigest"})


def _fixture_digest(value: dict) -> str:
    return canonical_digest({key: item for key, item in value.items() if key != "fixtureDigest"})


def _duplicate_axes(report: dict, *, index: int = 0) -> set[str]:
    return {
        item["axis"]
        for item in report["blockers"]
        if item.get("code") == "audit-efficiency-comparison-duplicate-identity" and item.get("index") == index
    }


if __name__ == "__main__":
    unittest.main()
