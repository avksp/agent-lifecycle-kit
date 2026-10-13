"""Read/replay local retained data without pretending protected production succeeded."""
import json
import unittest

from agent_lifecycle.workflow.closing_window import assess_retained_evidence
from tests.workflow.test_closing_authority import protected_store, semantic_rows
from tests.workflow.test_closing_window import NOW, evidence


class ClosingWindowRecoveryTests(unittest.TestCase):
    def test_reloaded_negative_receipt_and_original_overrun_are_preserved(self):
        original = evidence()
        original["checks"][0]["receipt"]["outcome"] = "FAIL"
        decoded = json.loads(json.dumps(original))
        result = assess_retained_evidence(decoded, now=NOW, observer_qualification="local-test-observer")
        self.assertEqual(result["status"], "REUSE")
        self.assertFalse(result["evidenceGateSatisfied"])
        self.assertEqual(result["retainedInput"], original)
        self.assertEqual(result["retainedInput"]["originalAttempt"]["spent"], 120)
        self.assertEqual(result["retainedInput"]["originalAttempt"]["absoluteDeadlineStatus"], "FAIL")

    def test_repeated_denial_creates_no_operation_nonce_or_financial_state(self):
        with protected_store() as (_, journal, store):
            before = semantic_rows(journal)
            request = {"operationId": "same", "plannedUpperBound": 0}
            first = store.claim_with_workflow_authority(request)
            for _ in range(3):
                self.assertEqual(store.claim_with_workflow_authority(request), first)
                self.assertEqual(semantic_rows(journal), before)
            self.assertEqual(first["writeOutcome"], "NOT_STARTED")
