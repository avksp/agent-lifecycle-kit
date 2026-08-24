"""Contracts and runtime validation for durable workflow state."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.schema_builders import open_object_schema

WORKFLOW_STATE_V3 = "agent-workflow-state.v3"
WORKFLOW_STATE_V4 = "agent-workflow-state.v4"
WORKFLOW_STATE_MIGRATION_RECEIPT = "agent-workflow-state-migration-receipt.v1"

RUN_PHASES = {
    "AWAITING_AUTHORIZATION",
    "PLAN_ONLY",
    "READY",
    "RUNNING",
    "BLOCKED",
    "WAITING_FOR_BUDGET_DECISION",
    "WAITING_FOR_EXTERNAL_ACTION",
    "FINAL_AUDIT",
    "COMPLETE",
    "FAILED",
    "CANCELLED",
}
TASK_STATUSES = {
    "PENDING",
    "READY",
    "RUNNING",
    "VERIFYING",
    "REWORK",
    "ACCEPTED",
    "CONTRACT_CHANGE",
    "BLOCKED",
}

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_TASK_ID = {"type": "string", "minLength": 1, "maxLength": 256}

WORKFLOW_STATE_SCHEMAS: dict[str, dict[str, Any]] = {
    WORKFLOW_STATE_V4: open_object_schema(
        WORKFLOW_STATE_V4,
        required=[
            "schemaVersion",
            "runId",
            "packageId",
            "stateRevision",
            "phase",
            "tasks",
            "operationLedger",
            "eventLog",
        ],
        properties={
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": "string", "minLength": 1},
            "planRevision": {"type": "integer", "minimum": 0},
            "planDigest": {"type": "string", "minLength": 0, "maxLength": 64},
            "sourceRevision": {"type": "string", "minLength": 0},
            "stateRevision": {"type": "integer", "minimum": 1},
            "phase": {"enum": sorted(RUN_PHASES)},
            "tasks": {"type": "array"},
            "operationLedger": {"type": "object"},
            "eventLog": {"type": "string", "minLength": 1},
            "authorization": {"type": "object"},
            "budgets": {"type": "object"},
            "attemptHistory": {"type": "array"},
        },
    ),
    WORKFLOW_STATE_MIGRATION_RECEIPT: open_object_schema(
        WORKFLOW_STATE_MIGRATION_RECEIPT,
        required=[
            "schemaVersion",
            "status",
            "runId",
            "packageId",
            "fromSchemaVersion",
            "toSchemaVersion",
            "sourceStateRevision",
            "targetStateRevision",
            "operationId",
            "receiptDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "runId": {"type": "string", "minLength": 1},
            "packageId": {"type": "string", "minLength": 1},
            "fromSchemaVersion": {"const": WORKFLOW_STATE_V3},
            "toSchemaVersion": {"const": WORKFLOW_STATE_V4},
            "sourceStateRevision": {"type": "integer", "minimum": 1},
            "targetStateRevision": {"type": "integer", "minimum": 2},
            "operationId": {"type": "string", "minLength": 1},
            "receiptDigest": _DIGEST,
        },
    ),
}


def validate_workflow_state(state: dict[str, Any], *, allow_legacy: bool = True) -> dict[str, Any]:
    """Validate state shape and cross-field invariants before it is trusted."""

    if not isinstance(state, dict):
        raise LifecycleError("invalid-workflow-state", "workflow state must be an object")
    schema_version = state.get("schemaVersion")
    if schema_version == WORKFLOW_STATE_V3 and allow_legacy:
        _validate_legacy_state(state)
        return state
    if schema_version != WORKFLOW_STATE_V4:
        raise LifecycleError("unsupported-workflow-state", "workflow state schemaVersion is unsupported")
    _require_string(state, "runId")
    _require_string(state, "packageId")
    _require_positive_int(state, "stateRevision")
    phase = state.get("phase")
    if phase not in RUN_PHASES:
        raise LifecycleError("invalid-workflow-state", "workflow state phase is unsupported")
    if not isinstance(state.get("tasks"), list):
        raise LifecycleError("invalid-workflow-state", "tasks must be an array")
    if not isinstance(state.get("operationLedger"), dict):
        raise LifecycleError("invalid-workflow-state", "operationLedger must be an object")
    event_log = state.get("eventLog")
    if not isinstance(event_log, str) or not event_log or event_log.startswith("/"):
        raise LifecycleError("invalid-workflow-state", "eventLog must be a relative path")
    package_root = state.get("packageRoot", ".")
    if not isinstance(package_root, str) or not package_root or package_root.startswith("/"):
        raise LifecycleError("invalid-workflow-state", "packageRoot must be a relative path")
    _validate_tasks(state)
    _validate_phase_invariants(state)
    return state


def _validate_legacy_state(state: dict[str, Any]) -> None:
    _require_positive_int(state, "stateRevision")
    if not isinstance(state.get("phase"), str) or not state["phase"]:
        raise LifecycleError("invalid-workflow-state", "phase is required")
    if not isinstance(state.get("tasks"), list):
        raise LifecycleError("invalid-workflow-state", "tasks must be an array")


def _validate_tasks(state: dict[str, Any]) -> None:
    seen: set[str] = set()
    task_ids = {
        task.get("id")
        for task in state["tasks"]
        if isinstance(task, dict) and isinstance(task.get("id"), str)
    }
    for task in state["tasks"]:
        if not isinstance(task, dict):
            raise LifecycleError("invalid-workflow-state", "task entries must be objects")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id or task_id in seen:
            raise LifecycleError("invalid-workflow-state", "task IDs must be unique non-empty strings")
        seen.add(task_id)
        if task.get("status") not in TASK_STATUSES:
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has an unsupported status")
        attempt = task.get("attempt", 0)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has an invalid attempt")
        dependencies = task.get("dependsOn", [])
        if not isinstance(dependencies, list) or any(item not in task_ids for item in dependencies):
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has invalid dependencies")
        history = task.get("attemptHistory", [])
        if not isinstance(history, list) or len(history) > attempt:
            raise LifecycleError("invalid-workflow-state", f"task {task_id} has incoherent attempt history")
        if task.get("status") == "ACCEPTED" and any(
            key in task for key in ("attemptStartedAt", "attemptDeadlineAt", "attemptModelRoute")
        ):
            raise LifecycleError("invalid-workflow-state", f"accepted task {task_id} has active attempt state")
        if task.get("status") == "BLOCKED" and not isinstance(task.get("blocker"), dict):
            raise LifecycleError("invalid-workflow-state", f"blocked task {task_id} requires a typed blocker")
        if task.get("status") == "CONTRACT_CHANGE" and not isinstance(task.get("contractChangeRequest"), dict):
            raise LifecycleError(
                "invalid-workflow-state",
                f"contract-change task {task_id} requires a typed request",
            )


def _validate_phase_invariants(state: dict[str, Any]) -> None:
    required = [task for task in state["tasks"] if task.get("required", True)]
    if state["phase"] == "FINAL_AUDIT" and any(task.get("status") != "ACCEPTED" for task in required):
        raise LifecycleError("invalid-workflow-state", "FINAL_AUDIT requires every required task to be ACCEPTED")
    if state["phase"] == "BLOCKED" and not isinstance(state.get("blocker"), dict):
        raise LifecycleError("invalid-workflow-state", "BLOCKED state requires a typed blocker")


def _require_string(state: dict[str, Any], key: str) -> None:
    if not isinstance(state.get(key), str) or not state[key]:
        raise LifecycleError("invalid-workflow-state", f"{key} must be a non-empty string")


def _require_positive_int(state: dict[str, Any], key: str) -> None:
    value = state.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError("invalid-workflow-state", f"{key} must be a positive integer")


__all__ = [
    "RUN_PHASES",
    "TASK_STATUSES",
    "WORKFLOW_STATE_MIGRATION_RECEIPT",
    "WORKFLOW_STATE_SCHEMAS",
    "WORKFLOW_STATE_V3",
    "WORKFLOW_STATE_V4",
    "validate_workflow_state",
]
