from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow import migrate_workflow_state
from agent_lifecycle.workflow.state import load_state


def _legacy_state(path: Path, *, task_status: str = "READY") -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": "STEP_REVIEW" if task_status == "VERIFYING" else "RUNNING",
                "authorization": {"required": False, "granted": True},
                "tasks": [
                    {
                        "id": "WS-01",
                        "status": task_status,
                        "attempt": 1 if task_status == "VERIFYING" else 0,
                        "dependsOn": [],
                        "attemptHistory": [],
                        "required": True,
                    }
                ],
                "eventLog": "events.jsonl",
            }
        ),
        encoding="utf-8",
    )


class WorkflowStateMigrationTests(unittest.TestCase):
    def test_migrates_review_phase_to_task_local_v4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.state.json"
            _legacy_state(path, task_status="VERIFYING")
            payload = migrate_workflow_state(
                path,
                operation_id="migration-1",
                expected_revision=1,
                source_revision="source",
            )
            state = load_state(path)
            self.assertEqual(state["schemaVersion"], "agent-workflow-state.v4")
            self.assertEqual(state["phase"], "RUNNING")
            self.assertEqual(state["tasks"][0]["status"], "VERIFYING")
            self.assertEqual(payload["migrationReceipt"]["fromSchemaVersion"], "agent-workflow-state.v3")

    def test_rejects_legacy_status_without_v4_producer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.state.json"
            _legacy_state(path, task_status="VALIDATING")
            with self.assertRaises(LifecycleError) as raised:
                migrate_workflow_state(
                    path,
                    operation_id="migration-1",
                    expected_revision=1,
                    source_revision="source",
                )
            self.assertEqual(raised.exception.code, "workflow-state-migration-unsupported-status")


if __name__ == "__main__":
    unittest.main()
