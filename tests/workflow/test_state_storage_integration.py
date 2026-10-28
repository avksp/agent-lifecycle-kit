"""Native storage transaction boundaries; fixture outcomes are not release acceptance."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError, workflow_storage_io
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.workflow_storage import iter_historical_snapshots, task_evidence
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from agent_lifecycle.workflow.initialization import migrate_workflow_state
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update, observe_workflow_writes
from agent_lifecycle.workflow.state import load_state
from agent_lifecycle.workflow.transactions import workflow_transaction_context
from tests.workflow.test_state_storage import state_fixture


class WorkflowStorageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "state.json"
        state = state_fixture()
        state.update(stateRevision=1, phase="RUNNING", eventLog="events.jsonl")
        self.path.write_bytes(canonical_bytes(state) + b"\n")
        migrate_workflow_state(
            self.path,
            operation_id="migrate",
            expected_revision=1,
            source_revision="source",
            target_schema="agent-workflow-state.v5",
        )

    def commit(self, state, **kwargs):
        return commit_state(
            self.path, state, operation_id="mutation", event_type="fixture-change", payload={}, **kwargs
        )

    def evidence_change(self):
        state = load_state(self.path)
        state["tasks"][0]["resultChangeSetEvidence"] = {
            "schemaVersion": "agent-task-change-set-evidence.v1",
            "entries": [{"new": True}],
        }
        return state

    def test_outer_native_context_and_callbacks_share_cache_start_and_deadline(self):
        with (
            workflow_transaction_context(self.path),
            patch.object(
                workflow_storage_io, "read_authority_bytes", wraps=workflow_storage_io.read_authority_bytes
            ) as read,
        ):
            operation = StorageOperation.current()
            self.assertIsNotNone(operation)
            state = load_state(self.path)
            expected = operation.object_count
            started, deadline = operation.started, operation.deadline
            task_evidence(self.root, state, state["tasks"][0], "ownershipReceipt")
            list(iter_historical_snapshots(self.root, state))

            def callback():
                self.assertIs(StorageOperation.current(), operation)
                self.assertEqual((operation.started, operation.deadline), (started, deadline))
                self.assertEqual(load_state(self.path), state)

            self.commit(state, persist_artifacts=(callback,))
            self.assertEqual(read.call_count, expected)
            self.assertEqual(operation.physical_reads, expected)
        self.assertEqual(load_state(self.path)["stateRevision"], 3)

    def test_observer_sees_exact_sidecar_bytes_before_any_publication(self):
        observed = []
        before = set((self.root / "state.json.storage").rglob("*.json"))

        def observer(outputs):
            if not observed:
                self.assertEqual(set((self.root / "state.json.storage").rglob("*.json")), before)
            observed.append(outputs)

        with observe_workflow_writes(self.path, observer):
            self.commit(self.evidence_change())
        sidecars = {
            p: data for p, data in observed[0].items() if p.is_relative_to((self.root / "state.json.storage").resolve())
        }
        self.assertTrue(sidecars)
        self.assertTrue(all(p.read_bytes() == data for p, data in sidecars.items()))

    def test_preflight_or_deadline_refusal_never_calls_artifact_callback(self):
        for mode in ("history", "deadline", "observer"):
            with self.subTest(mode=mode):
                state = self.evidence_change()
                before, events = self.path.read_bytes(), (self.root / "events.jsonl").read_bytes()
                calls = []
                saved = None
                if mode == "history":
                    ref = state["priorSnapshots"][0]
                    target = self.root / state["storage"]["root"] / ref["path"]
                    saved = target.read_bytes()
                    target.unlink()
                try:
                    with workflow_transaction_context(self.path):
                        if mode == "deadline":
                            StorageOperation.current()._deadline = 0
                        with (
                            observe_workflow_writes(
                                self.path,
                                lambda _values, mode=mode: (
                                    (_ for _ in ()).throw(LifecycleError("test-deny", "denied"))
                                    if mode == "observer"
                                    else None
                                ),
                            ),
                            self.assertRaises(LifecycleError),
                        ):
                            self.commit(state, persist_artifacts=(lambda calls=calls: calls.append(True),))
                finally:
                    if saved is not None:
                        target.write_bytes(saved)
                self.assertEqual(calls, [])
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual((self.root / "events.jsonl").read_bytes(), events)

    def test_expiry_after_sidecar_keeps_orphan_and_authority_unchanged(self):
        state = self.evidence_change()
        before, events = self.path.read_bytes(), (self.root / "events.jsonl").read_bytes()
        old = set((self.root / "state.json.storage").rglob("*.json"))
        original = workflow_storage_io.create_authority_bytes

        def write_then_expire(*args, **kwargs):
            result = original(*args, **kwargs)
            StorageOperation.current()._deadline = 0
            return result

        with (
            patch.object(workflow_storage_io, "create_authority_bytes", side_effect=write_then_expire),
            self.assertRaises(LifecycleError) as raised,
        ):
            self.commit(state)
        self.assertEqual(raised.exception.code, "workflow-storage-deadline-exceeded")
        self.assertGreater(len(set((self.root / "state.json.storage").rglob("*.json")) - old), 0)
        self.assertTrue(raised.exception.details["publications"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.root / "events.jsonl").read_bytes(), events)
        self.commit(state)

    def test_event_and_state_write_faults_preserve_split_brain_rules(self):
        before = self.path.read_bytes()
        with (
            patch("agent_lifecycle.workflow.operation_kernel.append_event", side_effect=OSError("event fault")),
            self.assertRaises(OSError),
        ):
            self.commit(self.evidence_change())
        self.assertEqual(self.path.read_bytes(), before)
        with (
            patch("agent_lifecycle.workflow.operation_kernel.write_state_replace", side_effect=OSError("state fault")),
            self.assertRaises(OSError),
        ):
            self.commit(self.evidence_change())
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(LifecycleError) as raised:
            load_for_update(self.path, operation_id="retry", expected_revision=2, authorization_required=False)
        self.assertEqual(raised.exception.code, "workflow-split-brain")

    def test_expiry_after_state_write_reports_committed_state_without_acceptance_inference(self):
        from agent_lifecycle.workflow import operation_kernel

        original = operation_kernel.write_state_replace

        def write_then_expire(path, state):
            original(path, state)
            StorageOperation.current()._deadline = 0

        with (
            patch.object(operation_kernel, "write_state_replace", side_effect=write_then_expire),
            self.assertRaises(LifecycleError) as raised,
        ):
            self.commit(deepcopy(load_state(self.path)))
        self.assertEqual(load_state(self.path)["stateRevision"], 3)
        self.assertEqual(raised.exception.details["publications"][-1]["outcome"], "REPLACED")

    def test_expiry_after_event_retains_append_and_refuses_split_brain_retry(self):
        from agent_lifecycle.workflow import operation_kernel

        original = operation_kernel.append_event
        before = self.path.read_bytes()

        def append_then_expire(**kwargs):
            result = original(**kwargs)
            StorageOperation.current()._deadline = 0
            return result

        with (
            patch.object(operation_kernel, "append_event", side_effect=append_then_expire),
            self.assertRaises(LifecycleError) as raised,
        ):
            self.commit(self.evidence_change())
        self.assertEqual(raised.exception.details["publications"][-1]["outcome"], "APPENDED")
        self.assertEqual(self.path.read_bytes(), before)
        with self.assertRaises(LifecycleError) as split:
            load_for_update(self.path, operation_id="retry", expected_revision=2, authorization_required=False)
        self.assertEqual(split.exception.code, "workflow-split-brain")

    def test_checkpoint_expiry_and_required_failure_retain_actual_checkpoint(self):
        from agent_lifecycle.workflow import operation_kernel

        original = operation_kernel.persist_checkpoint_gate
        state = self.evidence_change()
        state["contextCheckpointPolicy"] = {
            "enabled": True,
            "required": True,
            "milestoneEvents": ["fixture-change"],
        }
        before, events = self.path.read_bytes(), (self.root / "events.jsonl").read_bytes()

        def checkpoint_then_expire(prepared):
            result = original(prepared)
            StorageOperation.current()._deadline = 0
            return result

        with (
            patch.object(operation_kernel, "persist_checkpoint_gate", side_effect=checkpoint_then_expire),
            self.assertRaises(LifecycleError) as raised,
        ):
            self.commit(state)
        self.assertEqual(raised.exception.code, "workflow-storage-deadline-exceeded")
        self.assertEqual(raised.exception.details["publications"][-1]["outcome"], "CHECKPOINT_OBSERVED")
        self.assertTrue(list((self.root / ".alk").rglob("*.json")))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.root / "events.jsonl").read_bytes(), events)

    def test_artifact_and_checkpoint_faults_leave_state_and_events_unchanged(self):
        state = self.evidence_change()
        before, events = self.path.read_bytes(), (self.root / "events.jsonl").read_bytes()

        def artifact_fault():
            raise OSError("artifact fault")

        with self.assertRaises(OSError):
            self.commit(state, persist_artifacts=(artifact_fault,))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.root / "events.jsonl").read_bytes(), events)
        with (
            patch(
                "agent_lifecycle.workflow.operation_kernel.persist_checkpoint_gate", side_effect=OSError("checkpoint")
            ),
            self.assertRaises(OSError),
        ):
            self.commit(state)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.root / "events.jsonl").read_bytes(), events)
