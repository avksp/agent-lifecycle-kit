from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.reporting.progress_hooks import build_progress_hook_receipt


class ManagedWorkflowProgressProofTests(unittest.TestCase):
    def test_auto_progress_requires_managed_workflow_proof_not_plugin_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = _write_state(Path(tmp))

            with self.assertRaises(LifecycleError) as raised:
                build_progress_hook_receipt(
                    adapter_id="codex",
                    support_level="AUTO",
                    command="workflow run",
                    hook_point="after-workflow-run",
                    hook_mode="stderr",
                    state_path=state,
                    managed_workflow_proof={"kind": "plugin-install", "status": "PASS", "command": "workflow run"},
                )

        self.assertEqual(raised.exception.code, "progress-hook-proof-kind")

    def test_auto_progress_receipt_carries_managed_workflow_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = _write_state(Path(tmp))

            receipt = build_progress_hook_receipt(
                adapter_id="codex",
                support_level="AUTO",
                command="workflow run",
                hook_point="after-workflow-run",
                hook_mode="stderr",
                state_path=state,
                managed_workflow_proof={"kind": "alk-managed-workflow-command", "status": "PASS", "command": "workflow run"},
            )

        self.assertTrue(receipt["autoClaimAllowed"])
        self.assertEqual(receipt["managedWorkflowProof"]["kind"], "alk-managed-workflow-command")
        self.assertFalse(receipt["pluginInstalledIsLifecycleProof"])


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
                "sourceRevision": "main",
                "stateRevision": 1,
                "phase": "RUNNING",
                "authorization": {"mode": "approval-required"},
                "budgets": {},
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    return state


if __name__ == "__main__":
    unittest.main()
