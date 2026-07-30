from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402

class CliWorkflowCommandTests(unittest.TestCase):
    def test_workflow_status_outputs_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_state(Path(tmp))
            code, payload = _run_cli(["workflow", "status", "--state", str(state_path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-workflow-status.v1")
            self.assertEqual(payload["nextAction"]["type"], "launch-tasks")

    def test_workflow_task_lifecycle_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-start",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "start-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "launch",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "RUNNING")

            result_path = "work/WS-01/attempt-1/task-result.json"
            result = _result()
            write_json_create(root / result_path, result)
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--result",
                    result_path,
                    "--reason",
                    "done",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "VERIFYING")

            review_path = "work/WS-01/attempt-1/task-review.json"
            write_json_create(root / review_path, _review(canonical_digest(result)))
            code, payload = _run_cli(
                [
                    "workflow",
                    "task-accept",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "accept-op",
                    "--expected-revision",
                    "3",
                    "--review",
                    review_path,
                    "--reason",
                    "accepted",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "ACCEPTED")

    def test_workflow_task_result_cli_accepts_model_usage_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            route = _model_route()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["modelRoute"] = route
            state_path.write_text(json.dumps(state), encoding="utf-8")
            code, _payload = _run_cli(
                [
                    "workflow",
                    "task-start",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "start-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "launch",
                ]
            )
            self.assertEqual(code, 0)
            result_path = "work/WS-01/attempt-1/task-result.json"
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            write_json_create(root / result_path, _result())
            write_json_create(root / usage_path, _model_usage_receipt(route))

            code, payload = _run_cli(
                [
                    "workflow",
                    "task-result",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "result-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--result",
                    result_path,
                    "--model-usage-receipt",
                    usage_path,
                    "--reason",
                    "done",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_task(payload)["status"], "VERIFYING")

    def test_workflow_budget_policy_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "budget-policy.json"
            policy_path.write_text(json.dumps(_budget_policy()), encoding="utf-8")

            code, payload = _run_cli(["workflow", "budget-policy-check", "--policy", str(policy_path)])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-budget-exceeded-policy-validation.v1")
            self.assertEqual(payload["status"], "PASS")

    def test_workflow_budget_decision_cli_pauses_overrun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            route = _model_route()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["modelRoute"] = route
            state_path.write_text(json.dumps(state), encoding="utf-8")
            code, _payload = _run_cli(
                [
                    "workflow",
                    "task-start",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "start-op",
                    "--expected-revision",
                    "1",
                    "--source-revision",
                    "source",
                    "--reason",
                    "launch",
                ]
            )
            self.assertEqual(code, 0)
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            receipt = _model_usage_receipt(route)
            receipt["usage"]["billableTokens"] = route["maxBillableTokens"] + 1
            write_json_create(root / usage_path, receipt)
            policy_path = "budget-policy.json"
            write_json_create(root / policy_path, _budget_policy())

            code, payload = _run_cli(
                [
                    "workflow",
                    "budget-decision",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "budget-op",
                    "--expected-revision",
                    "2",
                    "--source-revision",
                    "source",
                    "--model-usage-receipt",
                    usage_path,
                    "--budget-policy",
                    policy_path,
                    "--receipt",
                    "work/WS-01/attempt-1/budget-decision.json",
                    "--reason",
                    "operator decision required",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "WAITING_FOR_BUDGET_DECISION")
            self.assertEqual(payload["nextAction"]["type"], "record-budget-decision")
            self.assertTrue((root / "work/WS-01/attempt-1/budget-decision.json").is_file())

    def test_workflow_budget_decision_cli_applies_reroute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root)
            route = _model_route()
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["tasks"][0]["modelRoute"] = route
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(
                _run_cli(
                    [
                        "workflow",
                        "task-start",
                        "--state",
                        str(state_path),
                        "--task",
                        "WS-01",
                        "--operation-id",
                        "start-op",
                        "--expected-revision",
                        "1",
                        "--source-revision",
                        "source",
                        "--reason",
                        "launch",
                    ]
                )[0],
                0,
            )
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            receipt = _model_usage_receipt(route)
            receipt["usage"]["billableTokens"] = route["maxBillableTokens"] + 1
            write_json_create(root / usage_path, receipt)
            policy_path = "budget-policy.json"
            write_json_create(root / policy_path, _budget_policy())
            self.assertEqual(
                _run_cli(
                    [
                        "workflow",
                        "budget-decision",
                        "--state",
                        str(state_path),
                        "--task",
                        "WS-01",
                        "--operation-id",
                        "budget-op",
                        "--expected-revision",
                        "2",
                        "--source-revision",
                        "source",
                        "--model-usage-receipt",
                        usage_path,
                        "--budget-policy",
                        policy_path,
                        "--receipt",
                        "work/WS-01/attempt-1/budget-decision.json",
                        "--reason",
                        "operator decision required",
                    ]
                )[0],
                0,
            )
            reroute = _model_route()
            reroute["operationId"] = "route-WS-01-reroute"
            reroute["modelClass"] = "strong-reasoning"
            reroute["decisionDigest"] = "8" * 64
            route_path = "routes/WS-01-reroute.json"
            write_json_create(root / route_path, reroute)

            code, payload = _run_cli(
                [
                    "workflow",
                    "budget-decision",
                    "--state",
                    str(state_path),
                    "--task",
                    "WS-01",
                    "--operation-id",
                    "budget-apply-op",
                    "--expected-revision",
                    "3",
                    "--source-revision",
                    "source",
                    "--action",
                    "reroute-stronger",
                    "--decision-receipt",
                    "work/WS-01/attempt-1/budget-decision.json",
                    "--route-decision",
                    route_path,
                    "--receipt",
                    "work/WS-01/attempt-1/budget-decision-applied.json",
                    "--operator-identity-hash",
                    "operator-hash",
                    "--reason",
                    "operator selected stronger route",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(_task(payload)["status"], "READY")
            applied = json.loads((root / "work/WS-01/attempt-1/budget-decision-applied.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["selectedAction"], "reroute-stronger")
            self.assertEqual(applied["nextRouteDecisionDigest"], "8" * 64)


if __name__ == "__main__":
    unittest.main()
