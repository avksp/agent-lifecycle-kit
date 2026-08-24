"""Active workflow-run envelope schemas.

The workflow state machine is the sole execution authority. These envelopes
describe projections and receipts; they never authorize a host or mutate
state by themselves.
"""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

WORKFLOW_RUN_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-workflow-next-action.v1": _open_object_schema(
        "agent-workflow-next-action.v1",
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
    "agent-workflow-run-receipt.v1": _open_object_schema(
        "agent-workflow-run-receipt.v1",
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
