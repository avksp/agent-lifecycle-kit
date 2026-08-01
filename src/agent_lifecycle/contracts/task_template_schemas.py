"""Built-in JSON schemas for draft-only task template contracts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

TASK_TEMPLATE_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-task-template-library.v1": open_object_schema(
        "agent-task-template-library.v1",
        required=[
            "schemaVersion",
            "status",
            "enabledByDefault",
            "activationMode",
            "draftOnly",
            "requiresReview",
            "freezeBlocked",
            "defaultCommandFootprint",
            "templates",
            "productionPromotionClaimed",
            "libraryDigest",
        ],
        properties={
            "status": {"const": "OPTIONAL"},
            "enabledByDefault": {"const": False},
            "activationMode": {"const": "explicit-template-selection"},
            "draftOnly": {"const": True},
            "requiresReview": {"const": True},
            "freezeBlocked": {"const": True},
            "defaultCommandFootprint": {"type": "object"},
            "templates": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "libraryDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-task-template-library-validation.v1": open_object_schema(
        "agent-task-template-library-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "templateCount",
            "templateIds",
            "reports",
            "blockers",
            "libraryDigest",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "templateCount": {"type": "integer", "minimum": 0},
            "templateIds": {"type": "array", "items": {"type": "string"}},
            "reports": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "libraryDigest": {"type": ["string", "null"], "minLength": 64, "maxLength": 64},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-task-template-render.v1": open_object_schema(
        "agent-task-template-render.v1",
        required=[
            "schemaVersion",
            "status",
            "templateId",
            "path",
            "draftOnly",
            "requiresReview",
            "freezeBlocked",
            "qualityProfiles",
            "declaredPlaceholders",
            "substitutedPlaceholders",
            "content",
            "blockers",
            "productionPromotionClaimed",
            "renderDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "templateId": {"type": "string", "minLength": 1},
            "path": {"type": "string", "minLength": 1},
            "draftOnly": {"const": True},
            "requiresReview": {"const": True},
            "freezeBlocked": {"const": True},
            "qualityProfiles": {"type": "array", "items": {"type": "string"}},
            "declaredPlaceholders": {"type": "array", "items": {"type": "string"}},
            "substitutedPlaceholders": {"type": "array", "items": {"type": "string"}},
            "content": {"type": "string"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "renderDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}
