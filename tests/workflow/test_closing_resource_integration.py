"""Preparation fits cannot replace the protected operator or consume journal resources."""
import unittest

from agent_lifecycle.workflow.closing_window import evaluate_closing_resources
from tests.workflow.test_closing_authority import protected_store, semantic_rows
from tests.workflow.test_closing_window import scope


class ClosingResourceIntegrationTests(unittest.TestCase):
    def test_preparation_fit_cannot_create_protected_reservation(self):
        prepared = evaluate_closing_resources([scope()], inventory_complete=True)
        self.assertEqual(prepared["status"], "VALIDATED_DATA")
        with protected_store() as (_, journal, store):
            before = semantic_rows(journal)
            result = store.reserve_closing_operation({"prepared": prepared})
            self.assertEqual(result["reason"], "UNSUPPORTED_OPERATOR_ROUTE")
            self.assertEqual(semantic_rows(journal), before)

    def test_unknown_cost_keeps_history_and_never_becomes_zero_fit(self):
        value = scope(operationUpperBound=None)
        prepared = evaluate_closing_resources([value], inventory_complete=True)
        self.assertEqual(prepared["status"], "UNAVAILABLE")
        self.assertIsNone(prepared["scopes"][0]["original"]["operationUpperBound"])
        self.assertEqual(prepared["scopes"][0]["original"]["spentAtActivation"], 90)
        with protected_store() as (_, journal, store):
            before = semantic_rows(journal)
            self.assertEqual(store.reserve_closing_operation({"prepared": prepared})["writeOutcome"], "NOT_STARTED")
            self.assertEqual(semantic_rows(journal), before)
