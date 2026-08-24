from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class MultiRunViewCommandTests(unittest.TestCase):
    def test_multi_run_command_is_explicit_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = root / "work" / "run-a"
            run.mkdir(parents=True)
            state = {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run-a",
                "packageId": "p-a",
                "planRevision": 1,
                "planDigest": "1" * 64,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": "COMPLETE",
                "tasks": [],
                "operationLedger": {},
                "eventLog": "workflow-events.jsonl",
            }
            state_path = run / "run.state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            (run / "workflow-events.jsonl").write_text("{\"eventType\":\"run-complete\"}\n", encoding="utf-8")
            out = root / "out" / "view.json"

            code, payload = _run_cli(
                [
                    "report",
                    "multi-run",
                    "--project-root",
                    str(root),
                    "--run-root",
                    "work/run-a",
                    "--out",
                    str(out),
                ]
            )
            out_exists = out.is_file()

            after = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-multi-run-attention-view.v1")
        self.assertTrue(payload["readOnly"])
        self.assertFalse(payload["sourceOfTruth"])
        self.assertTrue(out_exists)
        self.assertEqual(after, state)


if __name__ == "__main__":
    unittest.main()
