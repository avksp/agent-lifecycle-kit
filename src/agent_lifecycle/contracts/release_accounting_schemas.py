"""Schemas for bounded release resource accounting."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}

RELEASE_ACCOUNTING_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-release-accounting-source.v1": open_object_schema(
        "agent-release-accounting-source.v1",
        required=[
            "schemaVersion",
            "status",
            "releaseId",
            "entryCount",
            "entries",
            "provenance",
            "blockers",
            "productionPromotionClaimed",
            "sourceDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "releaseId": {"type": "string", "minLength": 1, "maxLength": 256},
            "entryCount": {"type": "integer", "minimum": 1, "maximum": 1024},
            "entries": {"type": "array", "minItems": 1, "maxItems": 1024, "items": {"type": "object"}},
            "provenance": {"type": "object"},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "sourceDigest": _DIGEST,
        },
    ),
    "agent-release-accounting.v1": open_object_schema(
        "agent-release-accounting.v1",
        required=[
            "schemaVersion",
            "status",
            "releaseId",
            "generatedBy",
            "sourceArtifacts",
            "entryCount",
            "entries",
            "views",
            "categoryTotals",
            "totals",
            "exclusions",
            "provenance",
            "blockers",
            "liveCallsStarted",
            "productionPromotionClaimed",
            "accountingDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "releaseId": {"type": "string", "minLength": 1, "maxLength": 256},
            "generatedBy": {"const": "agent-lifecycle metrics release-accounting"},
            "sourceArtifacts": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"type": "object"}},
            "entryCount": {"type": "integer", "minimum": 1, "maximum": 1024},
            "entries": {"type": "array", "minItems": 1, "maxItems": 1024, "items": {"type": "object"}},
            "views": {"type": "object"},
            "categoryTotals": {"type": "object"},
            "totals": {"type": "object"},
            "exclusions": {"type": "array", "items": {"type": "object"}},
            "provenance": {"type": "object"},
            "blockers": _BLOCKERS,
            "liveCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "accountingDigest": _DIGEST,
        },
    ),
    "agent-release-accounting-validation.v1": open_object_schema(
        "agent-release-accounting-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "releaseId",
            "entryCount",
            "blockers",
            "accountingDigest",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "releaseId": {"type": ["string", "null"]},
            "entryCount": {"type": "integer", "minimum": 0},
            "blockers": _BLOCKERS,
            "accountingDigest": {"type": ["string", "null"], "minLength": 64, "maxLength": 64},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
    "agent-release-accounting-generation.v1": open_object_schema(
        "agent-release-accounting-generation.v1",
        required=[
            "schemaVersion",
            "status",
            "outputPath",
            "outputBytes",
            "accountingDigest",
            "validation",
            "liveCallsStarted",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "outputPath": {"type": "string", "minLength": 1},
            "outputBytes": {"type": "integer", "minimum": 1},
            "accountingDigest": _DIGEST,
            "validation": {"type": "object"},
            "liveCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
}
