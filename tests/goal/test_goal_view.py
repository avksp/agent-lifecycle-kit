from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.goal import build_goal_progress_view
from agent_lifecycle.reporting import render_goal_view_terminal


class GoalViewTests(unittest.TestCase):
    def test_builds_read_only_goal_progress_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, record_path, usage_path, changes_path = _write_inputs(root)
            before_state = state_path.read_bytes()
            before_record = record_path.read_bytes()

            view = build_goal_progress_view(
                record_path=record_path,
                state_path=state_path,
                usage_receipt_paths=[usage_path],
                change_summary_path=changes_path,
            )

            self.assertEqual(view["schemaVersion"], "agent-goal-progress-view.v1")
            self.assertEqual(view["status"], "PASS")
            self.assertFalse(view["sourceOfTruth"])
            self.assertTrue(view["readOnly"])
            self.assertFalse(view["modelCallsStarted"])
            self.assertFalse(view["hostCallsStarted"])
            self.assertFalse(view["stateMutated"])
            self.assertFalse(view["goalRecordMutated"])
            self.assertFalse(view["stateWritten"])
            self.assertFalse(view["goalRecordWritten"])
            self.assertEqual(view["goal"]["goalId"], "goal-1")
            self.assertEqual(view["lifecycle"]["phase"], "RUNNING")
            self.assertEqual(view["metrics"]["duration"], "00:01:30")
            self.assertEqual(view["metrics"]["tokens"], "↑0.2k/↓1.1k tok")
            self.assertIn("2 files changed", view["metrics"]["changeSummary"])
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual(record_path.read_bytes(), before_record)

    def test_terminal_renderer_adds_goal_and_lifecycle_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, record_path, usage_path, changes_path = _write_inputs(root)
            view = build_goal_progress_view(
                record_path=record_path,
                state_path=state_path,
                usage_receipt_paths=[usage_path],
                change_summary_path=changes_path,
            )

            rendered = render_goal_view_terminal(view)

        self.assertIn("GOAL", rendered)
        self.assertIn("LIFECYCLE", rendered)
        self.assertIn("ACTIVE", rendered)
        self.assertIn("RUNNING", rendered)
        self.assertIn("TOTAL", rendered)


def _write_inputs(root: Path) -> tuple[Path, Path, Path, Path]:
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
        "lifecycleProgressSteps": [
            {"name": "implementation", "status": "DONE", "durationSeconds": 90, "taskIds": ["WS-01"]}
        ],
    }
    record = {
        "schemaVersion": "agent-goal-record.v1",
        "goalId": "goal-1",
        "userIntent": "Finish the requested change.",
        "ownerOutcome": "The change is complete and validated.",
        "constraints": ["Stay read-only in progress views"],
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
    usage = {
        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
        "operationId": "op-1",
        "host": "codex",
        "modelClass": "balanced",
        "providerModelHash": "1" * 64,
        "taskId": "WS-01",
        "usage": {
            "inputTokens": 1100,
            "outputTokens": 200,
            "billableTokens": 1300,
            "cumulativeContextBytes": 0,
            "toolCalls": 0,
            "wallSeconds": 90,
        },
        "attestation": {"source": "host", "status": "ATTESTED"},
    }
    changes = {
        "filesChanged": 2,
        "insertions": 30,
        "deletions": 4,
        "modified": 1,
        "added": 1,
        "deleted": 0,
    }
    state_path = root / "state.json"
    record_path = root / "goal.json"
    usage_path = root / "usage.json"
    changes_path = root / "changes.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    usage_path.write_text(json.dumps(usage), encoding="utf-8")
    changes_path.write_text(json.dumps(changes), encoding="utf-8")
    return state_path, record_path, usage_path, changes_path


if __name__ == "__main__":
    unittest.main()
