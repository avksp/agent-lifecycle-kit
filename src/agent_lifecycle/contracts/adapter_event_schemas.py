"""Built-in JSON schema definitions for a lifecycle contract domain."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

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
            "payload": {"type": "object"},
        },
    },
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
        },
    ),
    "agent-adapter-event-capture-validation.v1": _open_object_schema(
        "agent-adapter-event-capture-validation.v1",
        required=["schemaVersion", "status", "adapterId", "host", "declaredEventCapture", "eventCount", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "declaredEventCapture": {"type": "boolean"},
            "eventCount": {"type": "integer", "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
}
