from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.contracts.review_verdict import (
    BLOCKING_REVIEW_SEVERITIES,
    compact_review_routing,
    validate_review_verdict,
)


class ReviewVerdictContractTests(unittest.TestCase):
    def test_contract_accepts_complete_accepted_verdict(self) -> None:
        verdict = _accepted_verdict()

        validation = validate_review_verdict(verdict)
        summary = compact_review_routing(verdict)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(summary["nextAction"], "accept")

    def test_contract_rejects_open_medium_findings_for_accepted_verdict(self) -> None:
        validation = validate_review_verdict(
            _accepted_verdict(),
            findings=[{"id": "M1", "status": "open", "severity": "MEDIUM"}],
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-verdict-open-findings", {item["code"] for item in validation["blockers"]})

    def test_canonical_blocking_policy_includes_all_medium_plus_severities(self) -> None:
        self.assertEqual(BLOCKING_REVIEW_SEVERITIES, {"BLOCKER", "CRITICAL", "HIGH", "MEDIUM"})
        for severity in BLOCKING_REVIEW_SEVERITIES:
            with self.subTest(severity=severity):
                validation = validate_review_verdict(
                    _accepted_verdict(),
                    findings=[{"id": severity, "status": "open", "severity": severity}],
                )
                self.assertEqual(validation["status"], "FAIL")

    def test_rework_verdict_can_report_open_blocking_finding(self) -> None:
        verdict = _accepted_verdict()
        verdict["overall"] = "REWORK"
        verdict["dimensions"]["implementationQuality"]["status"] = "FAIL"
        verdict["routing"]["nextAction"] = "fix-implementation"
        validation = validate_review_verdict(
            verdict,
            findings=[{"id": "H1", "status": "open", "severity": "HIGH"}],
        )
        self.assertEqual(validation["status"], "PASS")

    def test_medium_plus_gates_do_not_reintroduce_incomplete_literal_sets(self) -> None:
        root = Path(__file__).resolve().parents[2]
        paths = (
            "src/agent_lifecycle/audit/implementation.py",
            "src/agent_lifecycle/contracts/implementation_audit_validation.py",
            "src/agent_lifecycle/freeze/package_integrity.py",
            "src/agent_lifecycle/review/validation.py",
            "src/agent_lifecycle/specification/completion_gate.py",
            "src/agent_lifecycle/workflow/finalization.py",
            "src/agent_lifecycle/workflow/reviews.py",
        )
        incomplete = ('{"BLOCKER", "HIGH", "MEDIUM"}', '{"HIGH", "MEDIUM"}')
        for relative in paths:
            text = (root / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertFalse(any(literal in text for literal in incomplete))


def _accepted_verdict() -> dict[str, object]:
    return {
        "schemaVersion": "agent-review-verdict.v1",
        "overall": "ACCEPTED",
        "dimensions": {
            "requirementFit": {"status": "PASS", "reasonCode": "requirements-met", "summary": "Requirements are covered."},
            "implementationQuality": {"status": "PASS", "reasonCode": "quality-met", "summary": "Implementation is maintainable."},
            "evidenceQuality": {"status": "PASS", "reasonCode": "evidence-current", "summary": "Evidence is current."},
            "residualRisk": {"status": "PASS", "reasonCode": "risk-low", "summary": "No blocking residual risk remains."},
        },
        "routing": {"nextAction": "accept", "target": "task"},
    }
