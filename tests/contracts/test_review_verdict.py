from __future__ import annotations

import unittest

from agent_lifecycle.contracts.review_verdict import compact_review_routing, validate_review_verdict


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
