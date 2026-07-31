"""Built-in JSON schemas for usage/session export contracts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

USAGE_EXPORT_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-usage-export.v1": open_object_schema(
        "agent-usage-export.v1",
        required=[
            "schemaVersion",
            "status",
            "generatedBy",
            "sourceArtifacts",
            "entries",
            "totals",
            "blockers",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "generatedBy": {"type": "string"},
            "sourceArtifacts": {"type": "array", "items": {"type": "object"}},
            "lineage": {"type": "object"},
            "entries": {"type": "array", "items": {"type": "object"}},
            "totals": {"type": "object"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-usage-export-validation.v1": open_object_schema(
        "agent-usage-export-validation.v1",
        required=["schemaVersion", "status", "entryCount", "totals", "blockers", "exportDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "entryCount": {"type": "integer", "minimum": 0},
            "totals": {"type": "object"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "exportDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-usage-export-generation.v1": open_object_schema(
        "agent-usage-export-generation.v1",
        required=[
            "schemaVersion",
            "status",
            "format",
            "outputPath",
            "outputBytes",
            "exportDigest",
            "validation",
            "liveCallsStarted",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "format": {"enum": ["json", "table"]},
            "outputPath": {"type": "string"},
            "outputBytes": {"type": "integer", "minimum": 0},
            "exportDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "validation": {"type": "object"},
            "liveCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
        },
    ),
}
