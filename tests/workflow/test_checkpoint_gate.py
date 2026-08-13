from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.checkpoint_gate import invoke_checkpoint_gate, normalize_context_checkpoint_policy


class CheckpointGateTests(unittest.TestCase):
    def test_policy_defaults_to_minimal_disabled_behavior(self) -> None:
        policy = normalize_context_checkpoint_policy(None)
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["maxCheckpointsPerRun"], 64)

    def test_required_capture_fails_before_commit_data_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "work/release/run.state.json"
            state_path.parent.mkdir(parents=True)
            state = _state()
            state["planDigest"] = "invalid"
            state["contextCheckpointPolicy"] = {
                "enabled": True,
                "required": True,
                "milestoneEvents": ["task-completed"],
                "checkpointRoot": ".alk/context/checkpoints",
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaises(LifecycleError):
                invoke_checkpoint_gate(
                    state_path=state_path,
                    state=state,
                    operation_id="op-1",
                    event_type="task-completed",
                    payload={"result": "not enough lineage"},
                )
            self.assertFalse((root / ".alk/context/checkpoints").exists())
            self.assertEqual(state["stateRevision"], 1)

    def test_optional_capture_is_non_blocking_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "work/release/run.state.json"
            state_path.parent.mkdir(parents=True)
            state = _state()
            state["contextCheckpointPolicy"] = {
                "enabled": True,
                "required": False,
                "milestoneEvents": ["task-completed"],
                "checkpointRoot": ".alk/context/checkpoints",
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            first = invoke_checkpoint_gate(
                state_path=state_path,
                state=state,
                operation_id="op-1",
                event_type="task-completed",
                payload={"result": "complete"},
            )
            second = invoke_checkpoint_gate(
                state_path=state_path,
                state=state,
                operation_id="op-1",
                event_type="task-completed",
                payload={"result": "complete"},
            )
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(first["checkpointDigest"], second["checkpointDigest"])
            self.assertEqual(len(list((root / ".alk/context/checkpoints").glob("*.json"))), 1)


def _state() -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run-1",
        "packageId": "package-1",
        "planRevision": 1,
        "planDigest": "a" * 64,
        "sourceRevision": "main@abc",
        "stateRevision": 1,
        "phase": "RUNNING",
        "tasks": [],
    }


if __name__ == "__main__":
    unittest.main()
