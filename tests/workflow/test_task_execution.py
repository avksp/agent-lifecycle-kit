from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class WorkflowTaskExecutionTests(unittest.TestCase):
    def test_start_task_skips_occupied_attempt_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            occupied = root / "tasks/WS-01/attempt-1"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            review_path = "tasks/WS-01/attempt-1/task-review.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
            usage_path = "tasks/WS-01/attempt-1/model-usage-receipt.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
            usage_path = "tasks/WS-01/attempt-1/model-usage-receipt.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            review_path = "tasks/WS-01/attempt-1/task-review.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            review_path = "tasks/WS-01/attempt-1/task-review.json"
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
            result_path = "tasks/WS-01/attempt-1/task-result.json"
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
            review_path = "tasks/WS-01/attempt-1/task-review.json"
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


if __name__ == "__main__":
    unittest.main()
