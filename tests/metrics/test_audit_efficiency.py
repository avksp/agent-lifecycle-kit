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

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests/metrics/fixtures/release-2-6-accounting-baseline.json"


class AuditEfficiencyTests(unittest.TestCase):
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
    return build_audit_efficiency_input(
        release_id=release_id,
        source_revision=f"source-{release_id}",
        source_lineage_digest=canonical_digest({"release": release_id}),
        quality_floor="release-standard",
        views={
            "alkProcess": {"tokens": _metric(100), "elapsedWallMs": _metric(1000), "computeMs": _unavailable()},
            "implementation": {"tokens": _metric(200), "elapsedWallMs": _metric(2000), "computeMs": _unavailable()},
            "audit": {"tokens": _metric(audit_tokens), "elapsedWallMs": _metric(audit_wall), "computeMs": _metric(12000)},
            "postAuditRemediation": {"tokens": _metric(50), "elapsedWallMs": _metric(4000), "computeMs": _unavailable()},
        },
        outcomes={
            "confirmedFindings": _metric(confirmed),
            "rejectedFindings": _metric(rejected),
            "noVerdictSessions": _metric(no_verdict),
            "auditSessions": _metric(8),
            "remediationEvents": _metric(remediation),
        },
        totals={"elapsedWallMs": _metric(20000)},
    )


def _metric(value: int) -> dict:
    return {"status": "MEASURED", "value": value}


def _unavailable() -> dict:
    return {"status": "UNAVAILABLE", "value": None}


if __name__ == "__main__":
    unittest.main()
