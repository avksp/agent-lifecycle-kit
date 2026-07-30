"""Provider-neutral controlled execution-loop state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.context.profiles import resolve_window, validate_context_profile
from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest, read_json_object
from agent_lifecycle.contracts.paths import is_under_repo_path, normalize_repo_path

RUNNER_PHASES = {
    "READY",
    "ATTEMPTING",
    "VALIDATING",
    "REVIEWING",
    "WAITING_REMEDIATION",
    "WAITING_REROUTE",
    "WAITING_SPLIT",
    "BLOCKED",
    "STOPPED",
    "COMPLETE",
    "ABORTED",
}
TERMINAL_PHASES = {"COMPLETE", "ABORTED"}
TRANSITION_ACTIONS = {
    "attempt",
    "validate",
    "review",
    "accept",
    "remediate",
    "reroute",
    "split",
    "block",
    "abort",
}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "READY": {"attempt", "block", "abort"},
    "WAITING_REMEDIATION": {"attempt", "block", "abort"},
    "WAITING_REROUTE": {"attempt", "block", "abort"},
    "WAITING_SPLIT": {"block", "abort"},
    "ATTEMPTING": {"validate", "reroute", "block", "abort"},
    "VALIDATING": {"review", "remediate", "reroute", "block", "abort"},
    "REVIEWING": {"accept", "remediate", "reroute", "split", "block", "abort"},
    "BLOCKED": {"abort"},
    "STOPPED": {"resume"},
}
RESULT_PHASE_BY_ACTION = {
    "attempt": "ATTEMPTING",
    "validate": "VALIDATING",
    "review": "REVIEWING",
    "accept": "COMPLETE",
    "remediate": "WAITING_REMEDIATION",
    "reroute": "WAITING_REROUTE",
    "split": "WAITING_SPLIT",
    "block": "BLOCKED",
    "abort": "ABORTED",
}
LINEAGE_KEYS = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")
DEFAULT_POLICY = {
    "schemaVersion": "agent-runner-policy.v1",
    "maxAttemptsPerTask": 2,
    "maxReroutesPerTask": 1,
    "maxSplitsPerTask": 1,
    "maxBillableTokens": 120000,
}


def load_runner_policy(path: Path | None) -> dict[str, Any]:
    policy = DEFAULT_POLICY if path is None else read_json_object(path, label="runner policy")
    return _validate_policy(dict(policy))


def initialize_runner_state(
    workflow_state: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    operation_id: str,
    reason: str,
) -> dict[str, Any]:
    policy = _validate_policy(dict(policy or DEFAULT_POLICY))
    task_id = _first_ready_task(workflow_state)
    body = {
        "schemaVersion": "agent-runner-state.v1",
        "runnerRevision": 1,
        "status": "READY",
        "currentTaskId": task_id,
        "lineage": _lineage_from_workflow(workflow_state),
        "policy": policy,
        "counters": {
            "attemptsByTask": {},
            "reroutesByTask": {},
            "splitsByTask": {},
            "billableTokens": 0,
        },
        "history": [
            {
                "operationId": operation_id,
                "action": "initialize",
                "fromStatus": None,
                "toStatus": "READY",
                "taskId": task_id,
                "reason": reason,
                "recordedAt": _now_iso(),
            }
        ],
        "operations": {operation_id: {"action": "initialize", "runnerRevision": 1}},
    }
    validate_runner_state(body, workflow_state=workflow_state)
    return {**body, "stateDigest": _state_digest(body)}


def load_runner_state(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="runner state")


def validate_runner_state(
    state: dict[str, Any],
    *,
    workflow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise LifecycleError("invalid-runner-state", "runner state must be an object")
    if state.get("schemaVersion") != "agent-runner-state.v1":
        raise LifecycleError("invalid-runner-state", "runner state schemaVersion is unsupported")
    revision = _positive_int(state.get("runnerRevision"), label="runnerRevision")
    status = state.get("status")
    if status not in RUNNER_PHASES:
        raise LifecycleError("invalid-runner-state", "runner status is unsupported")
    lineage = _lineage(state.get("lineage"))
    _validate_policy(state.get("policy"))
    counters = _counters(state.get("counters"))
    history = state.get("history")
    if not isinstance(history, list) or not history:
        raise LifecycleError("invalid-runner-state", "runner history is required")
    operations = state.get("operations")
    if not isinstance(operations, dict):
        raise LifecycleError("invalid-runner-state", "runner operations ledger is required")
    _validate_history_and_operations(history, operations, status)
    stored_digest = state.get("stateDigest")
    if stored_digest is not None and stored_digest != _state_digest(state):
        raise LifecycleError("runner-state-digest-mismatch", "runner stateDigest does not match runner state")
    if workflow_state is not None:
        _validate_workflow_binding(lineage, workflow_state)
    return {
        "schemaVersion": "agent-runner-state-validation.v1",
        "status": "PASS",
        "runnerRevision": revision,
        "runnerStatus": status,
        "currentTaskId": state.get("currentTaskId"),
        "lineage": lineage,
        "counters": counters,
        "historyCount": len(history),
        "stateDigest": _state_digest(state),
    }


def transition_runner(
    state: dict[str, Any],
    workflow_state: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    validation = validate_runner_state(state, workflow_state=workflow_state)
    _validate_request_header(request, expected_revision=validation["runnerRevision"])
    operation_id = request["operationId"]
    if operation_id in state.get("operations", {}):
        raise LifecycleError("duplicate-runner-operation", "runner operationId was already applied")
    action = request.get("action")
    if action not in TRANSITION_ACTIONS:
        raise LifecycleError("invalid-runner-transition", "runner action is unsupported")
    current = str(state.get("status"))
    if current in TERMINAL_PHASES:
        raise LifecycleError("runner-terminal-state", "runner terminal state cannot transition")
    if action not in ALLOWED_TRANSITIONS.get(current, set()):
        raise LifecycleError(
            "runner-transition-not-allowed",
            "runner action is not allowed from the current status",
            {"fromStatus": current, "action": action},
        )
    task_id = _request_task_id(request, state)
    task = _workflow_task(workflow_state, task_id)
    _apply_action_guards(state, task, action, request)
    updated = _copy_state(state)
    from_status = str(updated["status"])
    updated["status"] = RESULT_PHASE_BY_ACTION[action]
    updated["currentTaskId"] = task_id
    updated["runnerRevision"] = int(updated["runnerRevision"]) + 1
    updated["counters"] = _updated_counters(updated["counters"], action, task_id, request)
    event = _history_event(request, from_status=from_status, to_status=updated["status"], task_id=task_id)
    updated["history"] = [*updated["history"], event]
    updated["operations"] = {
        **updated["operations"],
        operation_id: {"action": action, "runnerRevision": updated["runnerRevision"]},
    }
    if action == "block":
        updated["blocker"] = {"code": _required_string(request.get("blockerCode"), label="blockerCode"), "reason": request["reason"]}
    else:
        updated.pop("blocker", None)
    updated.pop("stopRequest", None)
    validate_runner_state(updated, workflow_state=workflow_state)
    result = _transition_result(updated, event, action=action)
    return {"state": {**updated, "stateDigest": _state_digest(updated)}, "result": result}


def request_runner_stop(
    state: dict[str, Any],
    workflow_state: dict[str, Any],
    *,
    operation_id: str,
    expected_runner_revision: int,
    reason: str,
) -> dict[str, Any]:
    validation = validate_runner_state(state, workflow_state=workflow_state)
    if expected_runner_revision != validation["runnerRevision"]:
        raise LifecycleError("runner-revision-mismatch", "runner revision mismatch")
    if operation_id in state.get("operations", {}):
        raise LifecycleError("duplicate-runner-operation", "runner operationId was already applied")
    current = str(state.get("status"))
    if current in TERMINAL_PHASES:
        raise LifecycleError("runner-terminal-state", "runner terminal state cannot be stopped")
    if current == "STOPPED":
        raise LifecycleError("runner-already-stopped", "runner is already stopped")
    updated = _copy_state(state)
    updated["runnerRevision"] = int(updated["runnerRevision"]) + 1
    updated["status"] = "STOPPED"
    updated["stopRequest"] = {"operationId": operation_id, "reason": reason, "resumeStatus": current}
    event = {
        "operationId": operation_id,
        "action": "stop",
        "fromStatus": current,
        "toStatus": "STOPPED",
        "taskId": updated.get("currentTaskId"),
        "reason": reason,
        "recordedAt": _now_iso(),
    }
    updated["history"] = [*updated["history"], event]
    updated["operations"] = {
        **updated["operations"],
        operation_id: {"action": "stop", "runnerRevision": updated["runnerRevision"]},
    }
    validate_runner_state(updated, workflow_state=workflow_state)
    return {"state": {**updated, "stateDigest": _state_digest(updated)}, "result": _transition_result(updated, event, action="stop")}


def resume_runner(
    state: dict[str, Any],
    workflow_state: dict[str, Any],
    *,
    operation_id: str,
    expected_runner_revision: int,
    reason: str,
) -> dict[str, Any]:
    validation = validate_runner_state(state, workflow_state=workflow_state)
    if expected_runner_revision != validation["runnerRevision"]:
        raise LifecycleError("runner-revision-mismatch", "runner revision mismatch")
    if operation_id in state.get("operations", {}):
        raise LifecycleError("duplicate-runner-operation", "runner operationId was already applied")
    if state.get("status") != "STOPPED":
        raise LifecycleError("runner-not-stopped", "runner resume requires STOPPED status")
    stop_request = state.get("stopRequest")
    if not isinstance(stop_request, dict) or stop_request.get("resumeStatus") not in RUNNER_PHASES:
        raise LifecycleError("invalid-runner-state", "runner stopRequest.resumeStatus is unsupported")
    resume_status = str(stop_request["resumeStatus"])
    if resume_status in TERMINAL_PHASES or resume_status == "STOPPED":
        raise LifecycleError("invalid-runner-state", "runner resumeStatus cannot be terminal or STOPPED")
    updated = _copy_state(state)
    updated["runnerRevision"] = int(updated["runnerRevision"]) + 1
    updated["status"] = resume_status
    updated.pop("stopRequest", None)
    event = {
        "operationId": operation_id,
        "action": "resume",
        "fromStatus": "STOPPED",
        "toStatus": resume_status,
        "taskId": updated.get("currentTaskId"),
        "reason": reason,
        "recordedAt": _now_iso(),
    }
    updated["history"] = [*updated["history"], event]
    updated["operations"] = {
        **updated["operations"],
        operation_id: {"action": "resume", "runnerRevision": updated["runnerRevision"]},
    }
    validate_runner_state(updated, workflow_state=workflow_state)
    return {"state": {**updated, "stateDigest": _state_digest(updated)}, "result": _transition_result(updated, event, action="resume")}


def build_runner_snapshot(
    state: dict[str, Any],
    workflow_state: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    validation = validate_runner_state(state, workflow_state=workflow_state)
    history = state.get("history", [])
    body = {
        "schemaVersion": "agent-runner-snapshot.v1",
        "status": "PASS",
        "runner": {
            "runnerStatus": validation["runnerStatus"],
            "runnerRevision": validation["runnerRevision"],
            "stateDigest": validation["stateDigest"],
            "currentTaskId": validation["currentTaskId"],
            "allowedNextActions": sorted(ALLOWED_TRANSITIONS.get(validation["runnerStatus"], set())),
        },
        "budget": validation["counters"],
        "lineage": validation["lineage"],
        "recentTransitions": history[-5:],
    }
    target = None
    token_estimate = estimate_tokens(body)
    if profile is not None:
        validate_context_profile(profile)
        selected = resolve_window(profile, window)
        limit = selected["limits"]["maxStateSummaryTokens"]
        target = {"window": selected["name"], "limit": limit}
        if token_estimate > limit:
            raise LifecycleError(
                "runner-summary-overflow",
                "runner snapshot exceeds compact context state-summary limit",
                {"estimatedTokens": token_estimate, "limit": limit, "window": selected["name"]},
            )
    body["estimatedTokens"] = token_estimate
    if target is not None:
        body["target"] = target
    return {**body, "snapshotDigest": canonical_digest(body)}


def write_runner_state(path: Path, state: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(canonical_bytes(state))
    tmp.replace(path)


def write_runner_state_create(path: Path, state: dict[str, Any]) -> None:
    if path.exists():
        raise LifecycleError("runner-state-exists", "runner state already exists", {"path": str(path)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(state))


def _validate_request_header(request: dict[str, Any], *, expected_revision: int) -> None:
    if request.get("schemaVersion") != "agent-runner-transition-request.v1":
        raise LifecycleError("invalid-runner-transition-request", "runner transition request schemaVersion is unsupported")
    _required_string(request.get("operationId"), label="operationId")
    if request.get("expectedRunnerRevision") != expected_revision:
        raise LifecycleError("runner-revision-mismatch", "runner revision mismatch")
    _required_string(request.get("reason"), label="reason")


def _apply_action_guards(state: dict[str, Any], task: dict[str, Any], action: str, request: dict[str, Any]) -> None:
    counters = _counters(state.get("counters"))
    policy = _validate_policy(state.get("policy"))
    task_id = str(task["id"])
    if action == "attempt" and counters["attemptsByTask"].get(task_id, 0) >= policy["maxAttemptsPerTask"]:
        raise LifecycleError("runner-attempt-limit-exceeded", "runner attempt limit exceeded", {"taskId": task_id})
    if action == "reroute" and counters["reroutesByTask"].get(task_id, 0) >= policy["maxReroutesPerTask"]:
        raise LifecycleError("runner-reroute-limit-exceeded", "runner reroute limit exceeded", {"taskId": task_id})
    if action == "split" and counters["splitsByTask"].get(task_id, 0) >= policy["maxSplitsPerTask"]:
        raise LifecycleError("runner-split-limit-exceeded", "runner split limit exceeded", {"taskId": task_id})
    next_billable = counters["billableTokens"] + _usage_tokens(request)
    if next_billable > policy["maxBillableTokens"]:
        raise LifecycleError(
            "runner-token-budget-exceeded",
            "runner token budget exceeded",
            {"billableTokens": next_billable, "maxBillableTokens": policy["maxBillableTokens"]},
        )
    if action == "remediate" and request.get("patch") is not None:
        _validate_patch(request["patch"], task)


def _validate_patch(patch: Any, task: dict[str, Any]) -> None:
    if not isinstance(patch, dict):
        raise LifecycleError("invalid-runner-patch", "runner patch must be an object")
    if patch.get("status") != "PASS":
        raise LifecycleError("runner-patch-restore-failed", "runner patch restoration did not pass")
    _digest(patch.get("patchDigest"), label="patch.patchDigest")
    changed = patch.get("changedFiles")
    if not isinstance(changed, list) or not all(isinstance(item, str) and item for item in changed):
        raise LifecycleError("invalid-runner-patch", "patch changedFiles must be a list of paths")
    writes = task.get("writes", [])
    if not isinstance(writes, list) or not all(isinstance(item, str) and item for item in writes):
        raise LifecycleError("invalid-workflow-state", "task writes must be a list of paths")
    normalized_writes = [normalize_repo_path(item, label="task write") for item in writes]
    for item in changed:
        path = normalize_repo_path(item, label="patch changed file")
        if not any(is_under_repo_path(path, root) for root in normalized_writes):
            raise LifecycleError(
                "runner-patch-write-scope-violation",
                "runner patch writes outside task scope",
                {"path": path, "writes": normalized_writes},
            )


def _transition_result(state: dict[str, Any], event: dict[str, Any], *, action: str) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-runner-transition-result.v1",
        "status": "PASS",
        "action": action,
        "runnerRevision": state["runnerRevision"],
        "runnerStatus": state["status"],
        "transition": event,
        "allowedNextActions": sorted(ALLOWED_TRANSITIONS.get(str(state["status"]), set())),
        "stateDigest": _state_digest(state),
    }
    return {**body, "resultDigest": canonical_digest(body)}


def _updated_counters(counters: dict[str, Any], action: str, task_id: str, request: dict[str, Any]) -> dict[str, Any]:
    updated = {
        "attemptsByTask": dict(counters.get("attemptsByTask", {})),
        "reroutesByTask": dict(counters.get("reroutesByTask", {})),
        "splitsByTask": dict(counters.get("splitsByTask", {})),
        "billableTokens": int(counters.get("billableTokens", 0)) + _usage_tokens(request),
    }
    if action == "attempt":
        updated["attemptsByTask"][task_id] = updated["attemptsByTask"].get(task_id, 0) + 1
    elif action == "reroute":
        updated["reroutesByTask"][task_id] = updated["reroutesByTask"].get(task_id, 0) + 1
    elif action == "split":
        updated["splitsByTask"][task_id] = updated["splitsByTask"].get(task_id, 0) + 1
    return updated


def _history_event(request: dict[str, Any], *, from_status: str, to_status: str, task_id: str) -> dict[str, Any]:
    event = {
        "operationId": request["operationId"],
        "action": request["action"],
        "fromStatus": from_status,
        "toStatus": to_status,
        "taskId": task_id,
        "reason": request["reason"],
        "recordedAt": _now_iso(),
    }
    if request.get("evidenceIds"):
        event["evidenceIds"] = _string_list(request["evidenceIds"], label="evidenceIds", allow_empty=True)
    if request.get("usage"):
        event["usage"] = request["usage"]
    if request.get("patch"):
        event["patchDigest"] = request["patch"].get("patchDigest")
    return event


def _request_task_id(request: dict[str, Any], state: dict[str, Any]) -> str:
    value = request.get("taskId", state.get("currentTaskId"))
    return _required_string(value, label="taskId")


def _workflow_task(workflow_state: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in workflow_state.get("tasks", []):
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    raise LifecycleError("runner-task-not-found", "runner task is missing from workflow state", {"taskId": task_id})


def _first_ready_task(workflow_state: dict[str, Any]) -> str:
    tasks = [task for task in workflow_state.get("tasks", []) if isinstance(task, dict)]
    for status in ("READY", "IN_PROGRESS", "ACCEPTED"):
        for task in tasks:
            if task.get("status") == status:
                return _required_string(task.get("id"), label="task.id")
    if tasks:
        return _required_string(tasks[0].get("id"), label="task.id")
    raise LifecycleError("runner-no-task", "workflow state has no tasks")


def _lineage_from_workflow(state: dict[str, Any]) -> dict[str, Any]:
    return {key: state.get(key) for key in LINEAGE_KEYS}


def _lineage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-runner-state", "runner lineage is required")
    result = {key: value.get(key) for key in LINEAGE_KEYS}
    for key, item in result.items():
        if key == "planRevision":
            _positive_int(item, label="lineage.planRevision")
        elif not isinstance(item, str) or not item:
            raise LifecycleError("invalid-runner-state", f"runner lineage.{key} is required")
    return result


def _validate_workflow_binding(lineage: dict[str, Any], workflow_state: dict[str, Any]) -> None:
    for key in LINEAGE_KEYS:
        if lineage.get(key) != workflow_state.get(key):
            raise LifecycleError("runner-lineage-mismatch", f"runner {key} mismatch")


def _validate_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise LifecycleError("invalid-runner-policy", "runner policy must be an object")
    if policy.get("schemaVersion") != "agent-runner-policy.v1":
        raise LifecycleError("invalid-runner-policy", "runner policy schemaVersion is unsupported")
    return {
        "schemaVersion": "agent-runner-policy.v1",
        "maxAttemptsPerTask": _non_negative_int(policy.get("maxAttemptsPerTask"), label="maxAttemptsPerTask"),
        "maxReroutesPerTask": _non_negative_int(policy.get("maxReroutesPerTask"), label="maxReroutesPerTask"),
        "maxSplitsPerTask": _non_negative_int(policy.get("maxSplitsPerTask"), label="maxSplitsPerTask"),
        "maxBillableTokens": _non_negative_int(policy.get("maxBillableTokens"), label="maxBillableTokens"),
    }


def _counters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-runner-state", "runner counters are required")
    attempts = _string_int_map(value.get("attemptsByTask"), label="attemptsByTask")
    reroutes = _string_int_map(value.get("reroutesByTask"), label="reroutesByTask")
    splits = _string_int_map(value.get("splitsByTask"), label="splitsByTask")
    billable = _non_negative_int(value.get("billableTokens"), label="billableTokens")
    return {
        "attemptsByTask": attempts,
        "reroutesByTask": reroutes,
        "splitsByTask": splits,
        "billableTokens": billable,
    }


def _validate_history_and_operations(history: list[Any], operations: dict[str, Any], status: str) -> None:
    seen: set[str] = set()
    for event in history:
        if not isinstance(event, dict):
            raise LifecycleError("invalid-runner-state", "runner history events must be objects")
        operation_id = _required_string(event.get("operationId"), label="history.operationId")
        if operation_id in seen:
            raise LifecycleError("invalid-runner-state", "runner history contains duplicate operationId")
        seen.add(operation_id)
        action = _required_string(event.get("action"), label="history.action")
        if not isinstance(event.get("toStatus"), str) or not event.get("toStatus"):
            raise LifecycleError("invalid-runner-state", "runner history.toStatus is required")
        operation = operations.get(operation_id)
        if not isinstance(operation, dict):
            raise LifecycleError("invalid-runner-state", "runner history operation is missing from ledger")
        if operation.get("action") != action:
            raise LifecycleError("invalid-runner-state", "runner history operation action mismatches ledger")
        _positive_int(operation.get("runnerRevision"), label=f"operations.{operation_id}.runnerRevision")
    extra = [operation_id for operation_id in operations if not isinstance(operation_id, str) or operation_id not in seen]
    if extra:
        raise LifecycleError("invalid-runner-state", "runner operations ledger contains entries missing from history")
    if history[-1].get("toStatus") != status:
        raise LifecycleError("invalid-runner-state", "runner history does not match current status")


def _usage_tokens(request: dict[str, Any]) -> int:
    usage = request.get("usage")
    if usage is None:
        return 0
    if not isinstance(usage, dict):
        raise LifecycleError("invalid-runner-transition-request", "usage must be an object")
    return _non_negative_int(usage.get("billableTokens", 0), label="usage.billableTokens")


def _string_int_map(value: Any, *, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-runner-state", f"{label} must be an object")
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise LifecycleError("invalid-runner-state", f"{label} keys must be strings")
        result[key] = _non_negative_int(item, label=f"{label}.{key}")
    return result


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-runner-state", f"{label} is required")
    return value


def _string_list(value: Any, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-runner-state", f"{label} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise LifecycleError("invalid-runner-state", f"{label} must not be empty")
    return list(value)


def _digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleError("invalid-runner-patch", f"{label} must be a 64-character digest")
    return value


def _positive_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError("invalid-runner-state", f"{label} must be a positive integer")
    return value


def _non_negative_int(value: Any, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError("invalid-runner-state", f"{label} must be a non-negative integer")
    return value


def _copy_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in state.items() if key != "stateDigest"},
        "policy": dict(state["policy"]),
        "lineage": dict(state["lineage"]),
        "counters": {
            "attemptsByTask": dict(state["counters"]["attemptsByTask"]),
            "reroutesByTask": dict(state["counters"]["reroutesByTask"]),
            "splitsByTask": dict(state["counters"]["splitsByTask"]),
            "billableTokens": state["counters"]["billableTokens"],
        },
        "history": list(state["history"]),
        "operations": dict(state["operations"]),
    }


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _state_digest(state: dict[str, Any]) -> str:
    return canonical_digest({key: value for key, value in state.items() if key != "stateDigest"})
