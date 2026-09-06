"""Authority journal mutations must fail before native workflow state changes."""

from __future__ import annotations

import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import resolve_authority_anchor
from agent_lifecycle.workflow.continuation_batch import _events_by_operation
from agent_lifecycle.workflow.events import read_events
from agent_lifecycle.workflow.initialization import initialize_workflow_state
from agent_lifecycle.workflow.run_transitions import block_run


class WorkflowEventBoundaryTests(unittest.TestCase):
    def test_duplicate_members_cannot_hide_an_ahead_event_revision(self) -> None:
        for record, code in (
            (b'{"operationId":"prior","stateRevision":9}\n', "workflow-split-brain"),
            (b'{"operationId":"prior","stateRevision":9,"stateRevision":1}\n', "invalid-json"),
            (b'{"operationId":"prior","payload":{"x":1,"x":2},"stateRevision":1}\n', "invalid-json"),
            (b'{"operationId":"prior","stateRevision":9,"stateRevi\\u0073ion":1}\n', "invalid-json"),
            (b"{malformed\n", "invalid-workflow-event-log"),
        ):
            with self.subTest(code=code, record=record), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_path = root / "run.state.json"
                initialize_workflow_state(state_path, run_id="run", package_id="package")
                before = state_path.read_bytes()
                journal = root / "events.jsonl"
                journal.write_bytes(record)
                with self.assertRaises(LifecycleError) as raised:
                    block_run(
                        state_path,
                        operation_id="must-not-commit",
                        expected_revision=1,
                        blocker_code="test",
                        reason="negative journal test",
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(journal.read_bytes(), record)
                rendered = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn(str(journal), rendered)
                self.assertNotIn(record.decode("utf-8").strip(), rendered)

    def test_batch_replay_uses_the_same_duplicate_member_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = b'{"operationId":"first","operationId":"second","stateRevision":1}\n'
            (root / "events.jsonl").write_bytes(record)
            with self.assertRaises(LifecycleError) as raised:
                _events_by_operation(root / "run.state.json", {"packageRoot": ".", "eventLog": "events.jsonl"})
            self.assertEqual(raised.exception.code, "invalid-json")
            self.assertEqual((root / "events.jsonl").read_bytes(), record)

    def test_journal_is_streamed_without_a_whole_log_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            row = b'{"operationId":"prior","stateRevision":1,"padding":"' + b"x" * 1000 + b'"}\n'
            path.write_bytes(row * 1100)
            self.assertGreater(path.stat().st_size, 1_048_576)
            self.assertEqual(sum(1 for _ in read_events(path)), 1100)

    def test_parent_layout_anchor_is_allowed_only_inside_the_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "work" / "release" / "run.state.json"
            with patch.object(Path, "cwd", return_value=root):
                self.assertEqual(resolve_authority_anchor(state_path, "../.."), root)
                with self.assertRaises(LifecycleError) as raised:
                    resolve_authority_anchor(state_path, "../../..")
            self.assertEqual(raised.exception.code, "authority-path-outside-root")


if __name__ == "__main__":
    unittest.main()
