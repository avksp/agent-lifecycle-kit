"""Built-in JSON schemas for neutral host capability declarations."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

HOST_CAPABILITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-host-capability.v1": _open_object_schema(
        "agent-host-capability.v1",
        required=[
            "schemaVersion",
            "capabilityId",
            "adapterId",
            "host",
            "support",
            "transport",
            "evidencePolicy",
            "providerIdentityUsed",
        ],
        properties={
            "capabilityId": {"type": "string", "minLength": 1},
            "adapterId": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "support": {"enum": ["supported", "unsupported", "unknown"]},
            "transport": {"enum": ["acp", "host-local", "rpc-json", "skills", "unknown"]},
            "evidencePolicy": {"enum": ["probe-required", "not-claimed", "unknown"]},
            "providerIdentityUsed": {"const": False},
            "probe": {"type": ["object", "null"]},
            "invocationContract": {"type": ["object", "null"]},
        },
    ),
    "agent-host-capability-validation.v1": _open_object_schema(
        "agent-host-capability-validation.v1",
        required=["schemaVersion", "status", "capabilityCount", "blockers"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "capabilityCount": {"type": "integer", "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-acp-probe-receipt.v1": _open_object_schema(
        "agent-acp-probe-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "adapterId",
            "host",
            "capabilityId",
            "liveCallsStarted",
            "blockers",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL", "SKIPPED"]},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "capabilityId": {"const": "acp"},
            "liveCallsStarted": {"const": False},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    ),
}
