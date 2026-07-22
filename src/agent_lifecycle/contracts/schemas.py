"""Built-in JSON schema registry for portable lifecycle envelopes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

SCHEMA_INDEX_VERSION = "agent-lifecycle-schema-index.v1"

_SCHEMAS: dict[str, dict[str, Any]] = {
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
    "agent-small-context-profile.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-small-context-profile.v1",
        "type": "object",
        "additionalProperties": True,
        "required": ["schemaVersion", "profileId", "defaultWindow", "windows", "requiredSummaryFields"],
        "properties": {
            "schemaVersion": {"const": "agent-small-context-profile.v1"},
            "profileId": {"type": "string", "minLength": 1},
            "defaultWindow": {"enum": ["8k", "16k", "32k", "64k"]},
            "windows": {"type": "object"},
            "requiredSummaryFields": {"type": "array", "items": {"type": "string"}},
        },
    },
    "agent-context-render-receipt.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-context-render-receipt.v1",
        "type": "object",
        "additionalProperties": True,
        "required": ["schemaVersion", "status", "profileId", "window", "estimatedTokens", "checks", "envelopeDigest"],
        "properties": {
            "schemaVersion": {"const": "agent-context-render-receipt.v1"},
            "status": {"enum": ["PASS", "FAIL"]},
            "profileId": {"type": "string", "minLength": 1},
            "window": {"enum": ["8k", "16k", "32k", "64k"]},
            "estimatedTokens": {"type": "object"},
            "checks": {"type": "array", "items": {"type": "object"}},
            "envelopeDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    },
    "agent-sdd-tier-resolution.v1": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-sdd-tier-resolution.v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "tier", "reasons", "requestDigest", "rules"],
        "properties": {
            "schemaVersion": {"const": "agent-sdd-tier-resolution.v1"},
            "tier": {"enum": ["S0", "S1", "S2"]},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "requestDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "rules": {"type": "object"},
        },
    },
}


def list_schemas() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_INDEX_VERSION,
        "schemas": [
            {"id": schema_id, "draft": schema["$schema"]}
            for schema_id, schema in sorted(_SCHEMAS.items())
        ],
    }


def get_schema(schema_id: str) -> dict[str, Any]:
    if schema_id not in _SCHEMAS:
        from agent_lifecycle.contracts.errors import LifecycleError

        raise LifecycleError("unknown-schema", f"unknown schema: {schema_id}")
    return deepcopy(_SCHEMAS[schema_id])
