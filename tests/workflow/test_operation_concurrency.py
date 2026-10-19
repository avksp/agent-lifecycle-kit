"""Real process contention, journal failures and public mutation authority."""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow import block_run
from agent_lifecycle.workflow.state import load_state, write_state_replace
from tests.workflow.helpers import _write_state


def _contending_writer(path, barrier, results, name):
    barrier.wait(timeout=15)
    try:
        block_run(Path(path), operation_id=name, expected_revision=1, blocker_code="test", reason="contention")
        results.put((name, "PASS"))
    except LifecycleError as error:
        results.put((name, error.code))


class OperationConcurrencyTests(unittest.TestCase):
    def test_two_processes_commit_once_with_one_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _write_state(root, phase="RUNNING")
            state = load_state(path)
            state["contextCheckpointPolicy"] = {
                "enabled": True,
                "required": True,
                "milestoneEvents": ["run-blocked"],
                "checkpointRoot": ".alk/context/checkpoints",
            }
            write_state_replace(path, state)
            context = multiprocessing.get_context("spawn")
            barrier, results = context.Barrier(3), context.Queue()
            alias = path.with_name(path.name.upper())
            second_path = alias if alias.exists() else path
            children = [
                context.Process(target=_contending_writer, args=(str(selected), barrier, results, name))
                for name, selected in (("writer-a", path), ("writer-b", second_path))
            ]
            try:
                for child in children:
                    child.start()
                barrier.wait(timeout=15)
                observations = [results.get(timeout=20) for _ in children]
                for child in children:
                    child.join(timeout=10)
                    self.assertEqual(child.exitcode, 0)
            finally:
                for child in children:
                    if child.is_alive():
                        child.terminate()
                        child.join(timeout=10)
                results.close()
            self.assertEqual(sorted(value for _, value in observations), ["PASS", "state-revision-mismatch"])
            winner = next(name for name, value in observations if value == "PASS")
            final = load_state(path)
            self.assertEqual(final["stateRevision"], 2)
            self.assertEqual(set(final["operationLedger"]), {winner})
            events = (root / "events.jsonl").read_text().splitlines()
            self.assertEqual(len(events), 1)
            self.assertEqual(json.loads(events[0])["operationId"], winner)
            self.assertEqual(len(list((root / ".alk/context/checkpoints").glob("*.json"))), 1)

    def test_legacy_rows_remain_readable_but_current_envelope_requires_operation_id(self) -> None:
        for legacy in (True, False):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = _write_state(root, phase="RUNNING")
                row = {"stateRevision": 1}
                if not legacy:
                    row["schemaVersion"] = "agent-workflow-event.v1"
                events = root / "events.jsonl"
                events.write_text(json.dumps(row) + "\n")
                before = path.read_bytes(), events.read_bytes()
                if legacy:
                    block_run(path, operation_id="new-event", expected_revision=1, blocker_code="unit", reason="legacy")
                    self.assertEqual(load_state(path)["stateRevision"], 2)
                    self.assertEqual(len(events.read_text().splitlines()), 2)
                else:
                    with self.assertRaises(LifecycleError) as caught:
                        block_run(
                            path, operation_id="refuse", expected_revision=1, blocker_code="unit", reason="invalid"
                        )
                    self.assertEqual(caught.exception.code, "invalid-workflow-event-log")
                    self.assertEqual((path.read_bytes(), events.read_bytes()), before)

    def test_append_then_replace_failure_releases_lock_and_refuses_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _write_state(root, phase="RUNNING")
            before = path.read_bytes()
            with patch("agent_lifecycle.workflow.operation_kernel.write_state_replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    block_run(path, operation_id="interrupted", expected_revision=1, blocker_code="test", reason="test")
            journal = (root / "events.jsonl").read_bytes()
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaises(LifecycleError) as caught:
                block_run(path, operation_id="retry", expected_revision=1, blocker_code="test", reason="test")
            self.assertEqual(caught.exception.code, "workflow-split-brain")
            self.assertEqual((root / "events.jsonl").read_bytes(), journal)
            self.assertEqual(path.read_bytes(), before)

    def test_duplicate_journal_revision_and_operation_are_not_accepted(self) -> None:
        for revision in (2, 3):
            with self.subTest(revision=revision), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = _write_state(root, phase="RUNNING")
                block_run(path, operation_id="original", expected_revision=1, blocker_code="test", reason="test")
                event_path = root / "events.jsonl"
                event = json.loads(event_path.read_text())
                event["stateRevision"] = revision
                with event_path.open("a") as handle:
                    handle.write(json.dumps(event) + "\n")
                before_state, before_events = path.read_bytes(), event_path.read_bytes()
                with self.assertRaises(LifecycleError) as caught:
                    block_run(path, operation_id="next", expected_revision=2, blocker_code="test", reason="test")
                self.assertEqual(caught.exception.code, "invalid-workflow-event-log")
                self.assertEqual(path.read_bytes(), before_state)
                self.assertEqual(event_path.read_bytes(), before_events)

    def test_revoked_or_expired_authority_refuses_before_mutation(self) -> None:
        for expired in (False, True):
            with self.subTest(expired=expired), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = _write_state(root, phase="RUNNING")
                state = load_state(path)
                if expired:
                    state["authorization"]["expiresAt"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
                else:
                    state["authorization"]["granted"] = False
                write_state_replace(path, state)
                before = path.read_bytes()
                with self.assertRaises(LifecycleError) as caught:
                    block_run(path, operation_id="denied", expected_revision=1, blocker_code="test", reason="test")
                self.assertEqual(
                    caught.exception.code, "authorization-expired" if expired else "authorization-required"
                )
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((root / "events.jsonl").exists())
