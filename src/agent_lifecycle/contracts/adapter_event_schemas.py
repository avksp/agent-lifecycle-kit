"""Built-in JSON schema definitions for a lifecycle contract domain."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

_ACTION_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ACTION_EVIDENCE = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schemaVersion",
        "userRequestId",
        "operationLineage",
        "profileDigest",
        "effectiveConfigDigest",
        "capabilityDigest",
        "permissionDecision",
        "toolCategory",
        "resultLink",
    ],
    "properties": {
        "schemaVersion": {"const": "agent-adapter-action-evidence.v1"},
        "userRequestId": {"type": "string", "minLength": 1, "maxLength": 128},
        "operationLineage": {
            "type": "object",
            "additionalProperties": False,
            "required": ["runId", "taskId", "operationId"],
            "properties": {
                "runId": {"type": "string", "minLength": 1, "maxLength": 128},
                "taskId": {"type": "string", "minLength": 1, "maxLength": 128},
                "operationId": {"type": "string", "minLength": 1, "maxLength": 128},
            },
        },
        "profileDigest": _ACTION_DIGEST,
        "effectiveConfigDigest": _ACTION_DIGEST,
        "capabilityDigest": _ACTION_DIGEST,
        "permissionDecision": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "source"],
            "properties": {
                "status": {"enum": ["ALLOW", "DENY", "REVIEW_REQUIRED"]},
                "source": {"enum": ["host", "frozen-plan", "operator"]},
                "decisionDigest": _ACTION_DIGEST,
            },
        },
        "toolCategory": {
            "enum": ["command", "filesystem", "process", "model", "review", "workflow", "other"]
        },
        "resultLink": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "ref", "digest"],
            "properties": {
                "kind": {"enum": ["task-result", "operation-result", "artifact"]},
                "ref": {"type": "string", "minLength": 1, "maxLength": 512},
                "digest": _ACTION_DIGEST,
            },
        },
        "actionEvidenceDigest": _ACTION_DIGEST,
    },
}

ADAPTER_EVENT_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-adapter-event.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-adapter-event.v1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "eventId",
            "host",
            "adapterId",
            "runId",
            "taskId",
            "operationId",
            "sequence",
            "eventType",
            "status",
            "recordedAt",
            "payload",
        ],
        "properties": {
            "schemaVersion": {"const": "agent-adapter-event.v1"},
            "eventId": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "adapterId": {"type": "string", "minLength": 1},
            "runId": {"type": "string", "minLength": 1},
            "taskId": {"type": "string", "minLength": 1},
            "operationId": {"type": "string", "minLength": 1},
            "sequence": {"type": "integer", "minimum": 1},
            "eventType": {
                "enum": [
                    "session.started",
                    "task.launched",
                    "command.completed",
                    "writes.summarized",
                    "usage.reported",
                    "task.blocked",
                    "task.completed",
                ]
            },
            "status": {"enum": ["INFO", "PASS", "FAIL", "BLOCKED"]},
            "recordedAt": {"type": "string", "minLength": 1},
            "payload": {
                "type": "object",
                "properties": {"actionEvidence": _ACTION_EVIDENCE},
            },
        },
    },
    "agent-adapter-action-evidence.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-adapter-action-evidence.v1",
        **_ACTION_EVIDENCE,
    },
    "agent-adapter-action-evidence-validation.v1": _open_object_schema(
        "agent-adapter-action-evidence-validation.v1",
        required=["schemaVersion", "status", "blockers", "productionPromotionClaimed", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "userRequestId": {"type": ["string", "null"], "maxLength": 128},
            "operationId": {"type": ["string", "null"], "maxLength": 128},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 64},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _ACTION_DIGEST,
        },
    ),
    "agent-adapter-event-stream-validation.v1": _open_object_schema(
        "agent-adapter-event-stream-validation.v1",
        required=["schemaVersion", "status", "eventCount", "eventTypes", "blockers"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "host": {"type": ["string", "null"]},
            "adapterId": {"type": ["string", "null"]},
            "runId": {"type": ["string", "null"]},
            "taskId": {"type": ["string", "null"]},
            "eventCount": {"type": "integer", "minimum": 0},
            "eventTypes": {"type": "array", "items": {"type": "string"}},
            "terminalEvent": {"type": ["string", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-adapter-event-stream-receipt.v1": _open_object_schema(
        "agent-adapter-event-stream-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "host",
            "runId",
            "taskId",
            "operationId",
            "producer",
            "descriptorDigest",
            "eventStreamDigest",
            "eventCount",
            "eventTypes",
            "terminalEvent",
            "emittedAt",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"const": "PASS"},
            "adapterId": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "runId": {"type": "string", "minLength": 1},
            "taskId": {"type": "string", "minLength": 1},
            "operationId": {"type": "string", "minLength": 1},
            "producer": {"type": "object"},
            "descriptorDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "eventStreamDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "eventCount": {"type": "integer", "minimum": 1},
            "eventTypes": {"type": "array", "items": {"type": "string"}},
            "terminalEvent": {"type": "string", "minLength": 1},
            "emittedAt": {"type": "string", "minLength": 1},
            "productionPromotionClaimed": {"const": False},
            "evidenceLevel": {"enum": ["LEGACY", "OBSERVED"]},
            "actionEvidenceDigest": _ACTION_DIGEST,
        },
    ),
    "agent-adapter-event-capture-validation.v1": _open_object_schema(
        "agent-adapter-event-capture-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "host",
            "declaredEventCapture",
            "eventCount",
            "blockers",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "declaredEventCapture": {"type": "boolean"},
            "eventCount": {"type": "integer", "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "evidenceLevel": {"enum": ["LEGACY", "OBSERVED"]},
            "actionEvidenceDigest": _ACTION_DIGEST,
        },
    ),
    "agent-adapter-lifecycle-control-validation.v1": _open_object_schema(
        "agent-adapter-lifecycle-control-validation.v1",
        required=["schemaVersion", "status", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "policy": {"type": ["object", "null"]},
            "request": {"type": ["object", "null"]},
            "decision": {"type": ["object", "null"]},
            "events": {"type": "object"},
            "attestation": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
}
