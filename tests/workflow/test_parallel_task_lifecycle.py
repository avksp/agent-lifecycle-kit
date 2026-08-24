from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, write_json_create
from agent_lifecycle.workflow import apply_task_review_outcome, commit_task_result, start_task
from agent_lifecycle.workflow.query import next_action
from agent_lifecycle.workflow.state import load_state


def _parallel_state(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "agent-workflow-state.v4",
                "runId": "run",
                "packageId": "package",
                "planRevision": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "stateRevision": 1,
                "phase": "RUNNING",
                "authorization": {"required": False, "granted": True},
                "budgets": {"maxParallelTasks": 2, "maxTaskAttempts": 2},
                "tasks": [
                    {
                        "id": task_id,
                        "status": "READY",
                        "attempt": 0,
                        "dependsOn": [],
                        "writes": [f"src/{task_id}.py"],
                        "artifactPaths": {
                            "result": f"work/{task_id}/attempt-{{attempt}}/task-result.json",
                            "review": f"work/{task_id}/attempt-{{attempt}}/task-review.json",
                        },
                        "attemptHistory": [],
                        "required": True,
                    }
                    for task_id in ("WS-01", "WS-02")
                ],
                "eventLog": "events.jsonl",
                "operationLedger": {},
            }
        ),
        encoding="utf-8",
    )


class ParallelTaskLifecycleTests(unittest.TestCase):
    def test_one_task_result_does_not_change_sibling_phase_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.state.json"
            _parallel_state(path)
            start_task(path, task_id="WS-01", operation_id="start-1", expected_revision=1, source_revision="source", reason="test")
            start_task(path, task_id="WS-02", operation_id="start-2", expected_revision=2, source_revision="source", reason="test")
            state = load_state(path)
            self.assertEqual(state["phase"], "RUNNING")
            self.assertEqual({task["status"] for task in state["tasks"]}, {"RUNNING"})
            self.assertEqual(next_action(state)["type"], "wait-for-active-tasks")

    def test_canonical_outcome_accepts_one_task_without_rewriting_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "run.state.json"
            _parallel_state(path)
            state = load_state(path)
            state["tasks"] = [state["tasks"][0]]
            state["budgets"]["maxParallelTasks"] = 1
            path.write_text(json.dumps(state), encoding="utf-8")
            start_task(path, task_id="WS-01", operation_id="start-1", expected_revision=1, source_revision="source", reason="test")
            result = {
                "schemaVersion": "agent-task-result.v2",
                "runId": "run",
                "taskId": "WS-01",
                "attempt": 1,
                "planDigest": "0" * 64,
                "sourceRevision": "source",
                "actor": "worker",
                "actorRunId": "worker-run",
                "taskPacketHash": "0" * 64,
                "itemOutcomes": [{"status": "COMPLETE"}],
                "changedFiles": [],
                "changeSet": {"baselineSha": "source", "provider": "git-worktree-v1"},
                "commands": [],
            }
            result_path = root / "work/WS-01/attempt-1/task-result.json"
            write_json_create(result_path, result)
            commit_task_result(
                path,
                task_id="WS-01",
                operation_id="result-1",
                expected_revision=2,
                source_revision="source",
                result_path="work/WS-01/attempt-1/task-result.json",
                reason="test",
            )
            review = {
                "schemaVersion": "agent-task-review.v2",
                "reviewId": "review-1",
                "runId": "run",
                "taskId": "WS-01",
                "attempt": 1,
                "planDigest": "0" * 64,
                "resultHash": canonical_digest(result),
                "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "test", "independent": True},
                "verdict": "ACCEPTED",
                "findings": [],
            }
            write_json_create(root / "work/WS-01/attempt-1/task-review.json", review)
            payload = apply_task_review_outcome(
                path,
                task_id="WS-01",
                operation_id="review-1",
                expected_revision=3,
                source_revision="source",
                review_path="work/WS-01/attempt-1/task-review.json",
                reason="test",
            )
            self.assertEqual(payload["phase"], "FINAL_AUDIT")
            self.assertEqual(payload["tasks"][0]["status"], "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
