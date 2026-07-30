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

class WorkflowBudgetDecisionTests(unittest.TestCase):
    def test_budget_overrun_pauses_for_manual_decision_and_writes_receipt(self) -> None:
        # NEG-R04-04 Budget Overrun Accepted
        # NEG-R04-05 Manual Mode Starts Invocation Before Operator Decision
        # NEG-R04-10 Decision Receipt Lineage Drift
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
            usage_path = "work/WS-01/attempt-1/model-usage-receipt.json"
            receipt = _model_usage_receipt(route)
            receipt["usage"]["billableTokens"] = route["maxBillableTokens"] + 1
            write_json_create(root / usage_path, receipt)
            policy_path = "budget-policy.json"
            write_json_create(root / policy_path, _budget_policy(mode="manual"))

            payload = pause_for_budget_decision(
                state_path,
                task_id="WS-01",
                operation_id="budget-op",
                expected_revision=2,
                source_revision="source",
                usage_receipt_path=usage_path,
                budget_policy_path=policy_path,
                decision_receipt_path="work/WS-01/attempt-1/budget-decision.json",
                reason="budget overrun",
            )

            self.assertEqual(payload["phase"], "WAITING_FOR_BUDGET_DECISION")
            self.assertEqual(payload["nextAction"]["type"], "record-budget-decision")
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "WAITING_FOR_BUDGET_DECISION")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["blocker"]["code"], "BUDGET_DECISION_REQUIRED")
            decision = json.loads((root / "work/WS-01/attempt-1/budget-decision.json").read_text(encoding="utf-8"))
            self.assertEqual(decision["schemaVersion"], "agent-lifecycle-budget-decision-receipt.v1")
            self.assertEqual(decision["selectedAction"], "await-operator")
            self.assertEqual(decision["priorRouteDecisionDigest"], route["decisionDigest"])
            self.assertEqual(decision["usageReceiptDigest"], canonical_digest(receipt))

    def test_budget_decision_apply_continue_same_route_resumes_running_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING")
            policy = _budget_policy(mode="manual")
            policy["allowedActions"].insert(0, "continue-same-route")
            _pause_budget_overrun(root, state_path, policy=policy)
            cap_deltas_path = "work/WS-01/attempt-1/cap-deltas.json"
            write_json_create(root / cap_deltas_path, {"maxBillableTokens": 240000})

            payload = apply_budget_decision(
                state_path,
                task_id="WS-01",
                operation_id="budget-apply-op",
                expected_revision=3,
                source_revision="source",
                decision_receipt_path="work/WS-01/attempt-1/budget-decision.json",
                action="continue-same-route",
                applied_receipt_path="work/WS-01/attempt-1/budget-decision-applied.json",
                cap_deltas_path=cap_deltas_path,
                operator_identity_hash="operator-hash",
                reason="operator approved cap increase",
            )

            self.assertEqual(payload["phase"], "RUNNING")
            self.assertIsNone(payload["blocker"])
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "RUNNING")
            applied = json.loads((root / "work/WS-01/attempt-1/budget-decision-applied.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["selectedAction"], "continue-same-route")
            self.assertEqual(applied["operatorIdentityHash"], "operator-hash")
            self.assertEqual(applied["capDeltas"], {"maxBillableTokens": 240000})

    def test_budget_decision_apply_reroute_stronger_sets_task_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            _pause_budget_overrun(root, state_path)
            next_route = _model_route()
            next_route["operationId"] = "route-WS-01-reroute"
            next_route["modelClass"] = "strong-reasoning"
            next_route["decisionDigest"] = "8" * 64
            route_path = "routes/WS-01-reroute.json"
            write_json_create(root / route_path, next_route)

            payload = apply_budget_decision(
                state_path,
                task_id="WS-01",
                operation_id="budget-reroute-op",
                expected_revision=3,
                source_revision="source",
                decision_receipt_path="work/WS-01/attempt-1/budget-decision.json",
                action="reroute-stronger",
                applied_receipt_path="work/WS-01/attempt-1/budget-decision-applied.json",
                route_decision_path=route_path,
                operator_identity_hash="operator-hash",
                reason="operator selected stronger route",
            )

            self.assertEqual(payload["phase"], "RUNNING")
            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "READY")
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["modelRoute"]["modelClass"], "strong-reasoning")
            self.assertNotIn("attemptModelRoute", stored_task)
            applied = json.loads((root / "work/WS-01/attempt-1/budget-decision-applied.json").read_text(encoding="utf-8"))
            self.assertEqual(applied["nextRouteDecisionDigest"], "8" * 64)
            self.assertEqual(applied["nextRouteDecision"]["path"], route_path)

    def test_budget_decision_apply_rejects_critical_review_cheaper_downgrade(self) -> None:
        # NEG-R04-03 Critical Downgrade Auto
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_state(root, phase="RUNNING", max_attempts=2)
            route = _model_route()
            route["criticalReview"] = True
            route["modelClass"] = "strong-reasoning"
            _pause_budget_overrun(root, state_path, route=route)
            cheaper = _model_route()
            cheaper["operationId"] = "route-WS-01-cheaper"
            cheaper["modelClass"] = "budget"
            cheaper["decisionDigest"] = "9" * 64
            route_path = "routes/WS-01-cheaper.json"
            write_json_create(root / route_path, cheaper)

            with self.assertRaises(LifecycleError) as raised:
                apply_budget_decision(
                    state_path,
                    task_id="WS-01",
                    operation_id="budget-cheaper-op",
                    expected_revision=3,
                    source_revision="source",
                    decision_receipt_path="work/WS-01/attempt-1/budget-decision.json",
                    action="reroute-cheaper",
                    applied_receipt_path="work/WS-01/attempt-1/budget-decision-applied.json",
                    route_decision_path=route_path,
                    operator_identity_hash="operator-hash",
                    reason="unsafe downgrade",
                )

            self.assertEqual(raised.exception.code, "budget-critical-downgrade")

    def test_budget_policy_validates_metered_subscription_and_local_caps(self) -> None:
        policy = _budget_policy(mode="manual")
        result = validate_budget_exceeded_policy(policy)
        self.assertEqual(result["status"], "PASS")

    def test_subscription_budget_policy_requires_max_invocations(self) -> None:
        # NEG-R04-07 Subscription Missing Max Invocations
        policy = _budget_policy(mode="manual")
        del policy["budgetModes"]["subscription"]["maxInvocations"]
        with self.assertRaises(LifecycleError) as raised:
            validate_budget_exceeded_policy(policy)
        self.assertEqual(raised.exception.code, "invalid-budget-policy")

    def test_subscription_and_local_budget_policy_require_token_or_wall_cap(self) -> None:
        # NEG-R04-08 Subscription Local Missing Resource Cap
        policy = _budget_policy(mode="manual")
        policy["budgetModes"]["subscription"].pop("maxBillableTokens")
        policy["budgetModes"]["subscription"].pop("maxWallSeconds")
        with self.assertRaises(LifecycleError) as raised:
            validate_budget_exceeded_policy(policy)
        self.assertEqual(raised.exception.code, "invalid-budget-policy")

    def test_metered_budget_policy_requires_usd_cap(self) -> None:
        # NEG-R04-09 Metered Missing USD Cap
        policy = _budget_policy(mode="manual")
        del policy["budgetModes"]["metered"]["budgetCapUsd"]
        with self.assertRaises(LifecycleError) as raised:
            validate_budget_exceeded_policy(policy)
        self.assertEqual(raised.exception.code, "invalid-budget-policy")

    def test_auto_budget_policy_respects_max_reroutes(self) -> None:
        # NEG-R04-06 Auto Policy Exceeds Max Reroutes
        policy = _budget_policy(mode="auto")
        task = {"budgetAutoReroutes": 1}
        with self.assertRaises(LifecycleError) as raised:
            select_auto_budget_action(policy, task=task, route_decision=_model_route())
        self.assertEqual(raised.exception.code, "budget-auto-reroute-limit")

    def test_auto_budget_policy_rejects_critical_review_cheaper_downgrade(self) -> None:
        policy = _budget_policy(mode="auto")
        route = _model_route()
        route["criticalReview"] = True
        route["modelClass"] = "strong-reasoning"
        action = select_auto_budget_action(policy, task={}, route_decision=route)
        self.assertEqual(action, "reroute-stronger")


if __name__ == "__main__":
    unittest.main()
