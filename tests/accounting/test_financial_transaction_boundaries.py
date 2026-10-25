"""Real journal admission, rollback, limits and compatibility after owner extraction."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from agent_lifecycle.accounting import closing_resource_recovery as recovery
from agent_lifecycle.accounting.contracts import JournalHandle, JournalUnavailable, RevisionConflict
from agent_lifecycle.accounting.financial_transactions import _claim_in_transaction, _reserve_in_transaction
from agent_lifecycle.accounting.journal import Journal
from tests.accounting.test_journal import PROOF, operation
from tests.accounting.test_opening_balances import import_data


class FinancialTransactionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = Journal(Path(self.temp.name) / "journal.db", PROOF)
        self.addCleanup(self.journal.close)
        self.assertEqual(self.journal.import_opening(*import_data(protected={"task": 100})).status, "IMPORTED")

    def test_compatibility_and_existing_journal_handle(self):
        self.assertIs(recovery._reserve_in_transaction, _reserve_in_transaction)
        self.assertIs(recovery._claim_in_transaction, _claim_in_transaction)
        self.assertIsInstance(self.journal, JournalHandle)
        self.assertEqual(_reserve_in_transaction.__module__, "agent_lifecycle.accounting.financial_transactions")

    def test_unadmitted_sql_transaction_cannot_mutate(self):
        before = list(self.journal._db.iterdump())
        for begin in (False, True):
            with self.subTest(sql_transaction=begin):
                if begin:
                    self.journal._db.execute("BEGIN")
                try:
                    for action in (
                        lambda: self.journal._reserve_identity_keys(operation()),
                        lambda: _reserve_in_transaction(self.journal, operation()),
                        lambda: _claim_in_transaction(self.journal, "run", "op", "a" * 64, "claim"),
                    ):
                        with self.assertRaises(JournalUnavailable) as caught:
                            action()
                        self.assertEqual(caught.exception.write_outcome, "NOT_STARTED")
                        self.assertEqual(str(caught.exception), "Financial operation requires admitted transaction")
                finally:
                    if begin:
                        self.journal._db.rollback()
        self.assertEqual(before, list(self.journal._db.iterdump()))

    def test_rules_use_only_narrow_capabilities_on_real_storage(self):
        journal = self.journal
        port = SimpleNamespace(
            **{
                name: getattr(journal, name)
                for name in (
                    "_require_financial_transaction",
                    "_reserve_identity_keys",
                    "_closed_scope",
                    "_conflict",
                    "_key",
                    "_load",
                    "_record",
                )
            }
        )
        self.assertFalse(hasattr(port, "_db"))
        op = operation()
        with journal._transaction():
            self.assertEqual(_reserve_in_transaction(port, op), "RESERVED")
            self.assertEqual(_claim_in_transaction(port, "run", "op", op.binding_digest, "claim"), "CLAIM_GRANTED")
        self.assertEqual(journal.rebuild("run"), journal.snapshot("run"))

    def test_late_identity_collision_rolls_back_prefix_and_keeps_conflict(self):
        first = operation()
        self.assertEqual(self.journal.reserve(first), "RESERVED")
        before = list(self.journal._db.execute("SELECT * FROM identities ORDER BY kind,key"))
        colliding = replace(operation(name="other"), permit_id=first.permit_id)
        with self.journal._transaction():
            self.assertEqual(_reserve_in_transaction(self.journal, colliding), "CONFLICT")
        self.assertEqual(before, list(self.journal._db.execute("SELECT * FROM identities ORDER BY kind,key")))
        state, _ = self.journal._load("run")
        self.assertNotIn("other", state["operations"])
        self.assertEqual(self.journal.snapshot("run").gate_status, "CONFLICT")
        self.assertEqual(self.journal.rebuild("run"), self.journal.snapshot("run"))

    def test_outer_rollback_reverts_events_keys_and_projection(self):
        before = list(self.journal._db.iterdump())
        op = operation(upper=50, closeout=True)
        with self.assertRaisesRegex(RuntimeError, "rollback witness"), self.journal._transaction():
            self.assertEqual(_reserve_in_transaction(self.journal, op), "RESERVED")
            self.assertEqual(
                _claim_in_transaction(self.journal, "run", "op", op.binding_digest, "claim"), "CLAIM_GRANTED"
            )
            raise RuntimeError("rollback witness")
        self.assertEqual(before, list(self.journal._db.iterdump()))

    def test_closeout_transfer_and_idempotency_do_not_double_charge(self):
        op = operation(upper=100, closeout=True)
        with self.journal._transaction():
            self.assertEqual(_reserve_in_transaction(self.journal, op), "RESERVED")
            reserved = self.journal.snapshot("run")
            self.assertEqual(_reserve_in_transaction(self.journal, op, expected_revision=0), "ALREADY_RESERVED")
            self.assertEqual(reserved, self.journal.snapshot("run"))
            self.assertEqual(
                _claim_in_transaction(self.journal, "run", "op", op.binding_digest, "first"), "CLAIM_GRANTED"
            )
            claimed = self.journal.snapshot("run")
            self.assertEqual(
                _claim_in_transaction(self.journal, "run", "op", op.binding_digest, "second"), "ALREADY_CLAIMED"
            )
            self.assertEqual(claimed, self.journal.snapshot("run"))
        final = self.journal.snapshot("run")
        self.assertEqual(final.active_reservations, 100)
        self.assertEqual(final.protected_closeout, 0)
        rebuilt = self.journal.rebuild("run")
        self.assertEqual(rebuilt, self.journal.snapshot("run"))
        self.assertEqual(rebuilt.active_reservations, final.active_reservations)
        self.assertEqual(rebuilt.protected_closeout, final.protected_closeout)

    def test_capacity_protection_and_stale_revision_refuse_without_mutation(self):
        before = list(self.journal._db.iterdump())
        with self.journal._transaction():
            self.assertEqual(_reserve_in_transaction(self.journal, operation(upper=901)), "DENY")
            self.assertEqual(_reserve_in_transaction(self.journal, operation(upper=101, closeout=True)), "DENY")
            with self.assertRaises(RevisionConflict):
                _reserve_in_transaction(self.journal, operation(), expected_revision=0)
            self.assertEqual(_claim_in_transaction(self.journal, "run", "missing", "a" * 64, "claim"), "UNAVAILABLE")
        self.assertEqual(before, list(self.journal._db.iterdump()))

    def test_changed_operation_binding_keeps_conflict_history(self):
        op = operation()
        self.assertEqual(self.journal.reserve(op), "RESERVED")
        with self.journal._transaction():
            self.assertEqual(_reserve_in_transaction(self.journal, replace(op, upper_bound_tokens=99)), "CONFLICT")
        self.assertEqual(self.journal.snapshot("run").gate_status, "CONFLICT")
        self.assertEqual(self.journal.rebuild("run"), self.journal.snapshot("run"))
