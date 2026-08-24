"""Read-only schemas retained for conversion of pre-2.0 runner artifacts.

These schemas are intentionally not used by active workflow execution. The
registry exposes them only so migration code can validate historical inputs.
"""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.runner_worktree_schemas import RUNNER_WORKTREE_SCHEMAS
from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

LEGACY_RUNNER_CORE_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-managed-lifecycle-next-action.v1": _open_object_schema(
        "agent-managed-lifecycle-next-action.v1",
        required=[
            "schemaVersion",
            "type",
            "status",
            "hostActionRequired",
            "modelCallsStarted",
            "stateMutationRequired",
            "blockers",
            "actionDigest",
        ],
        properties={
            "type": {"type": "string", "minLength": 1},
            "status": {"enum": ["READY", "BLOCKED"]},
            "hostActionRequired": {"type": "boolean"},
            "modelCallsStarted": {"const": False},
            "stateMutationRequired": {"type": "boolean"},
            "projectedAction": {"type": ["object", "null"]},
            "taskIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "authority": {"type": "object"},
            "deprecation": {"type": "object"},
            "workflowTransitionRequired": {"type": ["string", "null"]},
            "actionDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-managed-lifecycle-runner-receipt.v1": _open_object_schema(
        "agent-managed-lifecycle-runner-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "expectedRevision",
            "sourceRevision",
            "state",
            "plan",
            "nextAction",
            "blockers",
            "modelCallsStarted",
            "stateWritten",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "operationId": {"type": "string", "minLength": 1},
            "reason": {"type": ["string", "null"]},
            "expectedRevision": {"type": "integer", "minimum": 1},
            "sourceRevision": {"type": "string", "minLength": 1},
            "state": {"type": ["object", "null"]},
            "plan": {"type": ["object", "null"]},
            "nextAction": {"type": "object"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "modelCallsStarted": {"const": False},
            "stateWritten": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "authority": {"type": "object"},
            "deprecation": {"type": "object"},
            "workflowTransitionRequired": {"type": ["string", "null"]},
            "receiptDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-no-model-call-scan.v1": _open_object_schema(
        "agent-no-model-call-scan.v1",
        required=[
            "schemaVersion",
            "status",
            "paths",
            "checks",
            "blockers",
            "modelCallsStarted",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "paths": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "modelCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}

LEGACY_RUNNER_SCHEMAS: dict[str, dict[str, Any]] = {
    **{
        schema_id: schema
        for schema_id, schema in LEGACY_RUNNER_CORE_SCHEMAS.items()
        if schema_id != "agent-no-model-call-scan.v1"
    },
    **{
        schema_id: schema
        for schema_id, schema in RUNNER_WORKTREE_SCHEMAS.items()
        if schema_id.startswith("agent-runner-")
    },
}
