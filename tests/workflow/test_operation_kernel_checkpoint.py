from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.contracts.workflow_continuation_schemas import build_workflow_continuation_authority_projection
from agent_lifecycle.workflow.operation_kernel import commit_state


class OperationKernelCheckpointTests(unittest.TestCase):
    def test_prepared_event_and_ledger_share_observation_across_second_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run-1",
                "packageId": "package-1",
                "planRevision": 1,
                "planDigest": "a" * 64,
                "sourceRevision": "main@abc",
                "stateRevision": 1,
                "phase": "RUNNING",
                "tasks": [],
                "eventLog": "events.jsonl",
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            earlier = "2026-01-01T00:00:00.999999Z"
            later = "2026-01-01T00:00:01.000000Z"
            with (
                patch("agent_lifecycle.workflow.operation_kernel.now_iso", return_value=earlier),
                patch("agent_lifecycle.workflow.state.now_iso", return_value=later),
            ):
                commit_state(state_path, state, operation_id="clock-boundary", event_type="task-completed", payload={})
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            event = json.loads((state_path.parent / "events.jsonl").read_text(encoding="utf-8"))
            ledger_time = stored["operationLedger"]["clock-boundary"]["recordedAt"]
            self.assertEqual(stored["updatedAt"], earlier)
            self.assertEqual(ledger_time, later)
            self.assertEqual(event["recordedAt"], ledger_time)
            projection = build_workflow_continuation_authority_projection(stored, [event])
            self.assertEqual(projection["state"]["updatedAt"], "<observation-time>")

    def test_commit_seam_records_checkpoint_receipt_and_commits_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "work/release/run.state.json"
            state_path.parent.mkdir(parents=True)
            state = {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run-1",
                "packageId": "package-1",
                "planRevision": 1,
                "planDigest": "a" * 64,
                "sourceRevision": "main@abc",
                "stateRevision": 1,
                "phase": "RUNNING",
                "tasks": [],
                "eventLog": "events.jsonl",
                "contextCheckpointPolicy": {
                    "enabled": True,
                    "required": True,
                    "milestoneEvents": ["task-completed"],
                    "checkpointRoot": ".alk/context/checkpoints",
                },
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            commit_state(
                state_path,
                state,
                operation_id="op-1",
                event_type="task-completed",
                payload={"result": "complete"},
            )
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["stateRevision"], 2)
            events = (state_path.parent / "events.jsonl").read_text(encoding="utf-8")
            event = json.loads(events.strip())
            self.assertEqual(event["payload"]["contextCheckpoint"]["status"], "PASS")
            self.assertTrue(list((root / ".alk/context/checkpoints").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
