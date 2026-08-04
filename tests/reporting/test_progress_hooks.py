from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting.progress_hooks import (
    build_progress_hook_policy,
    build_progress_hook_receipt,
)


class ProgressHookTests(unittest.TestCase):
    def test_hook_receipt_wraps_bridge_without_mutating_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = _write_state(root)
            before = state.read_bytes()

            receipt = build_progress_hook_receipt(
                adapter_id="codex",
                support_level="AUTO",
                command="workflow run",
                hook_point="after-workflow-run",
                hook_mode="stderr",
                state_path=state,
                managed_workflow_proof={"kind": "alk-managed-workflow-command", "status": "PASS", "command": "workflow run"},
            )
            after = state.read_bytes()

        self.assertEqual(receipt["schemaVersion"], "agent-progress-hook-receipt.v1")
        self.assertEqual(receipt["status"], "EMITTED")
        self.assertTrue(receipt["autoClaimAllowed"])
        self.assertFalse(receipt["pluginInstalledIsLifecycleProof"])
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["stateWritten"])
        self.assertFalse(receipt["tokenSpendForProgress"])
        self.assertIn("RUNNING", receipt["terminalText"])
        self.assertEqual(before, after)

    def test_hook_policy_is_default_off_and_stdout_safe(self) -> None:
        policy = build_progress_hook_policy(hook_mode="stderr")

        self.assertEqual(policy["schemaVersion"], "agent-progress-hook-policy.v1")
        self.assertFalse(policy["defaultEnabled"])
        self.assertTrue(policy["stdoutJsonPreserved"])
        self.assertTrue(policy["stderrOnly"])
        self.assertFalse(policy["pluginInstalledIsLifecycleProof"])


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
