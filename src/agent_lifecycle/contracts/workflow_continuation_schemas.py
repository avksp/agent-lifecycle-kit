"""Projection and one-step apply schemas for guided workflow continuation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}

WORKFLOW_CONTINUATION_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-workflow-continuation-action.v1": open_object_schema(
        "agent-workflow-continuation-action.v1",
        required=[
            "schemaVersion",
            "route",
            "managedActionType",
            "stateRevision",
            "planDigest",
            "sourceRevision",
            "operationId",
            "taskId",
            "suppliedInputs",
            "managedActionDigest",
            "actionDigest",
        ],
        properties={
            "route": {"type": "string", "minLength": 1},
            "managedActionType": {"type": "string", "minLength": 1},
            "stateRevision": {"type": "integer", "minimum": 1},
            "planDigest": _DIGEST,
            "sourceRevision": {"type": "string", "minLength": 1},
            "operationId": {"type": "string", "minLength": 1},
            "taskId": {"type": ["string", "null"]},
            "suppliedInputs": {"type": "object"},
            "managedActionDigest": _DIGEST,
            "actionDigest": _DIGEST,
        },
    ),
    "agent-workflow-continuation-receipt.v1": open_object_schema(
        "agent-workflow-continuation-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "mode",
            "operationId",
            "stateBefore",
            "stateAfter",
            "plan",
            "action",
            "requiredInputs",
            "nextAction",
            "appliedEvent",
            "blockers",
            "modelCallsStarted",
            "stateWritten",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["INPUT_REQUIRED", "READY", "APPLIED", "WAITING", "BLOCKED"]},
            "mode": {"enum": ["PROJECT", "APPLY"]},
            "operationId": {"type": "string", "minLength": 1},
            "stateBefore": {"type": ["object", "null"]},
            "stateAfter": {"type": ["object", "null"]},
            "plan": {"type": ["object", "null"]},
            "action": {"type": ["object", "null"]},
            "requiredInputs": {"type": "array", "items": {"type": "object"}, "maxItems": 32},
            "nextAction": {"type": ["object", "null"]},
            "appliedEvent": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 64},
            "modelCallsStarted": {"const": False},
            "stateWritten": {"type": "boolean"},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
}
