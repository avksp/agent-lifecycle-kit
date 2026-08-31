"""Closed schemas for bounded cross-phase context packets."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

PHASE_PACKET_SCHEMA = "agent-phase-packet.v1"
PLANNING_HANDOFF_PAYLOAD_SCHEMA = "agent-phase-planning-handoff-payload.v1"
IMPLEMENTATION_PAYLOAD_SCHEMA = "agent-phase-implementation-payload.v1"
TASK_AUDIT_PAYLOAD_SCHEMA = "agent-phase-task-audit-payload.v1"
REMEDIATION_PAYLOAD_SCHEMA = "agent-phase-remediation-payload.v1"

_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_STRING = {"type": "string", "minLength": 1}
_STRING_LIST = {
    "type": "array",
    "items": _STRING,
    "uniqueItems": True,
}


def _closed_object(*, required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _closed_schema(schema_id: str, *, required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        **_closed_object(
            required=["schemaVersion", *required],
            properties={"schemaVersion": {"const": schema_id}, **properties},
        ),
    }


_ACCEPTANCE = _closed_object(
    required=["id"],
    properties={
        "id": _STRING,
        "requirementIds": _STRING_LIST,
        "evidenceIds": _STRING_LIST,
        "independentEvidenceIds": _STRING_LIST,
        "independence": {},
        "statement": {"type": "string"},
        "description": {"type": "string"},
        "source": {},
        "priority": {},
    },
)

_EVIDENCE = _closed_object(
    required=["id"],
    properties={
        "id": _STRING,
        "description": {"type": "string"},
        "source": {},
        "validation": {},
        "artifactPath": {"type": "string"},
        "required": {"type": "boolean"},
    },
)

_WORKSTREAM = _closed_object(
    required=[
        "id",
        "dependsOn",
        "writes",
        "readOnly",
        "forbiddenWrites",
        "acceptanceCriteria",
        "evidenceRequirements",
        "activeBlockerIds",
    ],
    properties={
        "id": _STRING,
        "dependsOn": _STRING_LIST,
        "writes": _STRING_LIST,
        "readOnly": _STRING_LIST,
        "forbiddenWrites": _STRING_LIST,
        "acceptanceCriteria": {"type": "array", "items": _ACCEPTANCE},
        "evidenceRequirements": {"type": "array", "items": _EVIDENCE},
        "activeBlockerIds": _STRING_LIST,
    },
)

_DEPENDENCY_EDGE = _closed_object(
    required=["from", "to"],
    properties={"from": _STRING, "to": _STRING},
)

_REVIEW_REQUIREMENTS = _closed_object(
    required=["independentRequired", "minimumVerdict", "requiredReviewerIds"],
    properties={
        "independentRequired": {"type": "boolean"},
        "minimumVerdict": _STRING,
        "requiredReviewerIds": _STRING_LIST,
    },
)

_PLANNING_HANDOFF = _closed_schema(
    PLANNING_HANDOFF_PAYLOAD_SCHEMA,
    required=["workstreams", "dependencyEdges"],
    properties={
        "workstreams": {"type": "array", "items": _WORKSTREAM},
        "dependencyEdges": {"type": "array", "items": _DEPENDENCY_EDGE},
    },
)

_IMPLEMENTATION = _closed_schema(
    IMPLEMENTATION_PAYLOAD_SCHEMA,
    required=[
        "taskId",
        "attempt",
        "taskPacketDigest",
        "writes",
        "readOnly",
        "forbiddenWrites",
        "acceptanceCriteria",
        "evidenceRequirements",
        "activeBlockerIds",
    ],
    properties={
        "taskId": _STRING,
        "attempt": {"type": "integer", "minimum": 1},
        "taskPacketDigest": _DIGEST,
        "writes": _STRING_LIST,
        "readOnly": _STRING_LIST,
        "forbiddenWrites": _STRING_LIST,
        "acceptanceCriteria": {"type": "array", "items": _ACCEPTANCE},
        "evidenceRequirements": {"type": "array", "items": _EVIDENCE},
        "activeBlockerIds": _STRING_LIST,
    },
)

_TASK_AUDIT = _closed_schema(
    TASK_AUDIT_PAYLOAD_SCHEMA,
    required=[
        "taskId",
        "attempt",
        "resultDigest",
        "changeSetDigest",
        "changedPaths",
        "writes",
        "readOnly",
        "forbiddenWrites",
        "reviewRequirements",
        "acceptanceCriteria",
        "evidenceReferences",
        "activeBlockerIds",
    ],
    properties={
        "taskId": _STRING,
        "attempt": {"type": "integer", "minimum": 1},
        "resultDigest": _DIGEST,
        "changeSetDigest": _DIGEST,
        "changedPaths": _STRING_LIST,
        "writes": _STRING_LIST,
        "readOnly": _STRING_LIST,
        "forbiddenWrites": _STRING_LIST,
        "reviewRequirements": _REVIEW_REQUIREMENTS,
        "acceptanceCriteria": {"type": "array", "items": _ACCEPTANCE},
        "evidenceReferences": _STRING_LIST,
        "activeBlockerIds": _STRING_LIST,
    },
)

_REMEDIATION = _closed_schema(
    REMEDIATION_PAYLOAD_SCHEMA,
    required=[
        "taskId",
        "attempt",
        "priorResultDigest",
        "priorReviewDigest",
        "changedPaths",
        "openFindingIds",
        "remainingAttempts",
        "writes",
        "readOnly",
        "forbiddenWrites",
        "acceptanceCriteria",
        "evidenceRequirements",
        "activeBlockerIds",
    ],
    properties={
        "taskId": _STRING,
        "attempt": {"type": "integer", "minimum": 1},
        "priorResultDigest": _DIGEST,
        "priorReviewDigest": _DIGEST,
        "changedPaths": _STRING_LIST,
        "openFindingIds": _STRING_LIST,
        "remainingAttempts": {"type": "integer", "minimum": 1},
        "writes": _STRING_LIST,
        "readOnly": _STRING_LIST,
        "forbiddenWrites": _STRING_LIST,
        "acceptanceCriteria": {"type": "array", "items": _ACCEPTANCE},
        "evidenceRequirements": {"type": "array", "items": _EVIDENCE},
        "activeBlockerIds": _STRING_LIST,
    },
)

PHASE_PACKET_SCHEMAS: dict[str, dict[str, Any]] = {
    PLANNING_HANDOFF_PAYLOAD_SCHEMA: _PLANNING_HANDOFF,
    IMPLEMENTATION_PAYLOAD_SCHEMA: _IMPLEMENTATION,
    TASK_AUDIT_PAYLOAD_SCHEMA: _TASK_AUDIT,
    REMEDIATION_PAYLOAD_SCHEMA: _REMEDIATION,
    PHASE_PACKET_SCHEMA: _closed_schema(
        PHASE_PACKET_SCHEMA,
        required=[
            "purpose",
            "planDigest",
            "planLockDigest",
            "stateRevision",
            "sourceRevision",
            "writeScopeDigest",
            "acceptanceDigest",
            "evidenceDigest",
            "activeBlockerIds",
            "payload",
            "implementationAuthorized",
            "proofAuthority",
            "productionPromotionClaimed",
            "packetDigest",
        ],
        properties={
            "purpose": {"enum": ["PLANNING_HANDOFF", "IMPLEMENTATION", "TASK_AUDIT", "REMEDIATION"]},
            "planDigest": _DIGEST,
            "planLockDigest": _DIGEST,
            "stateRevision": {"type": ["integer", "null"], "minimum": 1},
            "sourceRevision": _STRING,
            "writeScopeDigest": _DIGEST,
            "acceptanceDigest": _DIGEST,
            "evidenceDigest": _DIGEST,
            "activeBlockerIds": _STRING_LIST,
            "payload": {
                "oneOf": [
                    deepcopy(_PLANNING_HANDOFF),
                    deepcopy(_IMPLEMENTATION),
                    deepcopy(_TASK_AUDIT),
                    deepcopy(_REMEDIATION),
                ]
            },
            "implementationAuthorized": {"const": False},
            "proofAuthority": {"const": "none"},
            "productionPromotionClaimed": {"const": False},
            "packetDigest": _DIGEST,
        },
    ),
}

__all__ = [
    "IMPLEMENTATION_PAYLOAD_SCHEMA",
    "PHASE_PACKET_SCHEMA",
    "PHASE_PACKET_SCHEMAS",
    "PLANNING_HANDOFF_PAYLOAD_SCHEMA",
    "REMEDIATION_PAYLOAD_SCHEMA",
    "TASK_AUDIT_PAYLOAD_SCHEMA",
]
