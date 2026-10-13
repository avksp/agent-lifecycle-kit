"""Legacy event and operation lineage must be complete before journal adoption."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.accounting.contracts import (
    EvidenceRef,
    canonical,
    digest,
)
from agent_lifecycle.accounting.journal import Journal, JournalUnavailable
from agent_lifecycle.accounting.workflow_state_store import (
    WorkflowStore,
    prepare_legacy_adoption_candidate,
    validate_legacy_adoption_history,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_digest
from agent_lifecycle.contracts.workflow_authority_schemas import AUTHORITY_SNAPSHOT_V1
from tests.contracts.test_workflow_authority import _issuer, _pin, _signed

from .test_journal import operation as make_operation
from .test_opening_balances import import_data


def _state() -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v4", "runId": "run", "packageId": "package",
        "planRevision": 1, "planDigest": "a" * 64, "sourceRevision": "source", "stateRevision": 1,
        "phase": "RUNNING", "eventLog": "events.jsonl", "operationLedger": {},
        "tasks": [{"id": "WS-01", "status": "READY", "attempt": 0, "dependsOn": [],
                   "attemptHistory": [], "required": True}],
    }


class LegacyAdoptionHistoryTests(unittest.TestCase):
    @staticmethod
    def _artifact(root: Path, name: str, raw: bytes) -> dict:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    @classmethod
    def _candidate_fixture(cls, root: Path) -> tuple[dict, dict]:
        qualification = cls._artifact(root, "proof/qualification.json", b"operator evidence")
        snapshot = _signed({
            "schemaVersion": AUTHORITY_SNAPSHOT_V1, "authorityDomain": "authority:run",
            "rootId": "root", "rootGeneration": "generation:1", "bindingId": "binding",
            "journalIdentity": "journal", "epoch": 0, "previousSnapshotDigest": None,
            "validFrom": "2020-01-01T00:00:00.000000Z", "expiresAt": "2100-01-01T00:00:00.000000Z",
            "activeIssuers": [_issuer()], "revokedIssuers": [], "revokedGrants": [],
        }, bytes(range(32)), b"agent-lifecycle-workflow-authority-snapshot-v1\x00")
        pin = {**_pin(), "qualificationRef": qualification,
               "expectedInitialSnapshotDigest": canonical_digest(snapshot)}
        pin_ref = cls._artifact(root, "pin.json", canonical(pin).encode("utf-8"))
        binding = {
            "schemaVersion": "agent-workflow-journal-binding.v1", "bindingId": "binding", "runId": "run",
            "packageId": "package", "budgetScopeId": "budget:run", "canonicalStatePath": "state.json",
            "journalPath": str(root / "journal.db"), "journalIdentity": "journal",
            "storageProtocolVersion": "5", "workflowProtocolVersion": "1", "planDigest": "a" * 64,
            "sourceRevision": "source", "adoptionEpoch": "epoch-1", "authorityMode": "JOURNAL_REQUIRED",
            "workflowAuthorityPinRef": pin_ref, "resourceInventoryRef": qualification,
            "deadlineInventoryRef": qualification,
        }
        adoption = {
            "schemaVersion": "agent-workflow-adoption-input.v1", "operationId": "adopt-1",
            "bindingRef": cls._artifact(root, "binding.json", canonical(binding).encode("utf-8")),
            "legacyStateRef": cls._artifact(root, "state.json", canonical(_state()).encode("utf-8")),
            "legacyEventLogRef": None,
            "initialSnapshotRef": cls._artifact(root, "snapshot.json", canonical(snapshot).encode("utf-8")),
            "accountingMode": "EXISTING_QUALIFIED_SCOPE",
        }
        selection = {
            "schemaVersion": "agent-workflow-adoption-selection.v1",
            "expectedBindingDigest": canonical_digest(binding), "expectedPinDigest": canonical_digest(pin),
            "expectedInitialSnapshotDigest": canonical_digest(snapshot),
            "expectedAccountingStateDigest": "f" * 64, "expectedAccountingRevision": 1,
            "expectedJournalIdentity": "journal", "expectedBudgetScopeId": "budget:run",
            "expectedStorageProtocolVersion": "5", "expectedWorkflowProtocolVersion": "1",
            "operatorQualificationRef": qualification, "quiescenceEvidenceRef": qualification,
            "writerInventoryRef": qualification,
        }
        return adoption, selection

    def test_exact_initial_artifacts_remain_data_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adoption, selection = self._candidate_fixture(root)
            result = prepare_legacy_adoption_candidate(
                adoption, selection, artifact_root=root, observed_at="2026-09-23T01:00:00.000000Z"
            )
            self.assertEqual(result["status"], "DATA_CANDIDATE")
            self.assertEqual(result["eventCount"], 0)
            for name in ("operatorQualified", "quiescenceQualified", "accountingHistoryQualified",
                         "financialAdmission", "nativePermissionGranted"):
                self.assertFalse(result[name])
            (root / "events.jsonl").write_bytes(b"")
            with self.assertRaises(LifecycleError):
                prepare_legacy_adoption_candidate(
                    adoption, selection, artifact_root=root, observed_at="2026-09-23T01:00:00.000000Z"
                )
            adoption["legacyEventLogRef"] = self._artifact(root, "events.jsonl", b"")
            self.assertEqual(prepare_legacy_adoption_candidate(
                adoption, selection, artifact_root=root, observed_at="2026-09-23T01:00:00.000000Z"
            )["eventCount"], 0)

    def test_changed_artifact_or_self_selected_pin_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adoption, selection = self._candidate_fixture(root)
            (root / "state.json").write_bytes(b"{}")
            with self.assertRaises(LifecycleError):
                prepare_legacy_adoption_candidate(
                    adoption, selection, artifact_root=root, observed_at="2026-09-23T01:00:00.000000Z"
                )
            adoption["legacyStateRef"] = self._artifact(root, "state.json", canonical(_state()).encode("utf-8"))
            with self.assertRaises(LifecycleError):
                prepare_legacy_adoption_candidate(
                    adoption, {**selection, "expectedPinDigest": "0" * 64}, artifact_root=root,
                    observed_at="2026-09-23T01:00:00.000000Z",
                )
            snapshot_raw = (root / "snapshot.json").read_bytes() + b" " * 1_048_576
            adoption["initialSnapshotRef"] = self._artifact(root, "snapshot.json", snapshot_raw)
            with self.assertRaises(LifecycleError):
                prepare_legacy_adoption_candidate(
                    adoption, selection, artifact_root=root, observed_at="2026-09-23T01:00:00.000000Z"
                )

    def test_complete_event_prefix_and_exact_path_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adoption, selection = self._candidate_fixture(root)
            state, events = self._history()
            adoption["legacyStateRef"] = self._artifact(root, "state.json", canonical(state).encode("utf-8"))
            raw = b"".join(canonical(event).encode("utf-8") + b"\n" for event in events)
            adoption["legacyEventLogRef"] = self._artifact(root, "events.jsonl", raw)
            result = prepare_legacy_adoption_candidate(
                adoption, selection, artifact_root=root, observed_at="2026-09-23T01:00:00.000000Z"
            )
            self.assertEqual(result["eventCount"], 2)
            self.assertEqual(result["operationIds"], ["first", "second"])
            adoption["legacyEventLogRef"] = self._artifact(root, "other.jsonl", raw)
            with self.assertRaises(LifecycleError):
                prepare_legacy_adoption_candidate(
                    adoption, selection, artifact_root=root, observed_at="2026-09-23T01:00:00.000000Z"
                )

    def test_existing_accounting_replay_is_read_only_and_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adoption, selection = self._candidate_fixture(root)
            writer = EvidenceRef("fixture:writer", "a" * 64)
            with Journal(root / "journal.db", writer) as journal:
                binding = json.loads((root / adoption["bindingRef"]["path"]).read_text())
                binding["journalIdentity"] = journal.journal_identity
                binding["runId"] = "budget:run"
                scope, policy, opening = import_data("budget:run", spent=0)
                self.assertEqual(journal.import_opening(scope, policy, opening).status, "IMPORTED")
                store = WorkflowStore(journal, binding, canonical_digest(binding))
                state, revision = journal._load("budget:run")
                selected = {**selection, "expectedBindingDigest": canonical_digest(binding),
                            "expectedJournalIdentity": journal.journal_identity,
                            "expectedAccountingStateDigest": digest(state),
                            "expectedAccountingRevision": revision}
                result = store.read_adoption_accounting_candidate(selected)
                self.assertEqual(result["stateDigest"], digest(state))
                self.assertEqual(result["knownSpent"], 0)
                self.assertTrue(result["accountingReplayVerified"])
                self.assertFalse(result["accountingHistoryQualified"])
                self.assertFalse(result["financialAdmission"])
                self.assertFalse(journal._db.in_transaction)
                self.assertEqual(journal.reserve(make_operation(scope="budget:run", upper=100)), "RESERVED")
                with self.assertRaises(JournalUnavailable):
                    store.read_adoption_accounting_candidate(selected)
                current, current_revision = journal._load("budget:run")
                selected = {**selected, "expectedAccountingStateDigest": digest(current),
                            "expectedAccountingRevision": current_revision}
                self.assertEqual(store.read_adoption_accounting_candidate(selected)["activeReservations"], 100)
                with self.assertRaises(JournalUnavailable):
                    store.read_adoption_accounting_candidate({**selected, "expectedAccountingStateDigest": "0" * 64})

    @staticmethod
    def _history() -> tuple[dict, list[dict]]:
        state = _state()
        state["stateRevision"] = 3
        events = []
        for revision, operation in ((2, "first"), (3, "second")):
            event = {"schemaVersion": "agent-workflow-event.v1", "runId": "run",
                     "packageId": "package", "stateRevision": revision,
                     "operationId": operation, "eventType": "task-updated",
                     "payload": {"taskId": "WS-01"},
                     "recordedAt": "2026-09-23T01:00:00.000000Z"}
            state["operationLedger"][operation] = {
                "stateRevision": revision, "eventType": event["eventType"],
                "recordedAt": "2026-09-23T01:00:00.000000Z",
            }
            events.append(event)
        return state, events

    def test_complete_ordered_legacy_lineage_is_data_only(self) -> None:
        state, events = self._history()
        result = validate_legacy_adoption_history(state, events)
        self.assertEqual(result["eventCount"], 2)
        self.assertEqual(result["operationIds"], ["first", "second"])
        self.assertFalse(result["quiescenceQualified"])
        self.assertFalse(result["accountingHistoryQualified"])
        self.assertFalse(result["nativePermissionGranted"])
        initial = _state()
        self.assertEqual(validate_legacy_adoption_history(initial, [])["eventCount"], 0)

    def test_split_event_state_or_ledger_is_refused(self) -> None:
        state, events = self._history()
        variants = [
            (state, events[:-1]),
            (state, list(reversed(events))),
            (state, [events[0], {**events[1], "operationId": "first"}]),
            (state, [events[0], {**events[1], "runId": "other"}]),
            (state, [events[0], {**events[1], "unexpected": True}]),
            ({**state, "operationLedger": {"first": state["operationLedger"]["first"]}}, events),
            ({**state, "operationLedger": {**state["operationLedger"],
                                            "second": {**state["operationLedger"]["second"],
                                                       "eventType": "different"}}}, events),
            ({**state, "operationLedger": {**state["operationLedger"],
                                            "second": {**state["operationLedger"]["second"],
                                                       "recordedAt": "2026-09-23T02:00:00.000000Z"}}}, events),
        ]
        for selected_state, selected_events in variants:
            with self.subTest(state=selected_state, events=selected_events), self.assertRaises(LifecycleError):
                validate_legacy_adoption_history(copy.deepcopy(selected_state), copy.deepcopy(selected_events))
