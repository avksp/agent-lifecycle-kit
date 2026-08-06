from __future__ import annotations

import json
import contextlib
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from agent_lifecycle.cli import main  # noqa: E402
try:
    from .helpers import _run_cli  # noqa: E402
except ImportError:
    from helpers import _run_cli  # noqa: E402


class GoalCommandTests(unittest.TestCase):
    def test_goal_check_validates_record_against_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, record_path = _write_goal_inputs(root)

            code, payload = _run_cli(["goal", "check", "--record", str(record_path), "--state", str(state_path), "--current"])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-goal-record-validation.v1")
            self.assertEqual(payload["goalId"], "release-015")

    def test_goal_summarize_renders_compact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, record_path = _write_goal_inputs(root)

            code, payload = _run_cli([
                "goal",
                "summarize",
                "--record",
                str(record_path),
                "--state",
                str(state_path),
                "--profile",
                str(ROOT / "profiles/small-context-profile.v1.json"),
                "--target-window",
                "8k",
            ])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-objective-snapshot.v1")
            self.assertEqual(payload["goal"]["goalId"], "release-015")
            self.assertEqual(payload["lifecycle"]["nextAction"]["type"], "run-final-audit")

    def test_goal_update_writes_updated_record_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, record_path = _write_goal_inputs(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["stateRevision"] = 4
            state_path.write_text(json.dumps(state), encoding="utf-8")
            out_path = root / "goal.updated.json"

            code, payload = _run_cli([
                "goal",
                "update",
                "--record",
                str(record_path),
                "--state",
                str(state_path),
                "--status",
                "READY_FOR_FINALIZATION",
                "--evidence-id",
                "EV-FINAL",
                "--reason",
                "accepted evidence is ready",
                "--out",
                str(out_path),
            ])

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "READY_FOR_FINALIZATION")
            self.assertEqual(payload["lineage"]["stateRevision"], 4)
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), payload)

    def test_goal_view_returns_json_and_optional_terminal_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, record_path = _write_goal_inputs(root)
            out_path = root / "goal-view.json"

            code, payload = _run_cli([
                "goal",
                "view",
                "--record",
                str(record_path),
                "--state",
                str(state_path),
                "--out",
                str(out_path),
            ])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-goal-progress-view.v1")
            self.assertTrue(payload["readOnly"])
            self.assertFalse(payload["modelCallsStarted"])
            self.assertEqual(payload["goal"]["goalId"], "release-015")
            self.assertEqual(json.loads(out_path.read_text(encoding="utf-8")), payload)

            code, terminal = _run_cli_text([
                "goal",
                "view",
                "--record",
                str(record_path),
                "--state",
                str(state_path),
                "--terminal",
            ])

            self.assertEqual(code, 0)
            self.assertIn("GOAL", terminal)
            self.assertIn("LIFECYCLE", terminal)
            self.assertNotIn('"schemaVersion"', terminal)

    def test_goal_check_rejects_stale_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, record_path = _write_goal_inputs(root)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["lineage"]["stateRevision"] = 1
            record_path.write_text(json.dumps(record), encoding="utf-8")

            code, payload = _run_cli(["goal", "check", "--record", str(record_path), "--state", str(state_path), "--current"])

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "goal-state-stale")


def _write_goal_inputs(root: Path) -> tuple[Path, Path]:
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 3,
        "phase": "RUNNING",
        "tasks": [{"id": "WS-01", "status": "ACCEPTED", "attempt": 1, "required": True}],
    }
    record = {
        "schemaVersion": "agent-goal-record.v1",
        "goalId": "release-015",
        "userIntent": "Ship release 0.15 with compact continuity.",
        "ownerOutcome": "The release is complete and validated.",
        "constraints": ["Keep validation deterministic", "Avoid copied external names"],
        "status": "ACTIVE",
        "lineage": {
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
            "stateRevision": 3,
        },
        "evidenceIds": [],
        "updatedAt": "2026-07-30T08:00:00Z",
    }
    state_path = root / "run.state.json"
    record_path = root / "goal.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    return state_path, record_path


def _run_cli_text(args: list[str]) -> tuple[int, str]:
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(args)
    return code, stdout.getvalue()


if __name__ == "__main__":
    unittest.main()
