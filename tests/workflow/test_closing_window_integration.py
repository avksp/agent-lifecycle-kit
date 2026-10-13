"""Successful preparation remains separate from current native closing permission."""
import copy
import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.closing_policy import require_native_closing_action
from agent_lifecycle.workflow.closing_window import assess_retained_evidence, evaluate_closing_resources
from tests.workflow.test_closing_policy import _context, _subject
from tests.workflow.test_closing_window import NOW, evidence, scope


class ClosingWindowIntegrationTests(unittest.TestCase):
    def test_fitting_resources_and_reusable_evidence_do_not_authorize_native_close(self):
        retained = evidence()
        original = copy.deepcopy(retained)
        self.assertEqual(evaluate_closing_resources([scope()], inventory_complete=True)["status"], "VALIDATED_DATA")
        result = assess_retained_evidence(retained, now=NOW, observer_qualification="local-test-observer")
        self.assertTrue(result["evidenceGateSatisfied"])
        state = {**_subject(), "closingWindow": _context()}
        before = copy.deepcopy(state)
        with self.assertRaises(LifecycleError) as error:
            require_native_closing_action(state, "finalize", "2026-09-23T01:30:00Z")
        self.assertEqual(error.exception.code, "closing-native-authority-required")
        self.assertEqual(state, before)
        self.assertEqual(retained, original)
        self.assertFalse(result["dispatch"])

    def test_invalidated_check_does_not_discard_independent_result_or_spend(self):
        retained = evidence()
        retained["checks"][0]["bindings"]["oracle"] = "changed"
        result = assess_retained_evidence(retained, now=NOW, observer_qualification="local-test-observer")
        statuses = {row["checkId"]: row["status"] for row in result["checks"]}
        self.assertEqual(statuses, {"Q": "RERUN_REQUIRED", "D": "RERUN_REQUIRED", "E": "RERUN_REQUIRED", "P": "REUSE"})
        self.assertEqual(result["retainedInput"]["originalAttempt"]["spent"], 120)
        self.assertFalse(result["dispatch"])
