"""Built-in JSON schema definitions for a lifecycle contract domain."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

CORE_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-lifecycle-version.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-lifecycle-version.v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "version"],
        "properties": {
            "schemaVersion": {"const": "agent-lifecycle-version.v1"},
            "version": {"type": "string", "minLength": 1},
        },
    },
    "agent-lifecycle-schema-index.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-lifecycle-schema-index.v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "schemas"],
        "properties": {
            "schemaVersion": {"const": "agent-lifecycle-schema-index.v1"},
            "schemas": {"type": "array", "items": {"type": "object"}},
        },
    },
    "agent-lifecycle-error.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-lifecycle-error.v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "code", "message", "details"],
        "properties": {
            "schemaVersion": {"const": "agent-lifecycle-error.v1"},
            "code": {"type": "string", "minLength": 1},
            "message": {"type": "string", "minLength": 1},
            "details": {"type": "object"},
        },
    },
    "agent-host-operation-request.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-host-operation-request.v1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "operationId",
            "capability",
            "inputs",
            "outputs",
            "constraints",
        ],
        "properties": {
            "schemaVersion": {"const": "agent-host-operation-request.v1"},
            "operationId": {"type": "string", "minLength": 1},
            "capability": {"type": "string", "minLength": 1},
            "inputs": {"type": "object"},
            "outputs": {"type": "array", "items": {"type": "object"}},
            "constraints": {"type": "object"},
            "modelRoute": {"type": "object"},
        },
    },
    "agent-host-operation-receipt.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-host-operation-receipt.v1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schemaVersion",
            "operationId",
            "capability",
            "status",
            "outputs",
            "usage",
        ],
        "properties": {
            "schemaVersion": {"const": "agent-host-operation-receipt.v1"},
            "operationId": {"type": "string", "minLength": 1},
            "capability": {"type": "string", "minLength": 1},
            "status": {"enum": ["PASS", "FAIL", "BLOCKED"]},
            "outputs": {"type": "array", "items": {"type": "object"}},
            "usage": {"type": "object"},
        },
    },
}
