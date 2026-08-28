"""Projection-first facade over authoritative workflow transitions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import package_root
from agent_lifecycle.workflow.authorization import authorize_execution
from agent_lifecycle.workflow.final_proof_integrity import proof_integrity_required
from agent_lifecycle.workflow.finalization import apply_final_audit_outcome, finalize_run
from agent_lifecycle.workflow.implementation_audit_gate import (
    final_implementation_audit_required,
    task_implementation_audit_required,
)
from agent_lifecycle.workflow.model_usage import model_usage_receipt_required
from agent_lifecycle.workflow.next_action import build_managed_next_action
from agent_lifecycle.workflow.plan_adoption import start_execution
from agent_lifecycle.workflow.review_mesh_gate import review_mesh_required
from agent_lifecycle.workflow.run import run_workflow_step
from agent_lifecycle.workflow.state import load_state, state_identity
from agent_lifecycle.workflow.task_outcomes import apply_task_review_outcome
from agent_lifecycle.workflow.task_transitions import commit_task_result, start_task
from agent_lifecycle.workflow.transition_contract import ACTION_TYPES

MODEL_CALLS_STARTED = False
MAX_INPUT_LIST_ITEMS = 128

_PATH_INPUTS = {
    "authorizationReceipt",
    "riskProfile",
    "result",
    "modelUsageReceipt",
    "budgetTargets",
    "review",
    "implementationAudit",
    "finalAudit",
    "proof",
    "proofIntegrity",
    "goalRecord",
    "followUpRegister",
    "completionGateReceipt",
    "finalImplementationAudit",
}
_LIST_INPUTS = {"findingIds", "taskIds", "reviewMeshQuorum"}
_DEFERRED_AUDIT_BLOCKER_CODES = {
    "implementation-audit-required",
    "security-analysis-verification-required",
}


def continue_workflow(
    *,
    state_path: Path,
    manifest_path: Path,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
    lock_path: Path | None = None,
    apply: bool = False,
    projected_state_revision: int | None = None,
    projected_action_digest: str | None = None,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project or apply one current workflow transition without inventing authority."""

    try:
        normalized_inputs = _normalize_inputs(inputs or {})
    except LifecycleError as exc:
        return _blocked_receipt(operation_id, apply=apply, exc=exc)
    preflight = _run_preflight(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        reason=reason,
    )
    try:
        preflight = _recover_audit_input_preflight(preflight, state_path)
    except LifecycleError as exc:
        return _blocked_from_preflight(preflight, operation_id, apply=apply, exc=exc)
    if preflight["status"] != "PASS":
        return _receipt(
            status="BLOCKED",
            operation_id=operation_id,
            apply=apply,
            state_before=preflight.get("state"),
            plan=preflight.get("plan"),
            next_action=preflight.get("nextAction"),
            blockers=list(preflight.get("blockers", [])),
        )
    try:
        state = _load_preflight_state(state_path, preflight)
        route = _project_route(state_path, state, preflight["nextAction"], normalized_inputs)
        action = _build_action(preflight, route, normalized_inputs, operation_id)
        required = _required_inputs(state_path, state, route, normalized_inputs)
    except LifecycleError as exc:
        return _blocked_from_preflight(preflight, operation_id, apply=apply, exc=exc)
    if not apply:
        return _projection_receipt(preflight, operation_id, route, action, required)
    return _apply_projected_route(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        preflight=preflight,
        route=route,
        action=action,
        required=required,
        inputs=normalized_inputs,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        reason=reason,
        projected_state_revision=projected_state_revision,
        projected_action_digest=projected_action_digest,
    )


def _apply_projected_route(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path | None,
    preflight: dict[str, Any],
    route: dict[str, Any],
    action: dict[str, Any],
    required: list[dict[str, Any]],
    inputs: dict[str, Any],
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
    projected_state_revision: int | None,
    projected_action_digest: str | None,
) -> dict[str, Any]:
    guard_requirements = _apply_guard_requirements(projected_state_revision, projected_action_digest)
    if guard_requirements:
        return _input_required_receipt(preflight, operation_id, action, [*guard_requirements, *required], apply=True)
    guard_blocker = _apply_guard_blocker(
        action,
        projected_state_revision=projected_state_revision,
        projected_action_digest=projected_action_digest,
    )
    if guard_blocker is not None:
        return _receipt(
            status="BLOCKED",
            operation_id=operation_id,
            apply=True,
            state_before=preflight["state"],
            plan=preflight["plan"],
            action=action,
            required_inputs=required,
            next_action=preflight["nextAction"],
            blockers=[guard_blocker],
        )
    if required:
        return _input_required_receipt(preflight, operation_id, action, required, apply=True)
    if route["transition"] is None:
        return _non_mutating_receipt(preflight, operation_id, route, action)
    return _apply_transition(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        preflight=preflight,
        route=route,
        action=action,
        inputs=inputs,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        reason=reason,
    )


def _run_preflight(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path | None,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
) -> dict[str, Any]:
    return run_workflow_step(
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        operation_id=operation_id,
        expected_revision=expected_revision,
        source_revision=source_revision,
        reason=reason,
    )


def _recover_audit_input_preflight(preflight: dict[str, Any], state_path: Path) -> dict[str, Any]:
    """Expose an audit-required accept route without weakening its transition gate."""

    if preflight.get("status") == "PASS":
        return preflight
    blockers = preflight.get("blockers")
    if not isinstance(blockers, list) or not blockers:
        return preflight
    if any(not isinstance(item, dict) or item.get("code") not in _DEFERRED_AUDIT_BLOCKER_CODES for item in blockers):
        return preflight
    state = _load_preflight_state(state_path, preflight)
    next_action = build_managed_next_action(state)
    if next_action.get("type") != "accept-task":
        return preflight
    candidates = {item for item in next_action.get("taskIds", []) if isinstance(item, str)}
    blocked_tasks = {str(item.get("taskId")) for item in blockers if item.get("taskId")}
    if not blocked_tasks or not blocked_tasks.issubset(candidates):
        return preflight
    return {**preflight, "status": "PASS", "nextAction": next_action, "blockers": []}


def _load_preflight_state(state_path: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    state = load_state(state_path)
    projected = preflight.get("state")
    expected_revision = projected.get("stateRevision") if isinstance(projected, dict) else None
    if state.get("stateRevision") != expected_revision:
        raise LifecycleError(
            "continuation-state-changed",
            "workflow state changed while continuation was being projected",
            {"expected": expected_revision, "actual": state.get("stateRevision")},
        )
    return state


def _project_route(
    state_path: Path,
    state: dict[str, Any],
    next_action: dict[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    action_type = next_action.get("type")
    if action_type not in ACTION_TYPES:
        raise LifecycleError("continuation-action-unsupported", "projected workflow action is unsupported")
    mapping: dict[str, tuple[str, Callable[..., dict[str, Any]] | None]] = {
        "request-execution-authorization": ("authorize", authorize_execution),
        "start-execution": ("run-start", start_execution),
        "launch-tasks": ("task-start", start_task),
        "wait-for-active-tasks": ("task-result", commit_task_result),
        "accept-task": ("task-review-apply", apply_task_review_outcome),
        "final-audit-outcome": ("final-audit-outcome", apply_final_audit_outcome),
        "finalize-run": ("finalize", finalize_run),
    }
    route_name, transition = mapping.get(action_type, (action_type, None))
    candidates = [item for item in next_action.get("taskIds", []) if isinstance(item, str)]
    task_id = _select_task(candidates, inputs.get("taskId"))
    return {
        "name": route_name,
        "managedActionType": action_type,
        "transition": transition,
        "taskId": task_id,
        "taskCandidates": candidates,
        "statePath": state_path.as_posix(),
        "phase": state.get("phase"),
    }


def _select_task(candidates: list[str], supplied: Any) -> str | None:
    if supplied is not None and (not isinstance(supplied, str) or not supplied):
        raise LifecycleError("continuation-task-invalid", "taskId must be a non-empty string")
    if supplied is not None and supplied not in candidates:
        raise LifecycleError(
            "continuation-task-ineligible",
            "selected task is not eligible for the projected action",
            {"taskId": supplied, "eligibleTaskIds": candidates},
        )
    if isinstance(supplied, str):
        return supplied
    return candidates[0] if len(candidates) == 1 else None


def _build_action(
    preflight: dict[str, Any],
    route: dict[str, Any],
    inputs: dict[str, Any],
    operation_id: str,
) -> dict[str, Any]:
    state = preflight["state"]
    plan = preflight["plan"]
    body = {
        "schemaVersion": "agent-workflow-continuation-action.v1",
        "route": route["name"],
        "managedActionType": route["managedActionType"],
        "stateRevision": state["stateRevision"],
        "planDigest": plan["planDigest"],
        "sourceRevision": preflight["sourceRevision"],
        "operationId": operation_id,
        "taskId": route["taskId"],
        "suppliedInputs": inputs,
        "managedActionDigest": preflight["nextAction"]["actionDigest"],
    }
    return {**body, "actionDigest": canonical_digest(body)}


def _required_inputs(
    state_path: Path,
    state: dict[str, Any],
    route: dict[str, Any],
    inputs: dict[str, Any],
) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    if route["transition"] is not None and len(route["taskCandidates"]) > 1 and route["taskId"] is None:
        required.append(_required("taskId", "--task", "select one eligible task"))
    route_name = route["name"]
    if route_name == "authorize":
        _append_missing(required, inputs, "authorizationReceipt", "--authorization-receipt")
    elif route_name == "task-result":
        _append_missing(required, inputs, "result", "--result")
        task = _task(state, route["taskId"])
        if task is not None and model_usage_receipt_required(task):
            _append_missing(required, inputs, "modelUsageReceipt", "--model-usage-receipt")
    elif route_name == "task-review-apply":
        _append_missing(required, inputs, "review", "--review")
        task = _task(state, route["taskId"])
        if task is not None and task_implementation_audit_required(state_path, state, task):
            _append_missing(required, inputs, "implementationAudit", "--implementation-audit")
        review = _read_supplied_document(state_path, state, inputs, "review", "task review")
        if isinstance(review, dict) and review.get("verdict") == "REWORK":
            _append_missing(required, inputs, "findingIds", "--finding-id")
    elif route_name == "final-audit-outcome":
        _append_missing(required, inputs, "finalAudit", "--final-audit")
        _append_missing(required, inputs, "verdict", "--verdict")
        if inputs.get("verdict") == "REWORK":
            _append_missing(required, inputs, "taskIds", "--task-id")
            _append_missing(required, inputs, "findingIds", "--finding-id")
    elif route_name == "finalize":
        _append_missing(required, inputs, "finalAudit", "--final-audit")
        _append_missing(required, inputs, "proof", "--proof")
        final_audit = _read_supplied_document(state_path, state, inputs, "finalAudit", "final audit")
        if proof_integrity_required(state, final_audit):
            _append_missing(required, inputs, "proofIntegrity", "--proof-integrity")
        if final_implementation_audit_required(state_path, state):
            _append_missing(required, inputs, "finalImplementationAudit", "--final-implementation-audit")
        review_mesh = state.get("reviewMesh") if isinstance(state.get("reviewMesh"), dict) else None
        if review_mesh_required(review_mesh, phase="final-audit"):
            _append_missing(required, inputs, "reviewMeshQuorum", "--review-mesh-quorum")
    return required


def _read_supplied_document(
    state_path: Path,
    state: dict[str, Any],
    inputs: dict[str, Any],
    name: str,
    label: str,
) -> dict[str, Any] | None:
    path = inputs.get(name)
    if not isinstance(path, str):
        return None
    return read_json_object(package_root(state_path, state) / path, label=label)


def _append_missing(required: list[dict[str, Any]], inputs: dict[str, Any], name: str, option: str) -> None:
    if inputs.get(name) is None:
        required.append(_required(name, option, f"{name} is required for this transition"))


def _required(name: str, option: str | None, reason: str) -> dict[str, Any]:
    return {"name": name, "option": option, "reason": reason}


def _task(state: dict[str, Any], task_id: str | None) -> dict[str, Any] | None:
    if task_id is None:
        return None
    return next((task for task in state.get("tasks", []) if task.get("id") == task_id), None)


def _normalize_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(inputs).difference(_PATH_INPUTS | _LIST_INPUTS | {"taskId", "verdict"}))
    if unknown:
        raise LifecycleError("continuation-input-unsupported", "continuation input is unsupported", {"fields": unknown})
    normalized: dict[str, Any] = {}
    for key, value in sorted(inputs.items()):
        if value is None:
            continue
        if key in _PATH_INPUTS:
            if not isinstance(value, str):
                raise LifecycleError("continuation-input-invalid", f"{key} must be a repository-relative path")
            normalized[key] = normalize_repo_path(value, label=key)
        elif key in _LIST_INPUTS:
            normalized[key] = _string_list(value, key)
        elif not isinstance(value, str) or not value:
            raise LifecycleError("continuation-input-invalid", f"{key} must be a non-empty string")
        else:
            normalized[key] = value
    return normalized


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_INPUT_LIST_ITEMS:
        raise LifecycleError("continuation-input-invalid", f"{field} must be a bounded string list")
    if any(not isinstance(item, str) or not item for item in value):
        raise LifecycleError("continuation-input-invalid", f"{field} must contain non-empty strings")
    return sorted(set(value))


def _apply_guard_requirements(state_revision: int | None, action_digest: str | None) -> list[dict[str, Any]]:
    required: list[dict[str, Any]] = []
    if state_revision is None:
        required.append(_required("projectedStateRevision", "--projected-state-revision", "bind apply to a projection"))
    if action_digest is None:
        required.append(_required("projectedActionDigest", "--projected-action-digest", "bind apply to a projection"))
    return required


def _apply_guard_blocker(
    action: dict[str, Any],
    *,
    projected_state_revision: int | None,
    projected_action_digest: str | None,
) -> dict[str, Any] | None:
    if projected_state_revision != action["stateRevision"]:
        return {
            "code": "continuation-projection-state-mismatch",
            "message": "apply state revision does not match the current projection",
            "context": {"expected": action["stateRevision"], "provided": projected_state_revision},
        }
    if projected_action_digest != action["actionDigest"]:
        return {
            "code": "continuation-projection-action-mismatch",
            "message": "apply action digest does not match the current projection",
        }
    return None


def _projection_receipt(
    preflight: dict[str, Any],
    operation_id: str,
    route: dict[str, Any],
    action: dict[str, Any],
    required: list[dict[str, Any]],
) -> dict[str, Any]:
    if required:
        status = "WAITING" if route["name"] in {"task-result", "run-final-audit"} else "INPUT_REQUIRED"
    elif route["transition"] is None:
        status = "BLOCKED" if route["managedActionType"] in {"blocked", "none", "request-human-decision"} else "WAITING"
    else:
        status = "READY"
    return _receipt(
        status=status,
        operation_id=operation_id,
        apply=False,
        state_before=preflight["state"],
        plan=preflight["plan"],
        action=action,
        required_inputs=required,
        next_action=preflight["nextAction"],
        blockers=[] if status != "BLOCKED" else _non_mutating_blockers(preflight, route),
    )


def _input_required_receipt(
    preflight: dict[str, Any],
    operation_id: str,
    action: dict[str, Any],
    required: list[dict[str, Any]],
    *,
    apply: bool,
) -> dict[str, Any]:
    return _receipt(
        status="INPUT_REQUIRED",
        operation_id=operation_id,
        apply=apply,
        state_before=preflight["state"],
        plan=preflight["plan"],
        action=action,
        required_inputs=required,
        next_action=preflight["nextAction"],
    )


def _non_mutating_receipt(
    preflight: dict[str, Any],
    operation_id: str,
    route: dict[str, Any],
    action: dict[str, Any],
) -> dict[str, Any]:
    status = "BLOCKED" if route["managedActionType"] in {"blocked", "none", "request-human-decision"} else "WAITING"
    return _receipt(
        status=status,
        operation_id=operation_id,
        apply=True,
        state_before=preflight["state"],
        plan=preflight["plan"],
        action=action,
        next_action=preflight["nextAction"],
        blockers=[] if status != "BLOCKED" else _non_mutating_blockers(preflight, route),
    )


def _non_mutating_blockers(preflight: dict[str, Any], route: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = list(preflight["nextAction"].get("blockers", []))
    if blockers:
        return blockers
    projected = preflight["nextAction"].get("projectedAction")
    reason = projected.get("reason") if isinstance(projected, dict) else None
    return [
        {
            "code": "continuation-route-non-mutating",
            "message": "the current workflow action cannot be applied by continuation",
            "context": {"route": route["name"], "reason": reason},
        }
    ]


def _apply_transition(
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path | None,
    preflight: dict[str, Any],
    route: dict[str, Any],
    action: dict[str, Any],
    inputs: dict[str, Any],
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
) -> dict[str, Any]:
    try:
        _dispatch_transition(
            route,
            state_path=state_path,
            operation_id=operation_id,
            expected_revision=expected_revision,
            source_revision=source_revision,
            reason=reason,
            inputs=inputs,
        )
        after = load_state(state_path)
        if after["stateRevision"] != expected_revision + 1:
            raise LifecycleError(
                "continuation-transition-count-invalid", "continuation must commit exactly one transition"
            )
        postflight = run_workflow_step(
            state_path=state_path,
            manifest_path=manifest_path,
            lock_path=lock_path,
            operation_id=f"{operation_id}:next",
            expected_revision=after["stateRevision"],
            source_revision=source_revision,
            reason=reason,
        )
    except LifecycleError as exc:
        return _blocked_from_preflight(preflight, operation_id, apply=True, exc=exc, action=action)
    ledger = after.get("operationLedger", {}).get(operation_id)
    event = {"operationId": operation_id, **ledger} if isinstance(ledger, dict) else None
    return _receipt(
        status="APPLIED",
        operation_id=operation_id,
        apply=True,
        state_before=preflight["state"],
        state_after=state_identity(state_path, after),
        plan=preflight["plan"],
        action=action,
        next_action=postflight.get("nextAction"),
        applied_event=event,
        state_written=True,
        blockers=list(postflight.get("blockers", [])),
    )


def _dispatch_transition(
    route: dict[str, Any],
    *,
    state_path: Path,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
    inputs: dict[str, Any],
) -> None:
    common = {
        "state_path": state_path,
        "operation_id": operation_id,
        "expected_revision": expected_revision,
        "source_revision": source_revision,
        "reason": reason,
    }
    name = route["name"]
    if name == "authorize":
        authorize_execution(**common, receipt_path=inputs["authorizationReceipt"])
    elif name == "run-start":
        start_execution(**common)
    elif name == "task-start":
        start_task(**common, task_id=route["taskId"], risk_profile_path=inputs.get("riskProfile"))
    elif name == "task-result":
        commit_task_result(
            **common,
            task_id=route["taskId"],
            result_path=inputs["result"],
            model_usage_receipt_path=inputs.get("modelUsageReceipt"),
            budget_targets_path=inputs.get("budgetTargets"),
        )
    elif name == "task-review-apply":
        apply_task_review_outcome(
            **common,
            task_id=route["taskId"],
            review_path=inputs["review"],
            finding_ids=inputs.get("findingIds"),
            implementation_audit_path=inputs.get("implementationAudit"),
        )
    elif name == "final-audit-outcome":
        apply_final_audit_outcome(
            **common,
            final_audit_path=inputs["finalAudit"],
            verdict=inputs["verdict"],
            task_ids=inputs.get("taskIds"),
            finding_ids=inputs.get("findingIds"),
        )
    elif name == "finalize":
        finalize_run(
            **common,
            final_audit_path=inputs["finalAudit"],
            proof_path=inputs["proof"],
            proof_integrity_path=inputs.get("proofIntegrity"),
            goal_record_path=inputs.get("goalRecord"),
            follow_up_register_path=inputs.get("followUpRegister"),
            completion_gate_receipt_path=inputs.get("completionGateReceipt"),
            final_implementation_audit_path=inputs.get("finalImplementationAudit"),
            review_mesh_quorum_paths=inputs.get("reviewMeshQuorum"),
        )
    else:
        raise LifecycleError("continuation-route-not-applicable", "projected action has no continuation transition")


def _blocked_receipt(operation_id: str, *, apply: bool, exc: LifecycleError) -> dict[str, Any]:
    return _receipt(status="BLOCKED", operation_id=operation_id, apply=apply, blockers=[_blocker(exc)])


def _blocked_from_preflight(
    preflight: dict[str, Any],
    operation_id: str,
    *,
    apply: bool,
    exc: LifecycleError,
    action: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _receipt(
        status="BLOCKED",
        operation_id=operation_id,
        apply=apply,
        state_before=preflight.get("state"),
        plan=preflight.get("plan"),
        action=action,
        next_action=preflight.get("nextAction"),
        blockers=[_blocker(exc)],
    )


def _blocker(exc: LifecycleError) -> dict[str, Any]:
    blocker: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        blocker["context"] = exc.details
    return blocker


def _receipt(
    *,
    status: str,
    operation_id: str,
    apply: bool,
    state_before: dict[str, Any] | None = None,
    state_after: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
    action: dict[str, Any] | None = None,
    required_inputs: list[dict[str, Any]] | None = None,
    next_action: dict[str, Any] | None = None,
    applied_event: dict[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
    state_written: bool = False,
) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-workflow-continuation-receipt.v1",
        "status": status,
        "mode": "APPLY" if apply else "PROJECT",
        "operationId": operation_id,
        "stateBefore": state_before,
        "stateAfter": state_after,
        "plan": plan,
        "action": action,
        "requiredInputs": required_inputs or [],
        "nextAction": next_action,
        "appliedEvent": applied_event,
        "blockers": blockers or [],
        "modelCallsStarted": MODEL_CALLS_STARTED,
        "stateWritten": state_written,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


__all__ = ["continue_workflow"]
