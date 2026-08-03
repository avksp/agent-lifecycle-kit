"""Built-in JSON schema definitions for a lifecycle contract domain."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema as _open_object_schema

PLAN_CONTRACT_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-plan-completeness-profile.v1": _open_object_schema(
        "agent-plan-completeness-profile.v1",
        required=["schemaVersion", "profileId", "profiles", "profileDigest"],
        properties={
            "profileId": {"type": "string", "minLength": 1},
            "profiles": {"type": "object"},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-plan-completeness-profile-validation.v1": _open_object_schema(
        "agent-plan-completeness-profile-validation.v1",
        required=["schemaVersion", "status", "profileId", "blockers", "profileDigest", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "profileId": {"type": ["string", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "profileDigest": {
                "anyOf": [
                    {"type": "string", "minLength": 64, "maxLength": 64},
                    {"type": "null"},
                ],
            },
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-plan-completeness-validation.v1": _open_object_schema(
        "agent-plan-completeness-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "packageId",
            "tier",
            "requiredChecks",
            "blockers",
            "profileDigest",
            "planDigest",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packageId": {"type": ["string", "null"]},
            "tier": {"enum": ["S0", "S1", "S2"]},
            "requiredChecks": {"type": "array", "items": {"type": "string"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "planDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-plan-reference-validation.v1": _open_object_schema(
        "agent-plan-reference-validation.v1",
        required=["schemaVersion", "status", "packageId", "referenceCount", "repositoryIds", "blockers", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packageId": {"type": ["string", "null"]},
            "referenceCount": {"type": "integer", "minimum": 0},
            "repositoryIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-plan-snapshot.v1": _open_object_schema(
        "agent-plan-snapshot.v1",
        required=[
            "schemaVersion",
            "status",
            "packageId",
            "planRevision",
            "sourceDigest",
            "baseRevision",
            "specificationDigest",
            "acceptanceDigest",
            "repositoryReferencesDigest",
            "referenceValidationDigest",
            "immutable",
            "snapshotDigest",
        ],
        properties={
            "status": {"const": "PASS"},
            "packageId": {"type": ["string", "null"]},
            "planRevision": {"type": ["integer", "null"], "minimum": 0},
            "sourceDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "baseRevision": {"type": "object"},
            "specificationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "acceptanceDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "repositoryReferencesDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "referenceValidationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "immutable": {"const": True},
            "snapshotDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-plan-reconciliation.v1": _open_object_schema(
        "agent-plan-reconciliation.v1",
        required=["schemaVersion", "status", "classification", "packageId", "snapshotDigest", "currentDigest", "blockers", "reconciliationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "classification": {"enum": ["MATCH", "REQUIRES_NEW_PLAN", "BLOCKED"]},
            "packageId": {"type": ["string", "null"]},
            "snapshotDigest": {"type": ["string", "null"]},
            "currentDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "reconciliationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-plan-handoff.v1": _open_object_schema(
        "agent-plan-handoff.v1",
        required=[
            "schemaVersion",
            "status",
            "packageId",
            "planRevision",
            "planStatus",
            "repositoryReferences",
            "referenceValidation",
            "workstreams",
            "acceptanceIds",
            "omitted",
            "sourceDigest",
            "estimatedTokens",
            "targetTokens",
            "handoffDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packageId": {"type": ["string", "null"]},
            "planRevision": {"type": ["integer", "null"], "minimum": 0},
            "planStatus": {"type": ["string", "null"]},
            "snapshotDigest": {"type": ["string", "null"]},
            "repositoryReferences": {"type": "array", "items": {"type": "object"}},
            "referenceValidation": {"type": "object"},
            "workstreams": {"type": "array", "items": {"type": "object"}},
            "acceptanceIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "omitted": {"type": "object"},
            "sourceDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "estimatedTokens": {"type": "integer", "minimum": 1},
            "targetTokens": {"type": "integer", "minimum": 1},
            "handoffDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),}
