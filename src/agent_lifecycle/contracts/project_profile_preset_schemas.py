"""Portable contracts for project workflow preset data and operations."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

PROJECT_PROFILE_PRESET_SCHEMA = "agent-project-workflow-preset.v1"
PROJECT_PROFILE_PRESET_VALIDATION_SCHEMA = "agent-project-workflow-preset-validation.v1"
PROJECT_PROFILE_PRESET_LIST_SCHEMA = "agent-project-workflow-preset-list.v1"
PROJECT_PROFILE_PRESET_OPERATION_SCHEMA = "agent-project-workflow-preset-operation.v1"
PROJECT_PROFILE_PRESET_RENDER_SCHEMA = "agent-project-workflow-preset-render-receipt.v1"

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_OPTIONAL_DIGEST = {"type": ["string", "null"], "minLength": 0, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 128}
_SAFETY = {
    "modelCallsStarted": {"const": False},
    "hostLaunchStarted": {"const": False},
    "productionPromotionClaimed": {"const": False},
}

PROJECT_PROFILE_PRESET_SCHEMAS: dict[str, dict[str, Any]] = {
    PROJECT_PROFILE_PRESET_SCHEMA: open_object_schema(
        PROJECT_PROFILE_PRESET_SCHEMA,
        required=[
            "schemaVersion",
            "presetId",
            "presetVersion",
            "title",
            "description",
            "defaultMode",
            "defaultRisk",
            "reviewMesh",
            "implementationAuthority",
            "stages",
            "source",
            "productionPromotionClaimed",
            "presetDigest",
        ],
        properties={
            "presetId": {"type": "string", "minLength": 1, "maxLength": 64},
            "presetVersion": {"type": "string", "minLength": 1, "maxLength": 32},
            "title": {"type": "string", "minLength": 1, "maxLength": 160},
            "description": {"type": "string", "minLength": 1, "maxLength": 2048},
            "defaultMode": {"enum": ["auto", "research", "plan", "review", "implement"]},
            "defaultRisk": {"enum": ["auto", "S0", "S1", "S2"]},
            "reviewMesh": {"type": "string", "minLength": 1, "maxLength": 96},
            "implementationAuthority": {"enum": ["excluded", "requires-frozen-plan"]},
            "stages": {"type": "object", "maxProperties": 7},
            "source": {"const": "built-in"},
            "productionPromotionClaimed": {"const": False},
            "presetDigest": _DIGEST,
        },
    ),
    PROJECT_PROFILE_PRESET_VALIDATION_SCHEMA: open_object_schema(
        PROJECT_PROFILE_PRESET_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "presetId",
            "presetDigest",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "presetId": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "presetDigest": _OPTIONAL_DIGEST,
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    PROJECT_PROFILE_PRESET_LIST_SCHEMA: open_object_schema(
        PROJECT_PROFILE_PRESET_LIST_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "presets",
            "productionPromotionClaimed",
            "resultDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "presets": {"type": "array", "maxItems": 8, "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "resultDigest": _DIGEST,
        },
    ),
    PROJECT_PROFILE_PRESET_OPERATION_SCHEMA: open_object_schema(
        PROJECT_PROFILE_PRESET_OPERATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operation",
            "preset",
            "validation",
            "productionPromotionClaimed",
            "resultDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "operation": {"enum": ["inspect", "validate"]},
            "preset": {"type": "object"},
            "validation": {"type": "object"},
            "productionPromotionClaimed": {"const": False},
            "resultDigest": _DIGEST,
            **_SAFETY,
        },
    ),
    PROJECT_PROFILE_PRESET_RENDER_SCHEMA: open_object_schema(
        PROJECT_PROFILE_PRESET_RENDER_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operation",
            "presetId",
            "outputPath",
            "profile",
            "profileDigest",
            "explicitOutputPath",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "operation": {"const": "render"},
            "presetId": {"type": "string", "minLength": 1},
            "outputPath": {"type": "string", "minLength": 1},
            "profile": {"type": "object"},
            "profileDigest": _DIGEST,
            "explicitOutputPath": {"const": True},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
            **_SAFETY,
        },
    ),
}
