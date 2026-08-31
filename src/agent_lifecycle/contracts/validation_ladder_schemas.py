"""Closed schemas for validation selection and release-full evidence."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

VALIDATION_CHECK_CATALOG_SCHEMA = "agent-validation-check-catalog.v1"
VALIDATION_LADDER_PROFILE_SCHEMA = "agent-validation-ladder-profile.v1"
VALIDATION_SELECTION_SCHEMA = "agent-validation-selection.v1"
RELEASE_FULL_VALIDATION_RECEIPT_SCHEMA = "agent-release-full-validation-receipt.v1"

_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_STRING = {"type": "string", "minLength": 1}
_STRING_LIST = {"type": "array", "items": _STRING, "uniqueItems": True}
_DIGEST_LIST = {"type": "array", "items": deepcopy(_DIGEST), "uniqueItems": True}


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


_CHECK = _closed_object(
    required=["id", "commandDigest"],
    properties={"id": _STRING, "commandDigest": _DIGEST},
)

_MAPPING = _closed_object(
    required=["id", "pathPrefix", "level", "checkIds"],
    properties={
        "id": _STRING,
        "pathPrefix": _STRING,
        "level": {"enum": ["TASK_FAST", "TASK_ACCEPTANCE", "RELEASE_FULL"]},
        "checkIds": _STRING_LIST,
    },
)

VALIDATION_LADDER_SCHEMAS: dict[str, dict[str, Any]] = {
    VALIDATION_CHECK_CATALOG_SCHEMA: _closed_schema(
        VALIDATION_CHECK_CATALOG_SCHEMA,
        required=["checks", "catalogDigest"],
        properties={
            "checks": {"type": "array", "items": _CHECK},
            "catalogDigest": _DIGEST,
        },
    ),
    VALIDATION_LADDER_PROFILE_SCHEMA: _closed_schema(
        VALIDATION_LADDER_PROFILE_SCHEMA,
        required=["mappings", "additionalProtectedPathPrefixes", "profileDigest"],
        properties={
            "mappings": {"type": "array", "items": _MAPPING},
            "additionalProtectedPathPrefixes": _STRING_LIST,
            "profileDigest": _DIGEST,
        },
    ),
    VALIDATION_SELECTION_SCHEMA: _closed_schema(
        VALIDATION_SELECTION_SCHEMA,
        required=[
            "status",
            "disposition",
            "level",
            "selectedCheckIds",
            "matchedMappingIds",
            "reasons",
            "planDigest",
            "planLockDigest",
            "stateRevision",
            "sourceRevision",
            "currentTreeDigest",
            "profileDigest",
            "catalogDigest",
            "commandsExecuted",
            "stateWritten",
            "blockers",
            "selectionDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "disposition": {"enum": ["SELECTED", "BLOCKED"]},
            "level": {"enum": ["TASK_FAST", "TASK_ACCEPTANCE", "RELEASE_FULL", None]},
            "selectedCheckIds": _STRING_LIST,
            "matchedMappingIds": _STRING_LIST,
            "reasons": _STRING_LIST,
            "planDigest": _DIGEST,
            "planLockDigest": _DIGEST,
            "stateRevision": {"type": "integer", "minimum": 1},
            "sourceRevision": _STRING,
            "currentTreeDigest": _DIGEST,
            "profileDigest": {"oneOf": [_DIGEST, {"type": "null"}]},
            "catalogDigest": _DIGEST,
            "commandsExecuted": {"const": False},
            "stateWritten": {"const": False},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "selectionDigest": _DIGEST,
        },
    ),
    RELEASE_FULL_VALIDATION_RECEIPT_SCHEMA: _closed_schema(
        RELEASE_FULL_VALIDATION_RECEIPT_SCHEMA,
        required=[
            "status",
            "sourceRevision",
            "currentTreeDigest",
            "planDigest",
            "planLockDigest",
            "catalogDigest",
            "requiredCheckIds",
            "passedCheckIds",
            "gateEvidenceDigests",
            "completedAt",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "sourceRevision": _STRING,
            "currentTreeDigest": _DIGEST,
            "planDigest": _DIGEST,
            "planLockDigest": _DIGEST,
            "catalogDigest": _DIGEST,
            "requiredCheckIds": _STRING_LIST,
            "passedCheckIds": _STRING_LIST,
            "gateEvidenceDigests": _DIGEST_LIST,
            "completedAt": _STRING,
            "blockers": {"type": "array", "maxItems": 0},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
}

__all__ = [
    "RELEASE_FULL_VALIDATION_RECEIPT_SCHEMA",
    "VALIDATION_CHECK_CATALOG_SCHEMA",
    "VALIDATION_LADDER_PROFILE_SCHEMA",
    "VALIDATION_LADDER_SCHEMAS",
    "VALIDATION_SELECTION_SCHEMA",
]
