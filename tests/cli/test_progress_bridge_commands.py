from __future__ import annotations

import json
import contextlib
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from agent_lifecycle.cli import main

try:
    from .helpers import _run_cli  # noqa: F401,E402
except ImportError:
    from helpers import _run_cli  # noqa: F401,E402


class ProgressBridgeCommandTests(unittest.TestCase):
    def test_report_progress_terminal_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = _write_state(root)

            code, payload = _run_cli(["report", "progress", "--state", str(state)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-progress-view.v1")

            terminal = _run_cli_text(
                [
                    "report",
                    "progress",
                    "--state",
                    str(state),
                    "--terminal",
                ]
            )

        self.assertIn("RUNNING", terminal)
        self.assertNotIn('"schemaVersion"', terminal)

    def test_report_progress_bridge_json_and_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = _write_state(root)
            out = root / "out/bridge.json"

            code, receipt = _run_cli(
                [
                    "report",
                    "progress-bridge",
                    "--adapter",
                    "codex",
                    "--support-level",
                    "WATCH",
                    "--hook-point",
                    "side-terminal-watch",
                    "--state",
                    str(state),
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(receipt["schemaVersion"], "agent-progress-bridge-receipt.v1")
            self.assertTrue(receipt["readOnly"])
            self.assertTrue(out.is_file())

            terminal = _run_cli_text(
                [
                    "report",
                    "progress-bridge",
                    "--adapter",
                    "codex",
                    "--support-level",
                    "WATCH",
                    "--hook-point",
                    "side-terminal-watch",
                    "--state",
                    str(state),
                    "--terminal",
                ]
            )

        self.assertIn("RUNNING", terminal)
        self.assertNotIn('"schemaVersion"', terminal)


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


def _run_cli_text(args: list[str]) -> str:
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(args)
    if code != 0:
        raise AssertionError(f"CLI returned {code}: {stdout.getvalue()}")
    return stdout.getvalue()


if __name__ == "__main__":
    unittest.main()
