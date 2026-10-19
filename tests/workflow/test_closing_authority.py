"""Current protected operations deny before effects; synthetic SQL is not authority."""
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from agent_lifecycle.accounting.contracts import EvidenceRef
from agent_lifecycle.accounting.journal import Journal
from tests.accounting import test_workflow_authority_store as fixture_module


@contextmanager
def protected_store():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        with Journal(root / "journal.sqlite", EvidenceRef("test-writer", "a" * 64)) as journal:
            store, _ = fixture_module.WorkflowAuthorityStoreTests()._fixture(journal)
            yield root, journal, store


def semantic_rows(journal):
    return tuple(journal._connection.iterdump())


class ClosingAuthorityTests(unittest.TestCase):
    def test_all_protected_work_producers_refuse_without_writes(self):
        with protected_store() as (root, journal, store):
            before = semantic_rows(journal)
            for name in ("reserve_closing_operation", "claim_with_workflow_authority",
                         "authorize_local_proof_production", "commit_transition"):
                with self.subTest(operation=name):
                    extra = {"artifact_root": root} if name == "commit_transition" else {}
                    result = getattr(store, name)({}, **extra)
                    self.assertEqual(result, {"status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE",
                                              "writeOutcome": "NOT_STARTED"})
                    self.assertEqual(semantic_rows(journal), before)

    def test_caller_declared_qualification_cannot_enable_reservation(self):
        with protected_store() as (_, journal, store):
            before = semantic_rows(journal)
            for request in ({"operatorQualified": True}, {"permission": "closing.activate"},
                            {"status": "PASS", "financialAdmission": True}):
                self.assertEqual(store.reserve_closing_operation(request)["reason"], "UNSUPPORTED_OPERATOR_ROUTE")
                self.assertEqual(semantic_rows(journal), before)
