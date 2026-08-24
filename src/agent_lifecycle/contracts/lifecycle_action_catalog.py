"""Closed catalog for workflow actions and compatibility commands.

The catalog is deliberately data-only.  It is shared by projections and
host gates, but it cannot be extended by a project profile or an adapter.
"""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.canonical import canonical_digest

ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "none": {"hostActionRequired": False, "stateMutationRequired": False},
    "blocked": {"hostActionRequired": True, "stateMutationRequired": False},
    "start-execution": {"hostActionRequired": True, "stateMutationRequired": True},
    "launch-tasks": {"hostActionRequired": True, "stateMutationRequired": False},
    "wait-for-active-tasks": {"hostActionRequired": False, "stateMutationRequired": False},
    "accept-task": {"hostActionRequired": True, "stateMutationRequired": False},
    "wait-for-task-outcome": {"hostActionRequired": False, "stateMutationRequired": False},
    "run-final-audit": {"hostActionRequired": True, "stateMutationRequired": False},
    "final-audit-outcome": {"hostActionRequired": True, "stateMutationRequired": True},
    "finalize-run": {"hostActionRequired": True, "stateMutationRequired": True},
    "request-human-decision": {"hostActionRequired": True, "stateMutationRequired": False},
    "record-budget-decision": {"hostActionRequired": True, "stateMutationRequired": True},
    "record-external-action-receipt": {"hostActionRequired": True, "stateMutationRequired": True},
    "request-execution-authorization": {"hostActionRequired": True, "stateMutationRequired": True},
    "adopt-plan": {"hostActionRequired": True, "stateMutationRequired": True},
}

ACTION_TYPES = frozenset(ACTION_CATALOG)
NON_MODEL_ACTION_TYPES = frozenset(
    {
        "adopt-plan",
        "final-audit-outcome",
        "request-human-decision",
        "record-budget-decision",
        "record-external-action-receipt",
    }
)

OPERATION_ACTION_TYPES: dict[str, frozenset[str]] = {
    "file-edit": frozenset({"launch-tasks"}),
    "shell-command": frozenset({"launch-tasks"}),
    "task-accept": frozenset({"accept-task"}),
    "run-finalize": frozenset({"finalize-run"}),
}

WORKFLOW_PHASE_ACTION_TYPES: dict[str, frozenset[str]] = {
    "AWAITING_AUTHORIZATION": frozenset({"request-execution-authorization"}),
    "PLAN_ONLY": frozenset({"none"}),
    "READY": frozenset({"start-execution"}),
    "RUNNING": frozenset(
        {
            "launch-tasks",
            "accept-task",
            "wait-for-active-tasks",
            "wait-for-task-outcome",
            "request-human-decision",
            "run-final-audit",
        }
    ),
    "BLOCKED": frozenset({"adopt-plan", "request-human-decision", "none"}),
    "WAITING_FOR_BUDGET_DECISION": frozenset({"record-budget-decision"}),
    "WAITING_FOR_EXTERNAL_ACTION": frozenset({"record-external-action-receipt"}),
    "FINAL_AUDIT": frozenset({"final-audit-outcome", "finalize-run"}),
    "COMPLETE": frozenset({"none"}),
    "FAILED": frozenset({"none"}),
    "CANCELLED": frozenset({"none"}),
}

COMPATIBILITY_COMMANDS: dict[str, dict[str, str]] = {
    "runner start": {"kind": "compatibility", "replacement": "workflow run"},
    "runner status": {"kind": "compatibility", "replacement": "workflow status"},
    "runner transition": {"kind": "compatibility", "replacement": "workflow task-*"},
    "runner stop": {"kind": "compatibility", "replacement": "workflow pause"},
    "runner resume": {"kind": "compatibility", "replacement": "workflow resume"},
}


def build_action(action_type: str, **fields: Any) -> dict[str, Any]:
    """Build a projected action only if it belongs to the closed catalog."""

    validate_action_type(action_type)
    return {"type": action_type, **fields}


def validate_action_type(action_type: Any) -> str:
    if not isinstance(action_type, str) or action_type not in ACTION_TYPES:
        raise ValueError(f"unsupported lifecycle action: {action_type!r}")
    return action_type


def action_requires_host(action_type: Any) -> bool:
    return bool(ACTION_CATALOG.get(validate_action_type(action_type), {}).get("hostActionRequired"))


def action_requires_state_mutation(action_type: Any) -> bool:
    return bool(ACTION_CATALOG.get(validate_action_type(action_type), {}).get("stateMutationRequired"))


def action_types_for_operation(operation: str) -> frozenset[str]:
    return OPERATION_ACTION_TYPES.get(operation, frozenset())


def validate_action_catalog() -> dict[str, Any]:
    """Return deterministic catalog checks used by release validation."""

    blockers: list[dict[str, Any]] = []
    for phase, actions in WORKFLOW_PHASE_ACTION_TYPES.items():
        unknown = sorted(set(actions).difference(ACTION_TYPES))
        if unknown:
            blockers.append({"code": "catalog-unknown-phase-action", "phase": phase, "actions": unknown})
    for operation, actions in OPERATION_ACTION_TYPES.items():
        unknown = sorted(set(actions).difference(ACTION_TYPES))
        if unknown:
            blockers.append({"code": "catalog-unknown-operation-action", "operation": operation, "actions": unknown})
    for command, entry in COMPATIBILITY_COMMANDS.items():
        if entry.get("kind") != "compatibility" or not entry.get("replacement"):
            blockers.append({"code": "catalog-invalid-command-classification", "command": command})
    body = {
        "schemaVersion": "agent-lifecycle-action-catalog.v1",
        "status": "PASS" if not blockers else "FAIL",
        "actionTypes": sorted(ACTION_TYPES),
        "workflowPhaseActions": {key: sorted(value) for key, value in sorted(WORKFLOW_PHASE_ACTION_TYPES.items())},
        "operationActions": {key: sorted(value) for key, value in sorted(OPERATION_ACTION_TYPES.items())},
        "compatibilityCommands": COMPATIBILITY_COMMANDS,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "catalogDigest": canonical_digest(body)}


__all__ = [
    "ACTION_CATALOG",
    "ACTION_TYPES",
    "COMPATIBILITY_COMMANDS",
    "NON_MODEL_ACTION_TYPES",
    "OPERATION_ACTION_TYPES",
    "WORKFLOW_PHASE_ACTION_TYPES",
    "action_requires_host",
    "action_requires_state_mutation",
    "action_types_for_operation",
    "build_action",
    "validate_action_catalog",
    "validate_action_type",
]
