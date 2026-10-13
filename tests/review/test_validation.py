"""Review envelope checks; these do not attest reviewer identity or host proof."""
from __future__ import annotations

import copy
import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.review.validation import validate_independent_review


class IndependentReviewValidationTests(unittest.TestCase):
    @staticmethod
    def review() -> dict:
        return {"reviewer": {"id": "independent-reviewer", "independent": True},
                "verdict": "ACCEPTED", "findings": []}

    def test_positive_verdicts_allow_closed_blockers_and_open_low_findings(self):
        for verdict in ("READY_TO_FREEZE", "ACCEPTED"):
            value = self.review()
            value["verdict"] = verdict
            value["findings"] = [{"id": "closed", "severity": "HIGH", "status": "closed"},
                                 {"id": "low", "severity": "LOW", "status": "open"}]
            with self.subTest(verdict=verdict):
                self.assertEqual(validate_independent_review(value), {
                    "schemaVersion": "agent-review-validation.v1", "verdict": verdict, "openBlocking": []})

    def test_positive_verdict_rejects_open_blocking_severities(self):
        for severity in ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM"):
            value = self.review()
            value["findings"] = [{"id": "block", "severity": severity, "status": " OPEN "}]
            with self.subTest(severity=severity), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "review-open-findings")

    def test_nonpositive_review_preserves_blocking_finding_ids(self):
        value = self.review()
        value["verdict"] = "CHANGES_REQUIRED"
        value["findings"] = [{"id": "needs-work", "severity": "MEDIUM", "status": "open"}]
        self.assertEqual(validate_independent_review(value)["openBlocking"], ["needs-work"])

    def test_exact_independence_flag_is_required(self):
        for reviewer in (None, {}, {"independent": False}, {"independent": 1}):
            value = self.review()
            value["reviewer"] = reviewer
            with self.subTest(reviewer=reviewer), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "review-not-independent")

    def test_unsupported_verdict_and_nonarray_findings_reject(self):
        for patch in ({"verdict": "RELEASE_READY"}, {"findings": None}, {"findings": {}}):
            value = self.review()
            value.update(patch)
            with self.subTest(patch=patch), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "invalid-review")

    def test_hidden_authority_control_rejects_before_verdict_filtering(self):
        for patch in ({"verdict": "ACCEP\u200bTED"},
                      {"findings": [{"id": "hidden", "severity": "HI\u200bGH", "status": "open"}]}):
            value = copy.deepcopy(self.review())
            value.update(patch)
            with self.subTest(patch=patch), self.assertRaises(LifecycleError) as caught:
                validate_independent_review(value)
            self.assertEqual(caught.exception.code, "authority-text-control")


if __name__ == "__main__":
    unittest.main()
