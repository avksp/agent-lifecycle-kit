from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
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

    def test_all_review_outcomes_fail_closed_for_incomplete_or_matching_identity(self) -> None:
        verdicts = ("ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED")
        mutations = (
            ("missing-actor", "task-result-invalid"),
            ("empty-actor", "task-result-invalid"),
            ("missing-actor-run", "task-result-invalid"),
            ("empty-actor-run", "task-result-invalid"),
            ("same-actor", "task-review-self-certification"),
            ("same-run", "task-review-self-certification"),
            ("missing-review-id", "task-review-invalid"),
            ("empty-review-id", "task-review-invalid"),
        )
        for verdict in verdicts:
            for mutation, expected_code in mutations:
                with self.subTest(verdict=verdict, mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    state_path, review_path = _review_outcome_fixture(root, verdict=verdict, mutation=mutation)
                    before_state = state_path.read_bytes()

                    with self.assertRaises(LifecycleError) as raised:
                        apply_task_review_outcome(
                            state_path,
                            task_id="WS-01",
                            operation_id=f"review-{verdict.lower()}-{mutation}",
                            expected_revision=1,
                            source_revision="source",
                            review_path=review_path,
                            finding_ids=["F-1"] if verdict == "REWORK" else None,
                            reason="identity regression",
                        )

                    self.assertEqual(raised.exception.code, expected_code)
                    self.assertEqual(state_path.read_bytes(), before_state)
                    self.assertFalse((root / "events.jsonl").exists())


def _review_outcome_fixture(root: Path, *, verdict: str, mutation: str) -> tuple[Path, str]:
    state_path = root / "run.state.json"
    _parallel_state(state_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["tasks"] = [state["tasks"][0]]
    task = state["tasks"][0]
    task["status"] = "VERIFYING"
    task["attempt"] = 1

    result = {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "actor": "worker",
        "actorRunId": "worker-run",
        "itemOutcomes": [{"status": "COMPLETE"}],
        "changeSet": {"provider": "git-worktree-v1", "baselineSha": "source"},
        "commands": [],
    }
    if mutation == "missing-actor":
        result.pop("actor")
    elif mutation == "empty-actor":
        result["actor"] = ""
    elif mutation == "missing-actor-run":
        result.pop("actorRunId")
    elif mutation == "empty-actor-run":
        result["actorRunId"] = ""
    result_path = "work/WS-01/attempt-1/task-result.json"
    write_json_create(root / result_path, result)
    task["result"] = {
        "path": result_path,
        "sha256": canonical_digest(result),
        "bytes": (root / result_path).stat().st_size,
    }

    review = {
        "schemaVersion": "agent-task-review.v2",
        "reviewId": "review-1",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": "0" * 64,
        "resultHash": canonical_digest(result),
        "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "test", "independent": True},
        "verdict": verdict,
        "findings": ([{"id": "F-1", "severity": "HIGH", "status": "open"}] if verdict == "REWORK" else []),
    }
    if verdict == "CONTRACT_CHANGE":
        review["contractChangeRequest"] = {"reason": "contract changed"}
    elif verdict == "BLOCKED":
        review["blocker"] = {"code": "external-blocker", "reason": "blocked"}
    if mutation == "same-actor":
        review["reviewer"]["id"] = "worker"
    elif mutation == "same-run":
        review["reviewer"]["runId"] = "worker-run"
    elif mutation == "missing-review-id":
        review.pop("reviewId")
    elif mutation == "empty-review-id":
        review["reviewId"] = ""
    review_path = "work/WS-01/attempt-1/task-review.json"
    write_json_create(root / review_path, review)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path, review_path


if __name__ == "__main__":
    unittest.main()
