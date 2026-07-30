"""Built-in JSON schema definitions for a lifecycle contract domain."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

REVIEW_QUALITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-review-verdict.v1": _open_object_schema(
        "agent-review-verdict.v1",
        required=["schemaVersion", "overall", "dimensions", "routing"],
        properties={
            "overall": {"enum": ["ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"]},
            "dimensions": {"type": "object"},
            "routing": {"type": "object"},
        },
    ),
    "agent-review-verdict-validation.v1": _open_object_schema(
        "agent-review-verdict-validation.v1",
        required=["schemaVersion", "status", "overall", "failingDimensions", "warningDimensions", "nextAction", "blockers"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "overall": {"type": ["string", "null"]},
            "failingDimensions": {"type": "array", "items": {"type": "string"}},
            "warningDimensions": {"type": "array", "items": {"type": "string"}},
            "nextAction": {"type": ["string", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
        },
    ),
    "agent-review-routing-summary.v1": _open_object_schema(
        "agent-review-routing-summary.v1",
        required=["schemaVersion", "status", "overall", "nextAction", "failingDimensions", "warningDimensions", "dimensionStatus", "verdictDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "overall": {"type": ["string", "null"]},
            "nextAction": {"type": ["string", "null"]},
            "failingDimensions": {"type": "array", "items": {"type": "string"}},
            "warningDimensions": {"type": "array", "items": {"type": "string"}},
            "dimensionStatus": {"type": "object"},
            "verdictDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-optional-quality-pack.v1": _open_object_schema(
        "agent-optional-quality-pack.v1",
        required=[
            "schemaVersion",
            "packId",
            "status",
            "enabledByDefault",
            "activationMode",
            "commands",
            "productionPromotionClaimed",
        ],
        properties={
            "packId": {"type": "string", "minLength": 1},
            "status": {"const": "OPTIONAL"},
            "enabledByDefault": {"const": False},
            "activationMode": {"const": "opt-in"},
            "commands": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-optional-quality-pack-validation.v1": _open_object_schema(
        "agent-optional-quality-pack-validation.v1",
        required=["schemaVersion", "status", "packId", "commandCount", "defaultEnabled", "blockers", "productionPromotionClaimed"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packId": {"type": ["string", "null"]},
            "commandCount": {"type": "integer", "minimum": 0},
            "defaultEnabled": {"type": ["boolean", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
    "agent-behavior-check-fixture.v1": _open_object_schema(
        "agent-behavior-check-fixture.v1",
        required=["schemaVersion", "fixtureId", "expectedOutcome", "signals"],
        properties={
            "fixtureId": {"type": "string", "minLength": 1},
            "expectedOutcome": {"enum": ["PASS", "FAIL", "BLOCKED"]},
            "signals": {"type": "object"},
        },
    ),
    "agent-behavior-check-run.v1": _open_object_schema(
        "agent-behavior-check-run.v1",
        required=[
            "schemaVersion",
            "status",
            "packId",
            "fixtureCount",
            "passedExpectationCount",
            "failedExpectationCount",
            "checks",
            "blockers",
            "productionPromotionClaimed",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packId": {"type": ["string", "null"]},
            "fixtureCount": {"type": "integer", "minimum": 0},
            "passedExpectationCount": {"type": "integer", "minimum": 0},
            "failedExpectationCount": {"type": "integer", "minimum": 0},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
        },
    ),
}
