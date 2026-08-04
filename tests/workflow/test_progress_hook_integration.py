from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting.progress_hooks import build_progress_hook_receipt
from agent_lifecycle.workflow import start_execution


class WorkflowProgressHookIntegrationTests(unittest.TestCase):
    def test_progress_hook_reads_state_after_workflow_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            payload = start_execution(
                state_path,
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="approved",
            )

            receipt = build_progress_hook_receipt(
                adapter_id="codex",
                support_level="AUTO",
                command="workflow run",
                hook_point="after-workflow-run",
                hook_mode="stderr",
                state_path=state_path,
                managed_workflow_proof={"kind": "alk-managed-workflow-command", "status": "PASS", "command": "workflow run"},
            )

        self.assertEqual(payload["phase"], "RUNNING")
        self.assertEqual(receipt["stateIdentity"]["stateRevision"], 2)
        self.assertEqual(receipt["stateIdentity"]["phase"], "RUNNING")
        self.assertTrue(receipt["autoClaimAllowed"])
        self.assertFalse(receipt["stateWritten"])


def _write_state(root: Path) -> Path:
    state = root / "state.json"
    state.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run-1",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": "READY",
                "authorization": {"required": False, "granted": True},
                "budgets": {},
                "tasks": [],
                "eventLog": "events.jsonl",
            }
        ),
        encoding="utf-8",
    )
    return state


if __name__ == "__main__":
    unittest.main()
