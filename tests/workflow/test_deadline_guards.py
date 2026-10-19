"""Consumer completeness, original deadlines and unknowns are separate from evidence reuse."""
import copy
import unittest

from agent_lifecycle.workflow.closing_window import assess_retained_evidence
from agent_lifecycle.workflow.deadline_guards import evaluate_deadline_guards
from tests.contracts.test_deadlines import _duration, _freshness, _permission
from tests.workflow.test_closing_window import NOW, evidence

OBSERVED = "2026-09-23T01:30:00.000000Z"


def consumers():
    return [{"consumerId": "run", "rule": _duration(), "generatedAt": None},
            {"consumerId": "permission", "rule": _permission(), "generatedAt": None},
            {"consumerId": "receipt", "rule": _freshness(), "generatedAt": "2026-09-23T01:00:00.000000Z"}]


def assess(value, observed_at=OBSERVED):
    return evaluate_deadline_guards(value, expected_consumer_ids=["run", "permission", "receipt"], observed_at=observed_at)


class DeadlineGuardTests(unittest.TestCase):
    def test_complete_original_inputs_compare_without_permission_or_clock_claim(self):
        value = consumers()
        before = copy.deepcopy(value)
        result = assess(value)
        self.assertEqual(result["status"], "DATA_CANDIDATE")
        self.assertEqual(value, before)
        for key in ("nativeClockQualified", "nativePermissionGranted", "dispatchAuthorized",
                    "financialAdmission", "originalRulesReplaced"):
            self.assertIs(result[key], False)

    def test_original_attempt_wall_rule_remains_supported(self):
        value = consumers()
        value[0]["rule"]["kind"] = "ATTEMPT_WALL_BUDGET"
        self.assertEqual(assess(value)["status"], "DATA_CANDIDATE")
        self.assertEqual(assess(value, "2026-09-23T02:00:00.000000Z")["status"], "REFUSED")

    def test_one_expired_consumer_refuses_without_rewriting_original_interval(self):
        value = consumers()
        value[0]["rule"].update(limitSeconds=600, originalDeadlineAt="2026-09-23T01:10:00.000000Z")
        before = copy.deepcopy(value)
        self.assertEqual(assess(value)["status"], "REFUSED")
        self.assertEqual(value, before)

    def test_missing_duplicate_and_unknown_inputs_never_pass(self):
        self.assertEqual(assess(consumers()[:-1])["status"], "UNAVAILABLE")
        self.assertEqual(assess([*consumers(), consumers()[0]])["status"], "DENY")
        for key in ("rule", "generatedAt"):
            value = consumers()
            value[2][key] = None
            self.assertEqual(assess(value)["status"], "UNAVAILABLE")
        value = consumers()
        value[0]["rule"]["kind"] = "UNREGISTERED"
        self.assertEqual(assess(value)["status"], "DENY")

    def test_future_receipt_and_bad_clock_cannot_be_treated_as_fresh(self):
        value = consumers()
        value[2]["generatedAt"] = "2026-09-23T01:31:00.000000Z"
        self.assertEqual(assess(value)["status"], "REFUSED")
        self.assertEqual(assess(consumers(), "unavailable")["status"], "DENY")

    def test_expired_execution_does_not_invalidate_completed_technical_evidence(self):
        deadline = assess(consumers(), "2026-09-23T02:00:00.000000Z")
        self.assertEqual(deadline["status"], "REFUSED")
        retained = evidence()
        before = copy.deepcopy(retained)
        result = assess_retained_evidence(retained, now=NOW, observer_qualification="local-test-observer")
        self.assertEqual(result["status"], "REUSE")
        self.assertFalse(result["dispatch"])
        self.assertEqual(retained, before)
        self.assertEqual(result["retainedInput"]["originalAttempt"]["spent"], 120)
