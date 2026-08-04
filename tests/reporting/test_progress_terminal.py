from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting import (
    build_lifecycle_progress_view,
    build_lifecycle_progress_watch,
    render_progress_terminal,
)


class ProgressTerminalTests(unittest.TestCase):
    def test_renders_progress_view_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = _write_state(root, phase="RUNNING")
            before = state.read_bytes()

            view = build_lifecycle_progress_view(state_path=state)
            rendered = render_progress_terminal(view)
            after = state.read_bytes()

        self.assertIn("RUNNING", rendered)
        self.assertIn("ACTIVE", rendered)
        self.assertIn("TOTAL", rendered)
        self.assertIn("↑?/↓? tok", rendered)
        self.assertEqual(after, before)

    def test_renders_latest_watch_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = _write_state(root, phase="RUNNING")

            watch = build_lifecycle_progress_watch(state_path=state, iterations=2, interval_seconds=0)
            rendered = render_progress_terminal(watch)

        self.assertEqual(watch["schemaVersion"], "agent-lifecycle-progress-watch.v1")
        self.assertIn("RUNNING", rendered)
        self.assertIn("TOTAL", rendered)


def _write_state(root: Path, *, phase: str) -> Path:
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
                "phase": phase,
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
