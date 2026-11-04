"""Lower reader and journal data-candidate proof, without host qualification."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.accounting.workflow_authority_store import (
    prepare_legacy_adoption_candidate,
    validate_legacy_adoption_history,
)
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.workflow_state_authority import (
    decode_workflow_authority,
    historical_snapshots,
    validate_recovery_state,
    validate_typed_blocker,
    read_workflow_authority,
    validate_workflow_authority,
    workflow_authority_operation,
)
from agent_lifecycle.contracts.workflow_storage import persist_storage, prepare_storage
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from tests.accounting import test_workflow_store_recovery as journal_fixtures
from tests.workflow.test_state_storage import state_fixture


def authority_fixture(root: Path) -> tuple[Path, dict]:
    state = state_fixture()
    state.update(stateRevision=1, phase="RUNNING", eventLog="events.jsonl")
    prepared = prepare_storage(state, storage_root="state.json.storage")
    persist_storage(root, prepared)
    path = root / "state.json"
    path.write_bytes(canonical_bytes(prepared.state) + b"\n")
    return path, prepared.state


class WorkflowStateAuthorityTests(unittest.TestCase):
    def test_missing_authority_needs_explicit_creation_root_and_keeps_one_lifetime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "state.json"
            with workflow_authority_operation(path, allow_missing=True) as missing:
                self.assertIsNone(missing)
                self.assertIsNone(StorageOperation.current())
            with self.assertRaises(FileNotFoundError), workflow_authority_operation(path, creation_root=root):
                self.fail("A root alone must not allow a missing state")
            with workflow_authority_operation(path, allow_missing=True, creation_root=root) as operation:
                self.assertIsNotNone(operation)
                lifetime = (operation.started, operation.deadline)
                with workflow_authority_operation(path, allow_missing=True, creation_root=root) as nested:
                    self.assertIs(nested, operation)
                    self.assertEqual((nested.started, nested.deadline), lifetime)
                other = root / "other"
                other.mkdir()
                with (
                    self.assertRaises(LifecycleError),
                    workflow_authority_operation(path, allow_missing=True, creation_root=other),
                ):
                    self.fail("A nested creator must not select a different root")
            self.assertIsNone(StorageOperation.current())
            with self.assertRaises(LifecycleError):
                operation.check()
            self.assertFalse(path.exists())

    def test_lower_reader_retains_compact_identity_and_validates_unselected_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = authority_fixture(root)
            self.assertEqual(read_workflow_authority(path), state)
            self.assertEqual(canonical_digest(read_workflow_authority(path)), canonical_digest(state))
            reference = state["priorSnapshots"][0]
            (root / state["storage"]["root"] / reference["path"]).unlink()
            with self.assertRaises(LifecycleError):
                read_workflow_authority(path)

    def test_v5_decode_requires_explicit_root_path_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = authority_fixture(root)
            for kwargs in ({}, {"root": root}, {"root": root, "state_path": path}):
                with self.subTest(kwargs=kwargs), self.assertRaises(LifecycleError) as raised:
                    validate_workflow_authority(state, **kwargs)
                self.assertEqual(raised.exception.code, "workflow-storage-context-required")
            with StorageOperation(root, state_path=path) as operation:
                self.assertEqual(
                    decode_workflow_authority(path.read_bytes(), root=root, state_path=path, operation=operation),
                    state,
                )
            with self.assertRaises(LifecycleError):
                validate_legacy_adoption_history(state, [])

    def test_reader_refuses_wrong_root_and_noncanonical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = authority_fixture(root)
            with StorageOperation(root, state_path=path) as operation:
                with self.assertRaises(LifecycleError):
                    decode_workflow_authority(path.read_bytes()[:-1], root=root, state_path=path, operation=operation)
                changed = deepcopy(state)
                changed["storage"]["root"] = "other.storage"
                with self.assertRaises(LifecycleError):
                    validate_workflow_authority(changed, root=root, state_path=path, operation=operation)

    def test_v5_journal_candidate_keeps_exact_raw_ref_and_compact_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adoption, selection = journal_fixtures.LegacyAdoptionHistoryTests._candidate_fixture(root)
            import json

            path = root / "state.json"
            state = json.loads(path.read_bytes())
            snapshot = deepcopy(state)
            snapshot["financialRole"] = "HISTORICAL_ALREADY_INCLUDED_IN_CUMULATIVE_ACCOUNTING"
            state["priorSnapshots"] = [snapshot]
            prepared = prepare_storage(state, storage_root="state.json.storage")
            persist_storage(root, prepared)
            raw = canonical_bytes(prepared.state) + b"\n"
            path.write_bytes(raw)
            adoption["legacyStateRef"].update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
            candidate = prepare_legacy_adoption_candidate(
                adoption, selection, artifact_root=root, observed_at="2026-04-01T00:00:00.000000Z"
            )
            self.assertEqual(candidate["stateDigest"], canonical_digest(prepared.state))
            self.assertFalse(candidate["nativePermissionGranted"])
            reference = prepared.state["priorSnapshots"][0]
            (root / prepared.state["storage"]["root"] / reference["path"]).write_bytes(b"{}\n")
            with self.assertRaises(LifecycleError):
                prepare_legacy_adoption_candidate(
                    adoption, selection, artifact_root=root, observed_at="2026-04-01T00:00:00.000000Z"
                )

    def test_explicit_operation_root_and_v5_history_context_cannot_be_rebound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, state = authority_fixture(root)
            raw = path.read_bytes()
            other = root / "other"
            other.mkdir()
            with StorageOperation(root, state_path=path) as operation:
                self.assertEqual(read_workflow_authority(path, root=root, operation=operation), state)
                with self.assertRaises(LifecycleError) as raised:
                    read_workflow_authority(path, root=other, operation=operation)
                self.assertEqual(raised.exception.code, "workflow-storage-invalid")
                changed = deepcopy(state)
                changed["packageRoot"] = "child"
                with self.assertRaises(LifecycleError) as raised:
                    validate_workflow_authority(changed, root=root, state_path=path, operation=operation)
                self.assertEqual(raised.exception.code, "workflow-storage-invalid")
                self.assertTrue(list(historical_snapshots(state)))
            with self.assertRaises(LifecycleError) as raised:
                list(historical_snapshots(state))
            self.assertEqual(raised.exception.code, "workflow-storage-context-required")
            with self.assertRaises(LifecycleError) as raised:
                decode_workflow_authority(raw, root=root, state_path=path)
            self.assertEqual(raised.exception.code, "workflow-storage-context-required")
            self.assertEqual(path.read_bytes(), raw)

    def test_typed_blocker_negative_table_and_matching_task_are_immutable(self):
        blocker = {"code": "input-changed", "reason": "new evidence required", "scope": "task",
                   "recoveryRoute": "task-review", "taskId": "WS-01", "attempt": 1}
        variants = [
            ("non-object", [], "invalid-workflow-state"),
            ("nested", {**blocker, "blocker": {}}, "nested-blocker-forbidden"),
            ("nested-list", {**blocker, "blockers": []}, "nested-blocker-forbidden"),
            ("task-id", {**blocker, "taskId": None}, "invalid-workflow-blocker"),
            ("foreign-scope", {**blocker, "scope": "run", "recoveryRoute": "resolve-run"},
             "invalid-workflow-blocker"),
            ("route", {**blocker, "recoveryRoute": "adopt-plan"}, "invalid-workflow-blocker"),
            ("attempt-zero", {**blocker, "attempt": 0}, "invalid-workflow-blocker"),
            ("attempt-bool", {**blocker, "attempt": True}, "invalid-workflow-blocker"),
        ]
        variants.extend((key, {**blocker, key: ""}, "invalid-workflow-blocker")
                        for key in ("code", "reason", "scope", "recoveryRoute"))
        for label, value, code in variants:
            before = deepcopy(value)
            with self.subTest(case=label), self.assertRaises(LifecycleError) as raised:
                validate_typed_blocker(value)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(value, before)
        with self.assertRaises(LifecycleError) as raised:
            validate_typed_blocker(blocker, expected_task_id="WS-02")
        self.assertEqual(raised.exception.code, "workflow-blocker-lineage-mismatch")
        before = deepcopy(blocker)
        self.assertIs(validate_typed_blocker(blocker, expected_task_id="WS-01"), blocker)
        self.assertEqual(blocker, before)

    def test_recovery_phase_and_blocker_lineage_table_uses_actual_validator(self):
        # This checks recovery vocabulary only; full authority validation remains separate.
        task_blocker = {"code": "input-changed", "reason": "review", "scope": "task",
                        "recoveryRoute": "task-review", "taskId": "WS-01", "attempt": 1}
        task = {"id": "WS-01", "blocker": deepcopy(task_blocker)}
        baseline = {"phase": "RUNNING", "tasks": [task], "blocker": None}
        variants = [
            ("plan-mode", {**baseline, "phase": "PLAN_ONLY", "startMode": "execute"},
             "invalid-workflow-state"),
            ("plan-grant", {**baseline, "phase": "PLAN_ONLY", "startMode": "plan-only",
                            "authorization": {"granted": True}}, "plan-only-authorized"),
            ("blocked-empty", {**baseline, "phase": "BLOCKED"}, "invalid-workflow-state"),
            ("unknown-task", {**baseline, "blocker": task_blocker, "tasks": []},
             "workflow-blocker-lineage-mismatch"),
            ("nested-lineage", {**baseline, "blocker": task_blocker,
                                "tasks": [{"id": "WS-01", "blocker": {**task_blocker, "taskId": "WS-02"}}]},
             "workflow-blocker-lineage-mismatch"),
            ("different-blockers", {**baseline, "blocker": task_blocker,
                                   "tasks": [{"id": "WS-01", "blocker": {**task_blocker, "reason": "other"}}]},
             "workflow-blocker-lineage-mismatch"),
            ("budget-empty", {**baseline, "phase": "WAITING_FOR_BUDGET_DECISION"},
             "invalid-workflow-state"),
            ("budget-route", {**baseline, "phase": "WAITING_FOR_BUDGET_DECISION", "blocker": task_blocker},
             "invalid-workflow-state"),
            ("external-empty", {**baseline, "phase": "WAITING_FOR_EXTERNAL_ACTION"},
             "invalid-workflow-state"),
        ]
        for label, value, code in variants:
            before = deepcopy(value)
            with self.subTest(case=label), self.assertRaises(LifecycleError) as raised:
                validate_recovery_state(value)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(value, before)
        accepted = [
            {**baseline, "phase": "PLAN_ONLY", "startMode": "plan-only", "authorization": {"granted": False}},
            {**baseline, "phase": "BLOCKED", "blocker": task_blocker},
            {**baseline, "phase": "BLOCKED", "blocker": task_blocker, "tasks": [{"id": "WS-01"}]},
            {**baseline, "phase": "WAITING_FOR_BUDGET_DECISION",
             "blocker": {**task_blocker, "recoveryRoute": "budget-decision"}},
            {**baseline, "phase": "WAITING_FOR_EXTERNAL_ACTION", "externalAction": {}},
        ]
        for value in accepted:
            before = deepcopy(value)
            validate_recovery_state(value)
            self.assertEqual(value, before)
