from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import _run_cli  # noqa: E402
except ImportError:
    from helpers import _run_cli  # noqa: E402


class WorktreeCommandTests(unittest.TestCase):
    def test_worktree_receipt_and_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "run.state.json"
            policy = root / "worktree-policy.json"
            receipt = root / "receipt.json"
            state.write_text(json.dumps(_state()), encoding="utf-8")
            policy.write_text(json.dumps(_policy()), encoding="utf-8")

            code, payload = _run_cli([
                "worktree",
                "receipt",
                "--state",
                str(state),
                "--policy",
                str(policy),
                "--task",
                "WS-01",
                "--attempt",
                "1",
                "--worktree-path",
                ".alk/worktrees/run-ws-01-1",
                "--baseline-ref",
                "main",
                "--baseline-sha",
                "source",
                "--changed-file",
                "src/example.py",
                "--reason",
                "isolated attempt",
                "--out",
                str(receipt),
            ])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-worktree-attempt-receipt.v1")

            code, payload = _run_cli(["worktree", "check", "--receipt", str(receipt), "--state", str(state), "--policy", str(policy)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-worktree-attempt-receipt-validation.v1")


def _policy() -> dict:
    return {
        "schemaVersion": "agent-worktree-isolation-policy.v1",
        "worktreeRoot": ".alk/worktrees",
        "allowedWriteRoots": ["src"],
        "preserveFailedAttempts": True,
        "cleanupRequiresOperator": True,
    }


def _state() -> dict:
    return {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 2,
        "phase": "RUNNING",
        "tasks": [{"id": "WS-01", "status": "READY", "attempt": 1, "writes": ["src"]}],
    }


if __name__ == "__main__":
    unittest.main()
