"""Expired attempts retain honest results without becoming accepted work."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.workflow import accept_task, commit_task_result, start_task
from agent_lifecycle.workflow.task_outcomes import apply_task_review_outcome

from .helpers import _fresh_result, _initialize_managed_git_state, _review, _write_plan_bundle, _write_state


class IncompleteAttemptRecoveryTests(unittest.TestCase):
    def prepare(self, root: Path):
        _write_plan_bundle(root)
        state_path = _write_state(root, phase="RUNNING", max_attempts=3)
        revision = _initialize_managed_git_state(root, state_path, max_attempts=3)
        state = json.loads(state_path.read_text())
        manifest_path = "plans/package/plan.manifest.json"
        manifest = json.loads((root / manifest_path).read_text())
        lock_path = root / "plans/package/.agent-plan/package/plan.lock.json"
        index = json.loads((root / "plans/package/workflow/task-packets/index.json").read_text())
        state.update(schemaVersion="agent-workflow-state.v4", operationLedger={}, packageRoot=".",
                     runDeadlineAt="2020-01-02T00:00:00Z", manifestPath=manifest_path,
                     planRevision=manifest["planRevision"], planDigest=canonical_digest(manifest),
                     packetSet={"manifestDigest": index["manifestDigest"],
                                "packetSetHash": index["packetSetHash"],
                                "planLockSha256": hashlib.sha256(lock_path.read_bytes()).hexdigest()})
        task = state["tasks"][0]
        task.update(status="RUNNING", attempt=1, attemptBaseRevision=revision,
                    attemptStartedAt="2020-01-01T00:00:00Z", attemptDeadlineAt="2020-01-01T01:00:00Z",
                    usageTotals={"iterations": 1, "reportedTokens": 1234, "toolCalls": 2})
        state_path.write_text(json.dumps(state))
        (root / "src/example.py").write_text("value = 2\n")
        result = _fresh_result(root, state_path, attempt=1)
        result["planDigest"] = state["planDigest"]
        result["itemOutcomes"][0]["status"] = "INCOMPLETE"
        result["summary"] = "Attempt expired; partial changes retained, acceptance not established."
        result["blocker"] = {"code": "ATTEMPT_DEADLINE_EXPIRED", "reason": "Original deadline expired",
                             "scope": "task", "recoveryRoute": "task-review", "taskId": "WS-01", "attempt": 1}
        return state_path, revision, result

    def review(self, result):
        review = _review(attempt=1, result_hash=canonical_digest(result))
        review["planDigest"] = result["planDigest"]
        return review

    def commit(self, root, path, revision, result):
        result_path = "work/WS-01/attempt-1/task-result.json"
        write_json_create(root / result_path, result)
        return commit_task_result(path, task_id="WS-01", operation_id="record-incomplete", expected_revision=1,
                                  source_revision=revision, result_path=result_path, reason="Preserve expired attempt")

    def test_incomplete_result_can_be_reviewed_and_blocked_without_clock_or_cost_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, revision, result = self.prepare(root)
            before = json.loads(path.read_text())
            self.commit(root, path, revision, result)
            committed = json.loads(path.read_text())
            self.assertEqual(committed["tasks"][0]["status"], "VERIFYING")
            review = self.review(result)
            review.update(verdict="BLOCKED", blocker=result["blocker"], summary="Incomplete attempt is blocked")
            write_json_create(root / "work/WS-01/attempt-1/task-review.json", review)
            apply_task_review_outcome(path, task_id="WS-01", operation_id="block-incomplete", expected_revision=2,
                                      source_revision=revision, review_path="work/WS-01/attempt-1/task-review.json",
                                      reason="Retain incomplete result")
            after = json.loads(path.read_text())
            self.assertEqual(after["tasks"][0]["status"], "BLOCKED")
            self.assertEqual(after["tasks"][0]["attempt"], 1)
            self.assertEqual(after["runDeadlineAt"], before["runDeadlineAt"])
            for key in ["attemptStartedAt", "attemptDeadlineAt", "attemptHistory", "usageTotals"]:
                self.assertEqual(after["tasks"][0][key], before["tasks"][0][key])
            self.assertEqual(after["budgets"], before["budgets"])
            self.assertEqual(after["tasks"][0]["result"]["sha256"], canonical_digest(result))

    def test_non_accepting_failed_command_is_retained_but_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, revision, result = self.prepare(root)
            result["commands"] = [{"id": "affected-check", "status": "FAIL", "exitCode": 1}]
            self.commit(root, path, revision, result)
            write_json_create(root / "work/WS-01/attempt-1/task-review.json",
                              self.review(result))
            before = path.read_bytes()
            with self.assertRaises(LifecycleError) as raised:
                accept_task(path, task_id="WS-01", operation_id="invalid-accept", expected_revision=2,
                            review_path="work/WS-01/attempt-1/task-review.json", reason="must refuse")
            self.assertEqual(raised.exception.code, "task-result-not-acceptable")
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_or_missing_recovery_marker_never_commits(self):
        variants = {
            "no-marker": lambda r: r.update(blocker=None),
            "empty-blocker": lambda r: r.update(blocker={}),
            "scalar-blocker": lambda r: r.update(blocker="blocked"),
            "wrong-task": lambda r: r["blocker"].update(taskId="other"),
            "wrong-attempt": lambda r: r["blocker"].update(attempt=2),
            "bad-route": lambda r: r["blocker"].update(recoveryRoute="continue"),
            "two-markers": lambda r: r.update(contractChangeRequest={"reason": "change"}),
            "empty-contract": lambda r: r.update(blocker=None, contractChangeRequest={}),
            "scalar-contract": lambda r: r.update(blocker=None, contractChangeRequest="change"),
            "scalar-item": lambda r: r.update(itemOutcomes=[None]),
            "unknown-status": lambda r: r["itemOutcomes"][0].update(status="ACCEPTED"),
            "structured-status": lambda r: r["itemOutcomes"][0].update(status=[]),
            "wrong-result-attempt": lambda r: r.update(attempt=2),
            "wrong-packet": lambda r: r.update(taskPacketHash="f" * 64),
            "missing-actor": lambda r: r.pop("actor"),
        }
        for name, mutate in variants.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, revision, result = self.prepare(root)
                mutate(result)
                before = path.read_bytes()
                with self.assertRaises(LifecycleError):
                    self.commit(root, path, revision, result)
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse((root / "events.jsonl").exists())

    def test_contract_change_can_preserve_incomplete_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, revision, result = self.prepare(root)
            result.update(blocker=None, contractChangeRequest={"reason": "Missing contract guarantee"})
            self.commit(root, path, revision, result)
            self.assertEqual(json.loads(path.read_text())["tasks"][0]["status"], "VERIFYING")

    def test_rework_archives_incomplete_attempt_and_starts_next_without_run_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, revision, result = self.prepare(root)
            original = json.loads(path.read_text())
            self.commit(root, path, revision, result)
            finding = {"id": "DEADLINE-01", "severity": "HIGH", "status": "open", "title": "Incomplete evidence"}
            review = self.review(result)
            review.update(verdict="REWORK", findings=[finding], summary="Resume only missing proof in next attempt")
            write_json_create(root / "work/WS-01/attempt-1/task-review.json", review)
            apply_task_review_outcome(path, task_id="WS-01", operation_id="rework-incomplete", expected_revision=2,
                                      source_revision=revision, review_path="work/WS-01/attempt-1/task-review.json",
                                      finding_ids=["DEADLINE-01"], reason="Preserve attempt and request rework")
            archived = json.loads(path.read_text())
            task = archived["tasks"][0]
            self.assertEqual(task["status"], "REWORK")
            self.assertEqual(task["attemptHistory"][0]["result"]["sha256"], canonical_digest(result))
            self.assertEqual(task["attemptHistory"][0]["attemptDeadlineAt"],
                             original["tasks"][0]["attemptDeadlineAt"])
            self.assertEqual(task["attemptHistory"][0]["attemptStartedAt"],
                             original["tasks"][0]["attemptStartedAt"])
            self.assertEqual(task["attemptHistory"][0]["usageTotals"], original["tasks"][0]["usageTotals"])
            start_task(path, task_id="WS-01", operation_id="start-next", expected_revision=3,
                       source_revision=revision, reason="Separate remediation attempt")
            new_state = json.loads(path.read_text())
            self.assertEqual(new_state["tasks"][0]["attempt"], 2)
            self.assertEqual(new_state["runDeadlineAt"], original["runDeadlineAt"])
            self.assertEqual(new_state["runStartedAt"], original["runStartedAt"])
            self.assertEqual(new_state["tasks"][0]["usageTotals"], original["tasks"][0]["usageTotals"])
            self.assertEqual(new_state["tasks"][0]["attemptHistory"], task["attemptHistory"])
            self.assertEqual((root / "work/WS-01/attempt-1/task-result.json").read_text(),
                             json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")

    def test_incomplete_results_keep_actual_change_set_freshness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, revision, result = self.prepare(root)
            (root / "src/example.py").write_text("value = 3\n")
            before = path.read_bytes()
            with self.assertRaises(LifecycleError):
                self.commit(root, path, revision, result)
            self.assertEqual(path.read_bytes(), before)

    def test_complete_accepting_result_still_requires_successful_commands(self):
        for commands in [[], [{"status": "FAIL", "exitCode": 1}], [None]]:
            with self.subTest(commands=commands), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path, revision, result = self.prepare(root)
                result["blocker"] = None
                result["itemOutcomes"][0]["status"] = "COMPLETE"
                result["commands"] = deepcopy(commands)
                before = path.read_bytes()
                if not commands:
                    self.commit(root, path, revision, result)
                    self.assertEqual(json.loads(path.read_text())["tasks"][0]["status"], "VERIFYING")
                else:
                    with self.assertRaises(LifecycleError):
                        self.commit(root, path, revision, result)
                    self.assertEqual(path.read_bytes(), before)

    def test_legacy_incomplete_result_remains_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path, revision, result = self.prepare(root)
            state = json.loads(path.read_text())
            state["schemaVersion"] = "agent-workflow-state.v3"
            path.write_text(json.dumps(state))
            before = path.read_bytes()
            with self.assertRaises(LifecycleError) as raised:
                self.commit(root, path, revision, result)
            self.assertEqual(raised.exception.code, "task-result-not-acceptable")
            self.assertEqual(path.read_bytes(), before)
