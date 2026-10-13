"""A pure clock observation cannot reset persisted local UTC high-water."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.accounting.contracts import canonical, digest
from agent_lifecycle.accounting.journal import Journal
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.deadline_schemas import CLOCK_OBSERVATION_V1, validate_clock_observation
from agent_lifecycle.contracts.deadlines import evaluate_original_permission
from agent_lifecycle.contracts.schemas import get_schema

from .test_journal import open_scope, operation, receipt
from .test_workflow_authority_store import WRITER, WorkflowAuthorityStoreTests


class DeadlineClockTests(unittest.TestCase):
    def test_dd01_dd03_exact_utc_and_nondecending_high_water(self) -> None:
        observation = {
            "schemaVersion": CLOCK_OBSERVATION_V1,
            "journalIdentity": "journal", "processIdentity": "process",
            "observedAt": "2026-09-23T01:00:00.000001Z", "monotonicNanos": 42,
            "monotonicOriginId": "origin", "previousAcceptedUtc": "2026-09-23T01:00:00.000000Z",
            "clockQualificationDigest": "a" * 64,
        }
        self.assertEqual(get_schema(CLOCK_OBSERVATION_V1)["$id"], CLOCK_OBSERVATION_V1)
        self.assertIs(validate_clock_observation(observation), observation)
        for change in (
            {"observedAt": "2026-09-23T00:59:59.999999Z"},
            {"observedAt": "2026-09-23T01:00:00Z"},
            {"monotonicNanos": True},
            {"previousAcceptedUtc": "2026-09-23T01:00:00+00:00"},
        ):
            with self.subTest(change=change), self.assertRaises(LifecycleError):
                validate_clock_observation({**observation, **change})

    def test_dd16_expired_work_still_settles_and_revokes_without_new_grant(self) -> None:
        rule = {
            "kind": "EXECUTION_PERMISSION",
            "originalAuthorizationRef": {"path": "proof/original.json", "sha256": "a" * 64, "bytes": 12},
            "validFrom": "2026-09-23T01:00:00.000000Z",
            "expiresAt": "2026-09-23T02:00:00.000000Z",
            "replacement": "RETAIN_ORIGINAL",
        }
        before = evaluate_original_permission(rule, "2026-09-23T01:59:59.999999Z")
        expired = evaluate_original_permission(rule, rule["expiresAt"])
        self.assertEqual(before["disposition"], "DATA_CANDIDATE")
        self.assertEqual(expired["disposition"], "REFUSED_OR_NATIVE_INTERSECTION_REQUIRED")
        self.assertIs(expired["nativeAuthorityGranted"], False)
        with tempfile.TemporaryDirectory() as directory, Journal(Path(directory) / "journal.db", WRITER) as journal:
            fixture = WorkflowAuthorityStoreTests()
            store, initial = fixture._fixture(journal)
            state = {
                "schemaVersion": "agent-workflow-state.v4", "runId": "run", "packageId": "package",
                "planRevision": 1, "planDigest": "a" * 64, "sourceRevision": "source",
                "stateRevision": 1, "phase": "RUNNING", "eventLog": "events.jsonl",
                "operationLedger": {},
                "tasks": [{"id": "WS-01", "status": "READY", "attempt": 0, "dependsOn": [],
                           "attemptHistory": [], "required": True}],
            }
            journal._db.execute(
                "INSERT INTO workflow_states VALUES(?,?,?,?,?)",
                ("run", 1, digest(state), canonical(state), 1),
            )
            open_scope(journal)
            existing = operation(name="before-expiry")
            self.assertEqual(journal.reserve(existing), "RESERVED")
            self.assertEqual(journal.claim(
                "run", existing.operation_id, existing.binding_digest, "claim:before-expiry"
            ), "CLAIM_GRANTED")
            before_claims = journal._db.execute(
                "SELECT COUNT(*) FROM identities WHERE kind='claim' AND scope='run'"
            ).fetchone()[0]
            self.assertEqual(journal.record_settlement(receipt(existing, 19)), "SETTLED")
            settled = journal.snapshot("run")
            self.assertEqual(settled.known_spent, 19)
            self.assertEqual(store.reconcile_operation("missing", "f" * 64), {"status": "NOT_COMMITTED"})
            self.assertEqual(store.reserve_closing_operation({"expired": True}), {
                "status": "DENY", "reason": "UNSUPPORTED_OPERATOR_ROUTE", "writeOutcome": "NOT_STARTED",
            })
            self.assertEqual(journal.rebuild("run"), settled)
            successor = fixture._successor(initial)
            request = fixture._request(Path(directory), successor, "revoke-after-expiry", 0)
            self.assertEqual(store.install_authority_snapshot(
                request, artifact_root=Path(directory)
            )["status"], "INSTALLED")
            self.assertEqual(journal.snapshot("run"), settled)
            self.assertEqual(journal._db.execute(
                "SELECT COUNT(*) FROM identities WHERE kind='claim' AND scope='run'"
            ).fetchone()[0], before_claims)
