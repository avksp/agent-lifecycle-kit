"""Budget-overrun pause, decision, and resume helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.budget_policy import (
    ALLOWED_BUDGET_ACTIONS,
    select_auto_budget_action,
    validate_budget_exceeded_policy,
)
from agent_lifecycle.workflow.budget_receipts import (
    build_budget_decision_receipt,
    route_digest,
)
from agent_lifecycle.workflow.model_usage import (
    UNSAFE_CRITICAL_REVIEW_CLASSES,
    validate_attempt_model_route,
    validate_task_model_usage_receipt,
)
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import validate_typed_blocker


def pause_for_budget_decision(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    usage_receipt_path: str,
    budget_policy_path: str,
    decision_receipt_path: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] != "RUNNING":
        raise LifecycleError("invalid-phase", "budget decision pause requires RUNNING phase")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    task = find_task(state, task_id)
    if task.get("status") != "RUNNING":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not RUNNING")
    route = _attempt_route(task)
    if route is None:
        raise LifecycleError("budget-decision-not-required", "task has no model route")

    root = package_root(state_path, state)
    usage_rel = normalize_repo_path(usage_receipt_path, label="model usage receipt")
    receipt = read_json_object(root / usage_rel, label="model usage receipt")
    usage_identity = artifact_identity(root, usage_rel, receipt)
    validation = validate_task_model_usage_receipt(state, task, receipt, fail_on_invalid=False)
    if validation["status"] != "FAIL" or not _has_budget_failure(validation):
        raise LifecycleError("budget-decision-not-required", "model usage receipt did not fail a budget guard")

    policy_rel = normalize_repo_path(budget_policy_path, label="budget policy")
    policy = read_json_object(root / policy_rel, label="budget policy")
    policy_validation = validate_budget_exceeded_policy(policy)
    action = (
        "await-operator"
        if policy_validation["mode"] == "manual"
        else select_auto_budget_action(policy, task=task, route_decision=route)
    )

    decision_rel = normalize_repo_path(decision_receipt_path, label="budget decision receipt")
    decision = build_budget_decision_receipt(
        state=state,
        task=task,
        route_decision=route,
        usage_receipt=receipt,
        usage_identity=usage_identity,
        policy=policy,
        selected_action=action,
        validation=validation,
        expected_workflow_revision=state["stateRevision"] + 1,
    )
    write_json_create(root / decision_rel, decision)
    decision_identity = artifact_identity(root, decision_rel, decision)
    task["status"] = "WAITING_FOR_BUDGET_DECISION"
    task["budgetDecision"] = {
        **decision_identity,
        "selectedAction": action,
        "decisionMode": policy_validation["mode"],
        "usageReceipt": usage_identity,
        "usageValidation": validation,
    }
    budget_blocker = {
        "code": "BUDGET_DECISION_REQUIRED",
        "reason": reason,
        "scope": "task",
        "recoveryRoute": "budget-decision",
        "resumePhase": "RUNNING",
        "taskId": task_id,
        "attempt": task.get("attempt"),
        "allowedActions": policy["allowedActions"],
        "decisionReceiptTarget": decision_rel,
        "decisionReceipt": decision_identity,
    }
    validate_typed_blocker(budget_blocker, expected_task_id=task_id)
    task["blocker"] = dict(budget_blocker)
    if policy_validation["mode"] == "auto":
        task["budgetAutoReroutes"] = int(task.get("budgetAutoReroutes", 0)) + 1
    state["phase"] = "WAITING_FOR_BUDGET_DECISION"
    state["blocker"] = budget_blocker
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="budget-decision-required",
        payload={"taskId": task_id, "attempt": task.get("attempt"), "decisionReceipt": decision_identity},
    )
    return status(state_path)


def apply_budget_decision(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    decision_receipt_path: str,
    action: str,
    applied_receipt_path: str,
    route_decision_path: str | None = None,
    split_packet_path: str | None = None,
    cap_deltas_path: str | None = None,
    operator_identity_hash: str | None = None,
    reason: str,
) -> dict[str, Any]:
    if action not in ALLOWED_BUDGET_ACTIONS:
        raise LifecycleError("invalid-budget-action", "unsupported budget decision action", {"action": action})
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] != "WAITING_FOR_BUDGET_DECISION":
        raise LifecycleError("invalid-phase", "budget decision apply requires WAITING_FOR_BUDGET_DECISION phase")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    task = find_task(state, task_id)
    if task.get("status") != "WAITING_FOR_BUDGET_DECISION":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not waiting for a budget decision")
    blocker = _budget_blocker(state, task)
    root = package_root(state_path, state)
    pending_rel = normalize_repo_path(decision_receipt_path, label="budget decision receipt")
    pending = read_json_object(root / pending_rel, label="budget decision receipt")
    pending_identity = artifact_identity(root, pending_rel, pending)
    _validate_pending_decision(state, task, pending, action)

    next_route, next_route_identity = _read_next_route(root, route_decision_path, action, task)
    split_identity = _read_split_packet(root, split_packet_path, action)
    cap_deltas = _read_cap_deltas(root, cap_deltas_path, action)
    _require_operator_identity(pending, operator_identity_hash)

    receipt_rel = normalize_repo_path(applied_receipt_path, label="applied budget decision receipt")
    applied = build_budget_decision_receipt(
        state=state,
        task=task,
        route_decision=_attempt_route(task) or {},
        usage_receipt={"identity": pending.get("usageReceiptDigest")},
        usage_identity=dict(pending["usageReceipt"]),
        policy={"mode": pending["decisionMode"], "allowedActions": pending["allowedActions"]},
        selected_action=action,
        validation={"checks": [{"id": pending["overrunReason"], "status": "FAIL"}]},
        expected_workflow_revision=state["stateRevision"] + 1,
        operator_identity_hash=operator_identity_hash,
        prior_route_digest=str(pending["priorRouteDecisionDigest"]),
        usage_receipt_digest=str(pending["usageReceiptDigest"]),
        policy_digest=str(pending["policyDigest"]),
        overrun_reason=str(pending["overrunReason"]),
        next_route_decision=next_route,
        next_route_identity=next_route_identity,
        split_packet_identity=split_identity,
        cap_deltas=cap_deltas,
    )
    applied["pendingDecisionReceipt"] = pending_identity
    write_json_create(root / receipt_rel, applied)
    applied_identity = artifact_identity(root, receipt_rel, applied)
    _apply_action(
        state,
        task,
        action=action,
        next_route=next_route,
        split_identity=split_identity,
        applied_identity=applied_identity,
        pending_identity=pending_identity,
        reason=reason,
    )
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="budget-decision-applied",
        payload={
            "taskId": task_id,
            "attempt": task.get("attempt"),
            "action": action,
            "previousBlocker": blocker,
            "decisionReceipt": applied_identity,
        },
    )
    return status(state_path)


def _apply_action(
    state: dict[str, Any],
    task: dict[str, Any],
    *,
    action: str,
    next_route: dict[str, Any] | None,
    split_identity: dict[str, Any] | None,
    applied_identity: dict[str, Any],
    pending_identity: dict[str, Any],
    reason: str,
) -> None:
    task["budgetDecisionApplied"] = {
        **applied_identity,
        "selectedAction": action,
        "pendingDecisionReceipt": pending_identity,
        "reason": reason,
    }
    task["lastReason"] = reason
    if action == "continue-same-route":
        task["status"] = "RUNNING"
        state["phase"] = "RUNNING"
        state["blocker"] = None
        task.pop("blocker", None)
        return
    if action in {"reroute-cheaper", "reroute-stronger"}:
        assert next_route is not None
        task["modelRoute"] = next_route
        task.pop("attemptModelRoute", None)
        task["status"] = "READY"
        state["phase"] = "RUNNING"
        state["blocker"] = None
        task.pop("blocker", None)
        return
    task["status"] = "BLOCKED"
    code = "BUDGET_SPLIT_REQUIRED" if action == "split-task" else "BUDGET_ABORTED"
    recovery_route = "replan-task" if action == "split-task" else "cancel-run"
    blocker = {
        "code": code,
        "reason": reason,
        "scope": "task",
        "recoveryRoute": recovery_route,
        "taskId": task["id"],
        "attempt": task.get("attempt"),
        "selectedAction": action,
        "decisionReceipt": applied_identity,
        "splitPacketIdentity": split_identity,
    }
    validate_typed_blocker(blocker, expected_task_id=str(task["id"]))
    task["blocker"] = dict(blocker)
    state["blocker"] = blocker
    state["phase"] = "BLOCKED" if action == "split-task" else "CANCELLED"


def _budget_blocker(state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    blocker = state.get("blocker")
    if not isinstance(blocker, dict) or blocker.get("code") != "BUDGET_DECISION_REQUIRED":
        raise LifecycleError("budget-decision-not-required", "run is not blocked on a budget decision")
    if blocker.get("taskId") != task["id"] or blocker.get("attempt") != task.get("attempt"):
        raise LifecycleError("budget-decision-lineage-mismatch", "budget blocker does not match task attempt")
    return dict(blocker)


def _validate_pending_decision(
    state: dict[str, Any],
    task: dict[str, Any],
    receipt: dict[str, Any],
    action: str,
) -> None:
    if receipt.get("schemaVersion") != "agent-lifecycle-budget-decision-receipt.v1":
        raise LifecycleError("invalid-budget-decision-receipt", "unsupported budget decision receipt schema")
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "sourceRevision": state.get("sourceRevision"),
        "expectedWorkflowRevision": state.get("stateRevision"),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LifecycleError("budget-decision-lineage-mismatch", f"budget decision receipt {key} mismatch")
    if action not in receipt.get("allowedActions", []):
        raise LifecycleError("budget-action-not-allowed", "budget decision action is not allowed", {"action": action})
    selected = receipt.get("selectedAction")
    if receipt.get("decisionMode") == "manual" and selected != "await-operator":
        raise LifecycleError("invalid-budget-decision-receipt", "manual pending receipt must await operator action")
    if receipt.get("decisionMode") == "auto" and selected != action:
        raise LifecycleError("budget-action-mismatch", "auto budget decision must apply the selected action")
    prior_route = _attempt_route(task)
    if prior_route is not None and receipt.get("priorRouteDecisionDigest") != route_digest(prior_route):
        raise LifecycleError("budget-decision-lineage-mismatch", "prior route decision digest mismatch")


def _read_next_route(
    root: Path,
    route_decision_path: str | None,
    action: str,
    task: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if action not in {"reroute-cheaper", "reroute-stronger"}:
        if route_decision_path is not None:
            raise LifecycleError("unexpected-route-decision", "route decision is only valid for reroute actions")
        return None, None
    if route_decision_path is None:
        raise LifecycleError("route-decision-required", "reroute actions require --route-decision")
    route_rel = normalize_repo_path(route_decision_path, label="route decision")
    route = read_json_object(root / route_rel, label="route decision")
    if route.get("schemaVersion") != "agent-lifecycle-model-route-decision.v1":
        raise LifecycleError("invalid-model-route", "route decision schema is unsupported")
    if not isinstance(route.get("modelClass"), str) or not route["modelClass"]:
        raise LifecycleError("invalid-model-route", "route decision modelClass is required")
    _require_critical_safety(task, route, action)
    candidate = {**task, "modelRoute": route}
    validate_attempt_model_route(candidate)
    return route, artifact_identity(root, route_rel, route)


def _read_split_packet(root: Path, split_packet_path: str | None, action: str) -> dict[str, Any] | None:
    if action != "split-task":
        if split_packet_path is not None:
            raise LifecycleError("unexpected-split-packet", "split packet is only valid for split-task")
        return None
    if split_packet_path is None:
        raise LifecycleError("split-packet-required", "split-task requires --split-packet")
    packet_rel = normalize_repo_path(split_packet_path, label="split packet")
    packet = read_json_object(root / packet_rel, label="split packet")
    return artifact_identity(root, packet_rel, packet)


def _read_cap_deltas(root: Path, cap_deltas_path: str | None, action: str) -> dict[str, Any]:
    if action == "continue-same-route" and cap_deltas_path is None:
        raise LifecycleError("cap-deltas-required", "continue-same-route requires explicit cap deltas")
    if cap_deltas_path is None:
        return {}
    deltas_rel = normalize_repo_path(cap_deltas_path, label="cap deltas")
    deltas = read_json_object(root / deltas_rel, label="cap deltas")
    if not isinstance(deltas, dict):
        raise LifecycleError("invalid-cap-deltas", "cap deltas must be an object")
    return deltas


def _require_operator_identity(receipt: dict[str, Any], operator_identity_hash: str | None) -> None:
    if receipt.get("decisionMode") != "manual":
        return
    if not isinstance(operator_identity_hash, str) or not operator_identity_hash:
        raise LifecycleError("operator-identity-required", "manual budget decision requires operator identity hash")


def _require_critical_safety(task: dict[str, Any], next_route: dict[str, Any], action: str) -> None:
    prior = _attempt_route(task) or {}
    if prior.get("criticalReview") is not True:
        return
    next_class = str(next_route.get("modelClass", ""))
    if action == "reroute-cheaper" or next_class in UNSAFE_CRITICAL_REVIEW_CLASSES:
        raise LifecycleError(
            "budget-critical-downgrade",
            "critical review route cannot be rerouted to a cheaper or compact class",
            {"modelClass": next_class},
        )


def _attempt_route(task: dict[str, Any]) -> dict[str, Any] | None:
    route = task.get("attemptModelRoute")
    if isinstance(route, dict) and route:
        return route
    route = task.get("modelRoute")
    if isinstance(route, dict) and route:
        return route
    return None


def _has_budget_failure(validation: dict[str, Any]) -> bool:
    for check in validation.get("checks", []):
        if not isinstance(check, dict) or check.get("status") != "FAIL":
            continue
        check_id = str(check.get("id", ""))
        if check_id == "route-max-billable-tokens" or check_id.startswith("hard-ceiling-"):
            return True
    return False
