from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow import initialize_workflow_state, status
from agent_lifecycle.workflow.run_transitions import block_run


class WorkflowStateContractTests(unittest.TestCase):
    def test_init_rejects_invalid_storage_paths_before_creating_any_files(self) -> None:
        for field, value in (
            ("event_log", "../outside.jsonl"),
            ("event_log", "C:events.jsonl"),
            ("event_log", "C:/events.jsonl"),
            ("event_log", "//server/share/events.jsonl"),
            ("event_log", "\\\\server\\share\\events.jsonl"),
            ("event_log", "events.jsonl:stream"),
            ("package_root", "C:/outside"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = root / "not-created" / "run.state.json"
                with self.assertRaises(LifecycleError) as raised:
                    initialize_workflow_state(state_path, run_id="run", package_id="package", **{field: value})
                self.assertEqual(raised.exception.code, "invalid-workflow-state")
                self.assertEqual(list(root.iterdir()), [])

    def test_duplicate_state_member_blocks_transition_before_event_or_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "run.state.json"
            initialize_workflow_state(state_path, run_id="run", package_id="package")
            original = state_path.read_bytes()
            ambiguous = original.replace(b'"stateRevision":1', b'"stateRevision":2,"stateRevision":1')
            self.assertNotEqual(ambiguous, original)
            state_path.write_bytes(ambiguous)
            with self.assertRaises(LifecycleError) as raised:
                block_run(
                    state_path,
                    operation_id="must-not-commit",
                    expected_revision=1,
                    blocker_code="test-only",
                    reason="duplicate state must be rejected",
                )
            self.assertEqual(raised.exception.code, "invalid-json")
            self.assertEqual(state_path.read_bytes(), ambiguous)
            self.assertFalse((Path(tmp) / "events.jsonl").exists())

    def test_init_creates_unbound_private_v4_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "run.state.json"
            payload = initialize_workflow_state(state_path, run_id="run", package_id="package")
            self.assertEqual(payload["phase"], "AWAITING_AUTHORIZATION")
            self.assertEqual(status(state_path)["schemaVersion"], "agent-workflow-status.v1")
            with self.assertRaises(FileExistsError):
                initialize_workflow_state(state_path, run_id="run", package_id="package")


if __name__ == "__main__":
    unittest.main()
