"""Workflow state loading, validation and atomic persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.canonical import canonical_bytes, canonical_digest
from agent_lifecycle.contracts.persistence import replace_private_json as write_json_replace_private
from agent_lifecycle.contracts.workflow_state_schemas import (
    WORKFLOW_STATE_V3,
    WORKFLOW_STATE_V4,
    validate_workflow_state,
)

TERMINAL_PHASES = {"COMPLETE", "FAILED", "CANCELLED"}
EXECUTION_PHASES = {"RUNNING", "STEP_REVIEW", "REMEDIATING"}
EXTERNAL_ACTION_PHASES = {"RUNNING", "FINAL_AUDIT", "STEP_REVIEW", "REMEDIATING"}
BLOCKER_RECOVERY_ROUTES = {
    "run": {"resolve-run"},
    "task": {"task-review", "budget-decision", "replan-task", "cancel-run"},
    "plan": {"adopt-plan"},
    "external": {"external-action"},
}


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_state(path: Path) -> dict[str, Any]:
    state = read_json_object(path, label="workflow state")
    if state.get("schemaVersion") not in {WORKFLOW_STATE_V3, WORKFLOW_STATE_V4}:
        raise LifecycleError("unsupported-workflow-state", "workflow state schemaVersion is unsupported")
    state = validate_workflow_state(state)
    if state.get("schemaVersion") == WORKFLOW_STATE_V4:
        _validate_recovery_state(state)
    return state


def validate_typed_blocker(
    blocker: Any,
    *,
    expected_task_id: str | None = None,
) -> dict[str, Any]:
    """Validate the closed recovery vocabulary without resolving the blocker."""

    if not isinstance(blocker, dict):
        raise LifecycleError("invalid-workflow-state", "workflow blocker must be an object")
    if "blocker" in blocker or "blockers" in blocker:
        raise LifecycleError("nested-blocker-forbidden", "workflow blockers cannot contain nested blockers")
    for key in ("code", "reason", "scope", "recoveryRoute"):
        value = blocker.get(key)
        if not isinstance(value, str) or not value:
            raise LifecycleError("invalid-workflow-blocker", f"workflow blocker {key} is required")
    scope = blocker["scope"]
    route = blocker["recoveryRoute"]
    if scope not in BLOCKER_RECOVERY_ROUTES or route not in BLOCKER_RECOVERY_ROUTES[scope]:
        raise LifecycleError(
            "invalid-workflow-blocker",
            "workflow blocker recovery route is not valid for its scope",
            {"scope": scope, "recoveryRoute": route},
        )
    task_id = blocker.get("taskId")
    if scope == "task":
        if not isinstance(task_id, str) or not task_id:
            raise LifecycleError("invalid-workflow-blocker", "task blocker requires taskId")
        if expected_task_id is not None and task_id != expected_task_id:
            raise LifecycleError("workflow-blocker-lineage-mismatch", "task blocker taskId mismatch")
    elif task_id is not None:
        raise LifecycleError("invalid-workflow-blocker", "non-task blocker must not carry taskId")
    if "attempt" in blocker and (
        not isinstance(blocker["attempt"], int) or isinstance(blocker["attempt"], bool) or blocker["attempt"] < 1
    ):
        raise LifecycleError("invalid-workflow-blocker", "blocker attempt must be a positive integer")
    return blocker


def _validate_recovery_state(state: dict[str, Any]) -> None:
    phase = state.get("phase")
    if phase == "PLAN_ONLY":
        if state.get("startMode") != "plan-only":
            raise LifecycleError("invalid-workflow-state", "PLAN_ONLY requires plan-only start mode")
        authorization = state.get("authorization")
        if isinstance(authorization, dict) and authorization.get("granted") is True:
            raise LifecycleError("plan-only-authorized", "plan-only workflow cannot be authorized")
    blocker = state.get("blocker")
    if blocker is not None:
        validate_typed_blocker(blocker)
        if blocker.get("scope") == "task":
            task = next((item for item in state.get("tasks", []) if item.get("id") == blocker.get("taskId")), None)
            if not isinstance(task, dict):
                raise LifecycleError("workflow-blocker-lineage-mismatch", "task blocker refers to an unknown task")
            task_blocker = task.get("blocker")
            if task_blocker is not None:
                validate_typed_blocker(task_blocker, expected_task_id=str(task.get("id")))
                if task_blocker != blocker and blocker.get("recoveryRoute") != "budget-decision":
                    raise LifecycleError("workflow-blocker-lineage-mismatch", "run and task blockers differ")
    if phase == "BLOCKED" and blocker is None:
        raise LifecycleError("invalid-workflow-state", "BLOCKED state requires a typed blocker")
    if phase == "WAITING_FOR_BUDGET_DECISION" and (
        not isinstance(blocker, dict)
        or blocker.get("scope") != "task"
        or blocker.get("recoveryRoute") != "budget-decision"
    ):
        raise LifecycleError("invalid-workflow-state", "budget wait requires a task budget blocker")
    if phase == "WAITING_FOR_EXTERNAL_ACTION" and not isinstance(state.get("externalAction"), dict):
        raise LifecycleError("invalid-workflow-state", "external-action wait requires externalAction state")


def state_identity(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    data = canonical_bytes(state) + b"\n"
    return {
        "path": path.as_posix(),
        "sha256": canonical_digest(state),
        "bytes": len(data),
        "stateRevision": state["stateRevision"],
    }


def require_expected_revision(state: dict[str, Any], expected_revision: int) -> None:
    if state["stateRevision"] != expected_revision:
        raise LifecycleError(
            "state-revision-mismatch",
            "workflow state revision mismatch",
            {"expected": expected_revision, "actual": state["stateRevision"]},
        )


def require_operation_unused(state: dict[str, Any], operation_id: str) -> None:
    ledger = state.setdefault("operationLedger", {})
    if not isinstance(ledger, dict):
        raise LifecycleError("invalid-workflow-state", "operationLedger must be an object")
    if operation_id in ledger:
        raise LifecycleError("duplicate-operation", f"operation already recorded: {operation_id}")


def record_operation(state: dict[str, Any], *, operation_id: str, event_type: str) -> None:
    ledger = state.setdefault("operationLedger", {})
    if not isinstance(ledger, dict):
        raise LifecycleError("invalid-workflow-state", "operationLedger must be an object")
    ledger[operation_id] = {
        "stateRevision": state["stateRevision"],
        "eventType": event_type,
        "recordedAt": now_iso(),
    }


def deadline_after(started_at: str, seconds: int) -> str:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleError("invalid-timestamp", f"invalid timestamp: {started_at}") from exc
    return (start + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def write_state_replace(path: Path, state: dict[str, Any]) -> None:
    write_json_replace_private(path, state)


def summarize_state(path: Path, state: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        {
            "id": task.get("id"),
            "status": task.get("status"),
            "attempt": task.get("attempt"),
            "dependsOn": task.get("dependsOn", []),
            "required": task.get("required", True),
        }
        for task in state["tasks"]
    ]
    return {
        "schemaVersion": "agent-workflow-status.v1",
        "identity": state_identity(path, state),
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "phase": state["phase"],
        "blocker": state.get("blocker"),
        "authorization": state.get("authorization"),
        "tasks": tasks,
    }
