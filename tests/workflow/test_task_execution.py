from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

from agent_lifecycle.cli import main  # noqa: E402


def _prepare_rework_review(
    root: Path,
    *,
    max_attempts: int = 2,
    occupy_first: bool = False,
    reviewer_id: str = "reviewer",
    finding_ids: tuple[str, ...] = ("F-REWORK-1",),
) -> tuple[Path, str]:
    state_path = _write_state(root, phase="RUNNING", max_attempts=max_attempts)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["budgets"]["remediationMode"] = "ask"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    if occupy_first:
        occupied = root / "work/WS-01/attempt-1/task-result.json"
        occupied.parent.mkdir(parents=True)
        occupied.write_text("{}", encoding="utf-8")
    start_task(
        state_path,
        task_id="WS-01",
        operation_id="start-prepare",
        expected_revision=1,
        source_revision="source",
        reason="prepare rework",
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    attempt = state["tasks"][0]["attempt"]
    result_path = f"work/WS-01/attempt-{attempt}/task-result.json"
    result = _result(attempt=attempt)
    write_json_create(root / result_path, result)
    commit_task_result(
        state_path,
        task_id="WS-01",
        operation_id="result-prepare",
        expected_revision=2,
        source_revision="source",
        result_path=result_path,
        reason="prepare result",
    )
    review_path = f"work/WS-01/attempt-{attempt}/task-review.json"
    review = _review(attempt=attempt, result_hash=canonical_digest(result))
    review["verdict"] = "REWORK"
    review["reviewer"]["id"] = reviewer_id
    review["findings"] = [
        {"id": finding_id, "severity": "HIGH", "status": "open", "message": "revise implementation"}
        for finding_id in finding_ids
    ]
    write_json_create(root / review_path, review)
    return state_path, review_path


class WorkflowTaskExecutionTests(unittest.TestCase):
    def test_start_task_rejects_non_integer_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["budgets"]["maxTaskAttempts"] = "2"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-invalid-budget",
                    expected_revision=1,
                    source_revision="source",
                    reason="launch",
                )

            self.assertEqual(raised.exception.code, "task-attempt-budget-invalid")

    def test_start_task_skips_occupied_attempt_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            occupied = root / "work/WS-01/attempt-1"
            occupied.mkdir(parents=True)
            (occupied / "task-result.json").write_text("{}", encoding="utf-8")
            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "RUNNING")
            self.assertEqual(task["attempt"], 2)

    def test_start_task_requires_pre_launch_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            _add_gate(state_path, _gate("G-PRE", ["pre-launch"]))
            with self.assertRaises(LifecycleError):
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-op",
                    expected_revision=1,
                    source_revision="source",
                    reason="launch",
                )

    def test_start_task_records_pre_launch_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            gate = _gate("G-PRE", ["pre-launch"])
            _add_gate(state_path, gate)
            _write_gate_receipt(root, gate, phase="pre-launch", operation_id="start-op", attempt=1)
            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "RUNNING")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["attemptBaseRevision"], "source")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            stored = next(item for item in state["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored["controllerGateReceipts"][0]["gateId"], "G-PRE")

    def test_start_task_accepts_state_level_gate_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            gate = _gate("G-PRE", ["pre-launch"])
            gate["dependsOnGateIds"] = ["G-AUTH"]
            _add_gate(state_path, gate)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["controllerGateReceipts"] = [{"gateId": "G-AUTH", "path": "gates/auth.json"}]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            _write_gate_receipt(root, gate, phase="pre-launch", operation_id="start-op", attempt=1)

            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "RUNNING")

    def test_commit_result_requires_post_attempt_gate_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            _add_gate(state_path, _gate("G-POST", ["post-attempt"]))
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            write_json_create(root / result_path, _result(attempt=1))
            with self.assertRaises(LifecycleError):
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    reason="done",
                )

    def test_commit_result_requires_complete_worker_identity_before_state_change(self) -> None:
        mutations = (
            ("actor", None),
            ("actor", ""),
            ("actorRunId", None),
            ("actorRunId", ""),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = _write_state(root, phase="RUNNING")
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-op",
                    expected_revision=1,
                    source_revision="source",
                    reason="launch",
                )
                result = _result(attempt=1)
                if value is None:
                    result.pop(field)
                else:
                    result[field] = value
                result_path = "work/WS-01/attempt-1/task-result.json"
                write_json_create(root / result_path, result)
                before_state = state_path.read_bytes()
                before_events = (root / "events.jsonl").read_bytes()

                with self.assertRaises(LifecycleError) as raised:
                    commit_task_result(
                        state_path,
                        task_id="WS-01",
                        operation_id=f"result-{field}-{value!r}",
                        expected_revision=2,
                        source_revision="source",
                        result_path=result_path,
                        reason="done",
                    )

                self.assertEqual(raised.exception.code, "task-result-invalid")
                self.assertEqual(state_path.read_bytes(), before_state)
                self.assertEqual((root / "events.jsonl").read_bytes(), before_events)

    def test_task_accept_cli_rejects_missing_review_id_without_traceback_or_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-cli-review-id",
                expected_revision=1,
                source_revision="source",
                reason="prepare CLI review",
            )
            result = _result(attempt=1)
            result_path = "work/WS-01/attempt-1/task-result.json"
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-cli-review-id",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="prepare CLI review",
            )
            review = _review(attempt=1, result_hash=canonical_digest(result))
            review.pop("reviewId")
            review_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, review)
            before_state = state_path.read_bytes()
            before_events = (root / "events.jsonl").read_bytes()
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = main(
                    [
                        "workflow",
                        "task-accept",
                        "--state",
                        str(state_path),
                        "--task",
                        "WS-01",
                        "--operation-id",
                        "accept-cli-review-id",
                        "--expected-revision",
                        "3",
                        "--review",
                        review_path,
                        "--reason",
                        "reject incomplete review identity",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "task-review-invalid")
            self.assertNotIn("traceback", stdout.getvalue().lower())
            self.assertNotEqual(payload["code"], "cli-unexpected-error")
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual((root / "events.jsonl").read_bytes(), before_events)

    def test_commit_result_and_accept_review_unlocks_next_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            review_path = "work/WS-01/attempt-1/task-review.json"
            review = _review(attempt=1, result_hash=canonical_digest(result))
            write_json_create(root / review_path, review)
            payload = accept_task(
                state_path,
                task_id="WS-01",
                operation_id="accept-op",
                expected_revision=3,
                review_path=review_path,
                reason="accepted",
            )
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            self.assertEqual(payload["phase"], "FINAL_AUDIT")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["ownershipReceipt"]["status"], "PASS")

    def test_commit_result_requires_model_usage_receipt_for_model_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            _set_task_model_route(state_path, _model_route())
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            write_json_create(root / result_path, _result(attempt=1))

            with self.assertRaises(LifecycleError) as raised:
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "model-usage-receipt-required")

    def test_commit_result_records_valid_model_usage_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            route = _model_route()
            _set_task_model_route(state_path, route)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            result = _result(attempt=1)
            write_json_create(root / result_path, result)
            write_json_create(root / usage_path, _model_usage_receipt(route))

            payload = commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                model_usage_receipt_path=usage_path,
                reason="done",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "VERIFYING")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["modelUsageReceipt"]["modelClass"], "standard-code")
            self.assertEqual(stored_task["modelUsageReceipt"]["validation"]["status"], "PASS")

    def test_commit_result_rejects_model_usage_receipt_lineage_drift(self) -> None:
        # NEG-R03-08 Usage Receipt Drift
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            route = _model_route()
            _set_task_model_route(state_path, route)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            receipt = _model_usage_receipt(route)
            receipt["taskId"] = "WS-OTHER"
            write_json_create(root / result_path, _result(attempt=1))
            write_json_create(root / usage_path, receipt)

            with self.assertRaises(LifecycleError) as raised:
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    model_usage_receipt_path=usage_path,
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "model-usage-lineage-mismatch")

    def test_commit_result_rejects_stale_attempt_baseline_without_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            result["changeSet"]["baselineSha"] = "older-source"
            write_json_create(root / result_path, result)

            with self.assertRaises(LifecycleError) as raised:
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "task-result-stale-baseline")

    def test_commit_result_accepts_stale_attempt_baseline_with_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            result["changeSet"]["baselineSha"] = "older-source"
            result["reconciliationReceipt"] = {
                "schemaVersion": "agent-baseline-reconciliation-receipt.v1",
                "status": "PASS",
                "taskId": "WS-01",
                "attempt": 1,
                "expectedBaseRevision": "source",
                "actualBaseRevision": "older-source",
                "evidenceIds": ["EV-RECONCILIATION"],
            }
            write_json_create(root / result_path, result)

            payload = commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "VERIFYING")

    def test_commit_result_rejects_failed_command_as_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            result["commands"] = [{"id": "verify", "command": "python -m unittest", "exitCode": 1}]
            write_json_create(root / result_path, result)

            with self.assertRaises(LifecycleError) as raised:
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision="source",
                    result_path=result_path,
                    reason="done",
                )

            self.assertEqual(raised.exception.code, "task-result-failed-command")

    def test_accept_task_rejects_unowned_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            result["changedFiles"] = ["docs/out-of-scope.md"]
            result["itemOutcomes"][0]["changedFiles"] = ["docs/out-of-scope.md"]
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            review_path = "work/WS-01/attempt-1/task-review.json"
            review = _review(attempt=1, result_hash=canonical_digest(result))
            write_json_create(root / review_path, review)

            with self.assertRaises(LifecycleError) as raised:
                accept_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="accept-op",
                    expected_revision=3,
                    review_path=review_path,
                    reason="accepted",
                )

            self.assertEqual(raised.exception.code, "task-ownership-violation")

    def test_accept_task_rejects_forbidden_changed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["writePolicy"] = {"forbiddenWrites": [".git"], "readOnly": []}
            state["tasks"][0]["writes"] = ["src", ".git"]
            state_path.write_text(json.dumps(state), encoding="utf-8")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            result["changedFiles"] = [".git/config"]
            result["itemOutcomes"][0]["changedFiles"] = [".git/config"]
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            review_path = "work/WS-01/attempt-1/task-review.json"
            review = _review(attempt=1, result_hash=canonical_digest(result))
            write_json_create(root / review_path, review)

            with self.assertRaises(LifecycleError) as raised:
                accept_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="accept-op",
                    expected_revision=3,
                    review_path=review_path,
                    reason="accepted",
                )

            self.assertEqual(raised.exception.code, "task-ownership-violation")

    def test_accept_task_rejects_adopted_state_without_write_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["manifestPath"] = "plans/package/plan.manifest.json"
            state["packetSet"] = {"path": "plans/package/workflow/task-packets/index.json"}
            state["tasks"][0].pop("writes", None)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result(attempt=1)
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            review_path = "work/WS-01/attempt-1/task-review.json"
            review = _review(attempt=1, result_hash=canonical_digest(result))
            write_json_create(root / review_path, review)

            with self.assertRaises(LifecycleError) as raised:
                accept_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="accept-op",
                    expected_revision=3,
                    review_path=review_path,
                    reason="accepted",
                )

            self.assertEqual(raised.exception.code, "task-write-scope-missing")

    def test_start_task_rejects_critical_review_downgrade_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp), phase="RUNNING")
            route = _model_route()
            route["modelClass"] = "local-compact"
            route["criticalReview"] = True
            _set_task_model_route(state_path, route)

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-op",
                    expected_revision=1,
                    source_revision="source",
                    reason="launch",
                )

            self.assertEqual(raised.exception.code, "model-route-critical-downgrade")

    def test_rework_opens_second_fresh_attempt_and_preserves_first_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            source_revision = _initialize_managed_git_state(root, state_path)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-1",
                expected_revision=1,
                source_revision=source_revision,
                reason="first attempt",
            )
            (root / "src/example.py").write_text("value = 2\n", encoding="utf-8")
            result_1_path = "work/WS-01/attempt-1/task-result.json"
            result_1 = _fresh_result(root, state_path, attempt=1)
            write_json_create(root / result_1_path, result_1)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-1",
                expected_revision=2,
                source_revision=source_revision,
                result_path=result_1_path,
                reason="first result",
            )
            review_1_path = "work/WS-01/attempt-1/task-review.json"
            review_1 = _review(attempt=1, result_hash=canonical_digest(result_1))
            review_1["verdict"] = "REWORK"
            review_1["findings"] = [
                {"id": "F-REWORK-1", "severity": "HIGH", "status": "open", "message": "revise implementation"}
            ]
            write_json_create(root / review_1_path, review_1)
            result_1_bytes = (root / result_1_path).read_bytes()
            review_1_bytes = (root / review_1_path).read_bytes()

            rework_payload = rework_task(
                state_path,
                task_id="WS-01",
                operation_id="rework-1",
                expected_revision=3,
                source_revision=source_revision,
                review_path=review_1_path,
                finding_ids=["F-REWORK-1"],
                reason="independent review requested rework",
            )
            self.assertEqual(rework_payload["phase"], "REMEDIATING")
            self.assertEqual(rework_payload["nextAction"]["type"], "launch-tasks")
            with self.assertRaises(LifecycleError) as replayed:
                rework_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="rework-1",
                    expected_revision=4,
                    source_revision=source_revision,
                    review_path=review_1_path,
                    finding_ids=["F-REWORK-1"],
                    reason="duplicate",
                )
            self.assertEqual(replayed.exception.code, "duplicate-operation")
            replay_state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(replay_state["tasks"][0]["attemptHistory"]), 1)

            started = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-2",
                expected_revision=4,
                source_revision=source_revision,
                reason="second attempt",
            )
            self.assertEqual(next(item for item in started["tasks"] if item["id"] == "WS-01")["attempt"], 2)
            self.assertEqual((root / result_1_path).read_bytes(), result_1_bytes)
            self.assertEqual((root / review_1_path).read_bytes(), review_1_bytes)

            (root / "src/example.py").write_text("value = 3\n", encoding="utf-8")
            result_2_path = "work/WS-01/attempt-2/task-result.json"
            result_2 = _fresh_result(root, state_path, attempt=2)
            write_json_create(root / result_2_path, result_2)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-2",
                expected_revision=5,
                source_revision=source_revision,
                result_path=result_2_path,
                reason="fresh second result",
            )
            review_2_path = "work/WS-01/attempt-2/task-review.json"
            review_2 = _review(attempt=2, result_hash=canonical_digest(result_2))
            write_json_create(root / review_2_path, review_2)
            accepted = accept_task(
                state_path,
                task_id="WS-01",
                operation_id="accept-2",
                expected_revision=6,
                review_path=review_2_path,
                reason="accepted",
            )

            self.assertEqual(next(item for item in accepted["tasks"] if item["id"] == "WS-01")["status"], "ACCEPTED")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["tasks"][0]["attemptHistory"]), 1)
            history = state["tasks"][0]["attemptHistory"][0]
            self.assertEqual(history["runId"], state["runId"])
            self.assertEqual(history["taskId"], "WS-01")
            self.assertEqual(history["planRevision"], state["planRevision"])
            self.assertEqual(history["planDigest"], state["planDigest"])
            self.assertEqual(history["sourceRevision"], state["sourceRevision"])
            self.assertEqual(state["tasks"][0]["remediationFindingIds"], [])

    def test_rework_rejects_unknown_finding_without_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root)
            before_state = state_path.read_bytes()
            before_events = (root / "events.jsonl").read_bytes()

            with self.assertRaises(LifecycleError) as raised:
                rework_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="rework-mismatch",
                    expected_revision=3,
                    source_revision="source",
                    review_path=review_path,
                    finding_ids=["F-UNKNOWN"],
                    reason="invalid finding",
                )

            self.assertEqual(raised.exception.code, "task-rework-finding-mismatch")
            self.assertEqual(state_path.read_bytes(), before_state)
            self.assertEqual((root / "events.jsonl").read_bytes(), before_events)

    def test_rework_requires_every_open_finding_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(
                root,
                finding_ids=("F-REWORK-1", "F-REWORK-2"),
            )

            with self.assertRaises(LifecycleError) as raised:
                rework_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="rework-incomplete-findings",
                    expected_revision=3,
                    source_revision="source",
                    review_path=review_path,
                    finding_ids=["F-REWORK-1"],
                    reason="incomplete finding set",
                )

            self.assertEqual(raised.exception.code, "task-rework-finding-mismatch")
            self.assertEqual(raised.exception.details["omitted"], ["F-REWORK-2"])

    def test_rework_rejects_worker_self_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root, reviewer_id="worker")

            with self.assertRaises(LifecycleError) as raised:
                rework_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="rework-self-review",
                    expected_revision=3,
                    source_revision="source",
                    review_path=review_path,
                    finding_ids=["F-REWORK-1"],
                    reason="self review",
                )

            self.assertEqual(raised.exception.code, "task-review-self-certification")

    def test_rework_rejects_non_integer_task_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["attempt"] = "1"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                rework_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="rework-invalid-attempt",
                    expected_revision=3,
                    source_revision="source",
                    review_path=review_path,
                    finding_ids=["F-REWORK-1"],
                    reason="invalid attempt",
                )

            self.assertEqual(raised.exception.code, "task-attempt-history-invalid")

    def test_rework_rejects_exhausted_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root, occupy_first=True)

            with self.assertRaises(LifecycleError) as raised:
                rework_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="rework-exhausted",
                    expected_revision=3,
                    source_revision="source",
                    review_path=review_path,
                    finding_ids=["F-REWORK-1"],
                    reason="no attempts remain",
                )

            self.assertEqual(raised.exception.code, "task-attempt-budget-exhausted")

    def test_rework_rejects_active_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            sibling = {**state["tasks"][0], "id": "WS-02", "status": "RUNNING", "attemptHistory": []}
            state["tasks"].append(sibling)
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                rework_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="rework-sibling",
                    expected_revision=3,
                    source_revision="source",
                    review_path=review_path,
                    finding_ids=["F-REWORK-1"],
                    reason="sibling active",
                )

            self.assertEqual(raised.exception.code, "task-rework-active-sibling")

    def test_start_rework_attempt_rejects_tampered_history_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root)
            rework_task(
                state_path,
                task_id="WS-01",
                operation_id="rework-history",
                expected_revision=3,
                source_revision="source",
                review_path=review_path,
                finding_ids=["F-REWORK-1"],
                reason="rework",
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["attemptHistory"][0]["sourceRevision"] = "different-source"
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-after-tamper",
                    expected_revision=4,
                    source_revision="source",
                    reason="start",
                )

            self.assertEqual(raised.exception.code, "task-attempt-history-lineage-mismatch")

    def test_start_rework_attempt_rejects_nonconsecutive_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root)
            rework_task(
                state_path,
                task_id="WS-01",
                operation_id="rework-history-attempt",
                expected_revision=3,
                source_revision="source",
                review_path=review_path,
                finding_ids=["F-REWORK-1"],
                reason="rework",
            )
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["attemptHistory"][0]["attempt"] = 2
            state["tasks"][0]["attempt"] = 2
            state_path.write_text(json.dumps(state), encoding="utf-8")

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-after-history-gap",
                    expected_revision=4,
                    source_revision="source",
                    reason="start",
                )

            self.assertEqual(raised.exception.code, "task-attempt-history-invalid")

    def test_start_rework_attempt_rejects_changed_archived_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path, review_path = _prepare_rework_review(root)
            rework_task(
                state_path,
                task_id="WS-01",
                operation_id="rework-artifact",
                expected_revision=3,
                source_revision="source",
                review_path=review_path,
                finding_ids=["F-REWORK-1"],
                reason="rework",
            )
            with (root / review_path).open("ab") as stream:
                stream.write(b" ")

            with self.assertRaises(LifecycleError) as raised:
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="start-after-artifact-change",
                    expected_revision=4,
                    source_revision="source",
                    reason="start",
                )

            self.assertEqual(raised.exception.code, "archived-artifact-changed")

    def test_managed_task_result_rejects_snapshot_created_before_code_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            source_revision = _initialize_managed_git_state(root, state_path)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision=source_revision,
                reason="launch",
            )
            (root / "src/example.py").write_text("value = 2\n", encoding="utf-8")
            stale = _fresh_result(root, state_path, attempt=1)
            (root / "src/example.py").write_text("value = 3\n", encoding="utf-8")
            result_path = "work/WS-01/attempt-1/task-result.json"
            write_json_create(root / result_path, stale)

            with self.assertRaises(LifecycleError) as raised:
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id="result-op",
                    expected_revision=2,
                    source_revision=source_revision,
                    result_path=result_path,
                    reason="stale result",
                )

            self.assertEqual(raised.exception.code, "task-result-stale-snapshot")

    def test_managed_acceptance_allows_disjoint_changes_owned_by_another_plan_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            source_revision = _initialize_managed_git_state(root, state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"].append(
                {
                    **state["tasks"][0],
                    "id": "WS-00",
                    "status": "ACCEPTED",
                    "attempt": 1,
                    "writes": ["docs"],
                    "attemptHistory": [],
                }
            )
            state_path.write_text(json.dumps(state), encoding="utf-8")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-owned",
                expected_revision=1,
                source_revision=source_revision,
                reason="launch",
            )
            (root / "src/example.py").write_text("value = 2\n", encoding="utf-8")
            prior = root / "docs/prior-task.md"
            prior.parent.mkdir(parents=True)
            prior.write_text("accepted prior task\n", encoding="utf-8")
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _fresh_result(root, state_path, attempt=1)
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-owned",
                expected_revision=2,
                source_revision=source_revision,
                result_path=result_path,
                reason="done",
            )
            review_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, _review(attempt=1, result_hash=canonical_digest(result)))

            accepted = accept_task(
                state_path,
                task_id="WS-01",
                operation_id="accept-owned",
                expected_revision=3,
                review_path=review_path,
                reason="accepted",
            )

            self.assertEqual(next(item for item in accepted["tasks"] if item["id"] == "WS-01")["status"], "ACCEPTED")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            categories = {entry["path"]: entry["category"] for entry in task["ownershipReceipt"]["entries"]}
            self.assertEqual(categories["src/example.py"], "task-owned")
            self.assertEqual(categories["docs/prior-task.md"], "plan-owned")

    def test_managed_acceptance_allows_adopted_lead_owned_controller_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            source_revision = _initialize_managed_git_state(root, state_path)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["writePolicy"] = {
                "forbiddenWrites": [],
                "readOnly": [],
                "leadOwned": [
                    {"path": "plans/package", "reason": "plan authority"},
                    {"path": "runtime/package", "reason": "runtime evidence"},
                ],
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-lead-owned",
                expected_revision=1,
                source_revision=source_revision,
                reason="launch",
            )
            (root / "src/example.py").write_text("value = 2\n", encoding="utf-8")
            for path in (root / "plans/package/plan.md", root / "runtime/package/evidence.json"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("controller-owned\n", encoding="utf-8")
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _fresh_result(root, state_path, attempt=1)
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-lead-owned",
                expected_revision=2,
                source_revision=source_revision,
                result_path=result_path,
                reason="done",
            )
            review_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, _review(attempt=1, result_hash=canonical_digest(result)))

            accepted = accept_task(
                state_path,
                task_id="WS-01",
                operation_id="accept-lead-owned",
                expected_revision=3,
                review_path=review_path,
                reason="accepted",
            )

            self.assertEqual(next(item for item in accepted["tasks"] if item["id"] == "WS-01")["status"], "ACCEPTED")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            categories = {entry["path"]: entry["category"] for entry in task["ownershipReceipt"]["entries"]}
            self.assertEqual(categories["plans/package/plan.md"], "lead-owned")
            self.assertEqual(categories["runtime/package/evidence.json"], "lead-owned")
            self.assertEqual(task["writes"], ["src"])

    def test_managed_acceptance_keeps_blocking_policy_ahead_of_lead_owned(self) -> None:
        for policy_key, expected_category in (("forbiddenWrites", "forbidden"), ("readOnly", "read-only")):
            with self.subTest(policy_key=policy_key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                state_path = _write_state(root, phase="RUNNING", max_attempts=2)
                source_revision = _initialize_managed_git_state(root, state_path)
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["writePolicy"] = {
                    "forbiddenWrites": [],
                    "readOnly": [],
                    "leadOwned": [{"path": "controller", "reason": "controller authority"}],
                }
                state["writePolicy"][policy_key] = ["controller/protected"]
                state_path.write_text(json.dumps(state), encoding="utf-8")
                start_task(
                    state_path,
                    task_id="WS-01",
                    operation_id=f"start-{expected_category}",
                    expected_revision=1,
                    source_revision=source_revision,
                    reason="launch",
                )
                (root / "src/example.py").write_text("value = 2\n", encoding="utf-8")
                protected = root / "controller/protected/value.txt"
                protected.parent.mkdir(parents=True, exist_ok=True)
                protected.write_text("must block\n", encoding="utf-8")
                result_path = "work/WS-01/attempt-1/task-result.json"
                result = _fresh_result(root, state_path, attempt=1)
                write_json_create(root / result_path, result)
                commit_task_result(
                    state_path,
                    task_id="WS-01",
                    operation_id=f"result-{expected_category}",
                    expected_revision=2,
                    source_revision=source_revision,
                    result_path=result_path,
                    reason="done",
                )
                review_path = "work/WS-01/attempt-1/task-review.json"
                write_json_create(root / review_path, _review(attempt=1, result_hash=canonical_digest(result)))

                with self.assertRaises(LifecycleError) as raised:
                    accept_task(
                        state_path,
                        task_id="WS-01",
                        operation_id=f"accept-{expected_category}",
                        expected_revision=3,
                        review_path=review_path,
                        reason="accepted",
                    )

                self.assertEqual(raised.exception.code, "task-ownership-violation")
                entries = raised.exception.details["ownership"]["entries"]
                protected_entry = next(item for item in entries if item["path"] == "controller/protected/value.txt")
                self.assertEqual(protected_entry["category"], expected_category)

    def test_managed_acceptance_rejects_unowned_repository_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            source_revision = _initialize_managed_git_state(root, state_path)
            start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-unowned",
                expected_revision=1,
                source_revision=source_revision,
                reason="launch",
            )
            (root / "src/example.py").write_text("value = 2\n", encoding="utf-8")
            (root / "outside.txt").write_text("unowned\n", encoding="utf-8")
            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _fresh_result(root, state_path, attempt=1)
            write_json_create(root / result_path, result)
            commit_task_result(
                state_path,
                task_id="WS-01",
                operation_id="result-unowned",
                expected_revision=2,
                source_revision=source_revision,
                result_path=result_path,
                reason="done",
            )
            review_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, _review(attempt=1, result_hash=canonical_digest(result)))

            with self.assertRaises(LifecycleError) as raised:
                accept_task(
                    state_path,
                    task_id="WS-01",
                    operation_id="accept-unowned",
                    expected_revision=3,
                    review_path=review_path,
                    reason="accepted",
                )

            self.assertEqual(raised.exception.code, "task-ownership-violation")


if __name__ == "__main__":
    unittest.main()
