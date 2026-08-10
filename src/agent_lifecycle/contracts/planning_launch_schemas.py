"""Portable contracts for bounded planning-only adapter launches."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema


_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}


PLANNING_LAUNCH_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-planning-launch-envelope.v1": open_object_schema(
        "agent-planning-launch-envelope.v1",
        required=[
            "schemaVersion",
            "adapterId",
            "sessionId",
            "requestedMode",
            "input",
            "task",
            "authority",
            "limits",
        ],
        properties={
            "adapterId": {"type": "string", "minLength": 1},
            "sessionId": {"type": "string", "minLength": 1},
            "requestedMode": {"enum": ["auto", "research", "plan", "review"]},
            "input": {"type": "object"},
            "task": {
                "type": "object",
                "required": ["untrustedText"],
                "properties": {"untrustedText": {"type": "string"}},
            },
            "authority": {
                "type": "object",
                "required": ["planningOnly", "implementationAuthorized", "freezeRequired"],
                "properties": {
                    "planningOnly": {"const": True},
                    "implementationAuthorized": {"const": False},
                    "freezeRequired": {"const": True},
                },
            },
            "limits": {"type": "object"},
            "advisory": {"type": "object"},
        },
    ),
    "agent-planning-result.v1": open_object_schema(
        "agent-planning-result.v1",
        required=[
            "schemaVersion",
            "status",
            "summary",
            "requirements",
            "workstreams",
            "evidenceRoutes",
            "implementationAuthorized",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"enum": ["REVIEW_REQUIRED", "BLOCKED"]},
            "summary": {"type": "string", "minLength": 1},
            "requirements": {"type": "array", "items": {"type": ["object", "string"]}},
            "workstreams": {"type": "array", "items": {"type": "object"}},
            "evidenceRoutes": {"type": "array", "items": {"type": "object"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "openQuestions": {"type": "array", "items": {"type": "string"}},
            "recommendedQualityProfiles": {"type": "array", "items": {"type": "string"}},
            "usage": {"type": "object"},
            "implementationAuthorized": {"const": False},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-planning-launch-receipt.v1": open_object_schema(
        "agent-planning-launch-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "action",
            "adapterId",
            "sessionId",
            "requestedMode",
            "input",
            "process",
            "result",
            "usageEvidence",
            "processCalls",
            "implementationAuthorized",
            "requiresReview",
            "rawTaskTextStored",
            "hostLaunchStarted",
            "modelCallsStarted",
            "secretsWritten",
            "nativeConfigWritten",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["REVIEW_REQUIRED", "BLOCKED"]},
            "action": {"const": "PLANNING_LAUNCH"},
            "adapterId": {"type": "string", "minLength": 1},
            "sessionId": {"type": "string", "minLength": 1},
            "requestedMode": {"enum": ["auto", "research", "plan", "review"]},
            "input": {"type": "object"},
            "process": {"type": "object"},
            "result": {"type": ["object", "null"]},
            "usageEvidence": {"type": "object"},
            "processCalls": {"type": "integer", "minimum": 0, "maximum": 1},
            "implementationAuthorized": {"const": False},
            "requiresReview": {"const": True},
            "rawTaskTextStored": {"const": False},
            "hostLaunchStarted": {"type": "boolean"},
            "modelCallsStarted": {"type": "boolean"},
            "secretsWritten": {"const": False},
            "nativeConfigWritten": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    "agent-planning-session-state.v1": open_object_schema(
        "agent-planning-session-state.v1",
        required=[
            "schemaVersion",
            "sessionId",
            "adapterId",
            "requestedMode",
            "state",
            "input",
            "planningReceiptDigest",
            "implementationAuthorized",
            "rawTaskTextStored",
            "productionPromotionClaimed",
            "stateDigest",
        ],
        properties={
            "sessionId": {"type": "string", "minLength": 1},
            "adapterId": {"type": "string", "minLength": 1},
            "requestedMode": {"enum": ["auto", "research", "plan", "review"]},
            "state": {"enum": ["INTAKE_ACCEPTED", "PLANNING_RUNNING", "REVIEW_REQUIRED", "BLOCKED"]},
            "input": {"type": "object"},
            "planningReceiptDigest": {"type": ["string", "null"]},
            "resultDigest": {"type": ["string", "null"]},
            "implementationAuthorized": {"const": False},
            "rawTaskTextStored": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "stateDigest": _DIGEST,
        },
    ),
}
