from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting import build_lifecycle_progress_view, build_lifecycle_progress_watch, build_status_view


class StatusViewTests(unittest.TestCase):
    def test_status_view_is_read_only_and_compact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/pass.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(json.dumps({"schemaVersion": "artifact.v1", "status": "PASS", "blockers": []}), encoding="utf-8")

            view = build_status_view(project_root=root, artifact_paths=[Path("evidence/pass.json")], target_window="4k-strict")

        rendered = json.dumps(view, sort_keys=True)
        self.assertEqual(view["schemaVersion"], "agent-readonly-status-view.v1")
        self.assertEqual(view["status"], "PASS")
        self.assertFalse(view["sourceOfTruth"])
        self.assertEqual(view["targetWindow"], "4k-strict")
        self.assertLess(view["estimatedTokens"], 300)
        self.assertNotIn(str(root), rendered)

    def test_status_view_fails_on_failed_source_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "evidence/fail.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                json.dumps(
                    {
                        "schemaVersion": "artifact.v1",
                        "status": "FAIL",
                        "blockers": [{"code": "missing-evidence"}],
                    }
                ),
                encoding="utf-8",
            )

            view = build_status_view(project_root=root, artifact_paths=[Path("evidence/fail.json")])

        self.assertEqual(view["status"], "FAIL")
        self.assertEqual(view["items"][0]["blockerCodes"], ["missing-evidence"])
        self.assertIn("status-view-artifact-failed", {item["code"] for item in view["blockers"]})

    def test_lifecycle_progress_view_formats_one_line_rows_and_terminal_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            usage = root / "usage.json"
            changes = root / "changes.json"
            state.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-workflow-state.v3",
                        "runId": "run-1",
                        "packageId": "package",
                        "planRevision": 1,
                        "planDigest": "0" * 64,
                        "sourceRevision": "main",
                        "stateRevision": 5,
                        "phase": "COMPLETE",
                        "runStartedAt": "2026-08-01T10:00:00Z",
                        "authorization": {"mode": "approval-required"},
                        "budgets": {},
                        "tasks": [{"id": "WS-01", "status": "ACCEPTED", "attempt": 1, "required": True}],
                        "lifecycleProgressSteps": [
                            {
                                "name": "implementation",
                                "status": "DONE",
                                "durationSeconds": 65,
                                "taskIds": ["WS-01"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            usage.write_text(
                json.dumps(
                    {
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
                            "wallSeconds": 65,
                        },
                        "attestation": {"source": "host", "status": "ATTESTED"},
                    }
                ),
                encoding="utf-8",
            )
            changes.write_text(
                json.dumps(
                    {
                        "filesChanged": 7,
                        "insertions": 432,
                        "deletions": 118,
                        "modified": 5,
                        "added": 1,
                        "deleted": 1,
                    }
                ),
                encoding="utf-8",
            )

            view = build_lifecycle_progress_view(
                state_path=state,
                usage_receipt_paths=[usage],
                change_summary_path=changes,
            )

        self.assertEqual(view["schemaVersion"], "agent-lifecycle-progress-view.v1")
        self.assertTrue(view["readOnly"])
        self.assertFalse(view["tokenSpendForProgress"])
        self.assertIn("00:01:05", view["lines"][0])
        self.assertIn("↑0.2k/↓1.1k tok", view["lines"][0])
        self.assertEqual(
            view["terminalSummary"]["changeSummary"],
            "7 files changed · 432 insertions · 118 deletions · 5 modified · 1 added · 1 deleted",
        )
        self.assertIn("TOTAL", view["terminalSummary"]["line"])

    def test_lifecycle_progress_view_keeps_unknown_tokens_for_unattested_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.json"
            usage = root / "usage.json"
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
            usage.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
                        "usage": {"inputTokens": 1100, "outputTokens": 200},
                        "attestation": {"source": "host", "status": "MISSING"},
                    }
                ),
                encoding="utf-8",
            )

            view = build_lifecycle_progress_view(state_path=state, usage_receipt_paths=[usage])

        self.assertIn("↑?/↓? tok", view["lines"][0])

    def test_lifecycle_progress_watch_rereads_without_state_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
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
            before = state.read_bytes()

            watch = build_lifecycle_progress_watch(state_path=state, iterations=2, interval_seconds=0)
            after = state.read_bytes()

        self.assertEqual(watch["schemaVersion"], "agent-lifecycle-progress-watch.v1")
        self.assertEqual(watch["frameCount"], 2)
        self.assertTrue(watch["readOnly"])
        self.assertFalse(watch["stateWritten"])
        self.assertFalse(watch["tokenSpendForProgress"])
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
