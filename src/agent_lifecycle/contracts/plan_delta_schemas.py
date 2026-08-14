"""Portable contracts for project principles and plan-delta reports."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

PROJECT_PRINCIPLES_SCHEMA = "agent-project-principles.v1"
PROJECT_PRINCIPLES_VALIDATION_SCHEMA = "agent-project-principles-validation.v1"
PLAN_DELTA_SCHEMA = "agent-plan-delta.v1"
PLAN_DELTA_VALIDATION_SCHEMA = "agent-plan-delta-validation.v1"

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_OPTIONAL_DIGEST = {"type": ["string", "null"], "minLength": 0, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}, "maxItems": 128}
_BOUNDED_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_BOUNDED_TEXT = {"type": "string", "minLength": 1, "maxLength": 2048}
_BOUNDED_LIST = {"type": "array", "items": _BOUNDED_TEXT, "maxItems": 32}


PLAN_DELTA_SCHEMAS: dict[str, dict[str, Any]] = {
    PROJECT_PRINCIPLES_SCHEMA: open_object_schema(
        PROJECT_PRINCIPLES_SCHEMA,
        required=[
            "schemaVersion",
            "principlesId",
            "revision",
            "entries",
            "authority",
            "source",
            "productionPromotionClaimed",
            "principlesDigest",
        ],
        properties={
            "principlesId": _BOUNDED_ID,
            "revision": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "entries": {"type": "array", "minItems": 1, "maxItems": 32, "items": {"type": "object"}},
            "authority": {"type": "object", "maxProperties": 8},
            "source": {"type": "object", "maxProperties": 8},
            "productionPromotionClaimed": {"const": False},
            "principlesDigest": _DIGEST,
        },
    ),
    PROJECT_PRINCIPLES_VALIDATION_SCHEMA: open_object_schema(
        PROJECT_PRINCIPLES_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "principlesDigest",
            "entryCount",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "principlesDigest": _OPTIONAL_DIGEST,
            "entryCount": {"type": "integer", "minimum": 0, "maximum": 32},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    PLAN_DELTA_SCHEMA: open_object_schema(
        PLAN_DELTA_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "before",
            "after",
            "lineage",
            "changes",
            "authorityImpact",
            "reviewRequired",
            "newLockRequired",
            "readOnly",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "deltaDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "BLOCKED"]},
            "before": {"type": "object", "maxProperties": 16},
            "after": {"type": "object", "maxProperties": 16},
            "lineage": {"type": "object", "maxProperties": 16},
            "changes": {"type": "object", "maxProperties": 32},
            "authorityImpact": {"type": "object", "maxProperties": 16},
            "reviewRequired": {"type": "boolean"},
            "newLockRequired": {"type": "boolean"},
            "readOnly": {"const": True},
            "blockers": _BLOCKERS,
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "deltaDigest": _DIGEST,
        },
    ),
    PLAN_DELTA_VALIDATION_SCHEMA: open_object_schema(
        PLAN_DELTA_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "deltaStatus",
            "reviewRequired",
            "newLockRequired",
            "blockers",
            "deltaDigest",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "deltaStatus": {"type": ["string", "null"]},
            "reviewRequired": {"type": "boolean"},
            "newLockRequired": {"type": "boolean"},
            "blockers": _BLOCKERS,
            "deltaDigest": _OPTIONAL_DIGEST,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}
