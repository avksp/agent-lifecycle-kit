from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting import build_workflow_event_feed


class EventFeedTests(unittest.TestCase):
    def test_event_feed_is_deterministic_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            _write_state(state_path)

            feed = build_workflow_event_feed(state_path=state_path)
            second = build_workflow_event_feed(state_path=state_path)

            after = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(feed, second)
        self.assertEqual(feed["schemaVersion"], "agent-workflow-event-feed.v1")
        self.assertEqual(feed["status"], "PASS")
        self.assertFalse(feed["sourceOfTruth"])
        self.assertTrue(feed["readOnly"])
        self.assertFalse(feed["modelCallsStarted"])
        self.assertFalse(feed["stateWritten"])
        self.assertEqual(after["stateRevision"], 3)
        self.assertEqual(feed["eventCount"], 4)
        self.assertEqual(
            [item["eventType"] for item in feed["events"]],
            ["run-observed", "task-observed", "task-observed", "operation-recorded"],
        )


def _write_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v3",
                "runId": "run-1",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "main",
                "stateRevision": 3,
                "phase": "RUNNING",
                "runStartedAt": "2026-08-01T10:00:00Z",
                "authorization": {"mode": "approval-required"},
                "budgets": {},
                "tasks": [
                    {"id": "WS-02", "status": "PENDING", "attempt": 0, "required": True},
                    {"id": "WS-01", "status": "RUNNING", "attempt": 1, "required": True},
                ],
                "operationLedger": {
                    "op-start": {
                        "stateRevision": 2,
                        "eventType": "task-started",
                        "recordedAt": "2026-08-01T10:01:00Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
