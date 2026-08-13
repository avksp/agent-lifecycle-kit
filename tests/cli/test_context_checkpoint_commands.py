from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from .helpers import _run_cli
from agent_lifecycle.contracts import canonical_digest


class ContextCheckpointCommandTests(unittest.TestCase):
    def test_checkpoint_and_restore_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "run.state.json"
            plan = root / "plan.json"
            source = root / "context.json"
            output = root / ".alk/context/checkpoints/checkpoint.json"
            continuation = root / "continuation.json"
            plan_payload = {
                "schemaVersion": "agent-plan-manifest.v1",
                "status": "FROZEN",
                "planRevision": 1,
                "package": {"id": "package-1"},
            }
            plan.write_text(json.dumps(plan_payload), encoding="utf-8")
            state.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-workflow-state.v3",
                        "runId": "run-1",
                        "packageId": "package-1",
                        "planRevision": 1,
                        "planDigest": canonical_digest(plan_payload),
                        "sourceRevision": "main@abc",
                        "stateRevision": 1,
                        "phase": "RUNNING",
                        "tasks": [],
                    }
                ),
                encoding="utf-8",
            )
            source.write_text(
                json.dumps(
                    {
                        "latestUserIntent": "Continue the reviewed task.",
                        "activeDecisions": ["Keep the plan authoritative."],
                        "openBlockers": [],
                        "nextRequiredAction": "run focused tests",
                    }
                ),
                encoding="utf-8",
            )
            previous = Path.cwd()
            os.chdir(root)
            try:
                code, checkpoint = _run_cli(
                    [
                        "context",
                        "checkpoint",
                        "--session",
                        "session-1",
                        "--state",
                        str(state),
                        "--plan",
                        str(plan),
                        "--input",
                        str(source),
                        "--reason",
                        "agent-requested",
                        "--capture-mode",
                        "MILESTONE",
                        "--out",
                        str(output),
                    ]
                )
                self.assertEqual(code, 0)
                self.assertEqual(checkpoint["schemaVersion"], "agent-context-checkpoint.v1")
                self.assertEqual(checkpoint["captureMode"], "MILESTONE")
                self.assertTrue(output.exists())
                code, restored = _run_cli(
                    [
                        "context",
                        "restore",
                        "--checkpoint",
                        str(output),
                        "--state",
                        str(state),
                        "--session",
                        "session-1",
                        "--out",
                        str(continuation),
                    ]
                )
            finally:
                os.chdir(previous)
            self.assertEqual(code, 0)
            self.assertEqual(restored["schemaVersion"], "agent-context-continuation.v1")
            self.assertFalse(restored["implementationAuthorized"])
            self.assertTrue(continuation.exists())


if __name__ == "__main__":
    unittest.main()
