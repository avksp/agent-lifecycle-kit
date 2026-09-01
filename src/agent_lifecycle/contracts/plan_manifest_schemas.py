"""Closed schema definitions for the canonical plan manifest envelope."""

from __future__ import annotations

from typing import Any

MANIFEST_SCHEMA = "agent-plan-manifest.v1"
MANIFEST_VALIDATION_SCHEMA = "agent-plan-manifest-validation.v1"


def _closed_object_schema(
    schema_id: str,
    *,
    required: list[str],
    properties: dict[str, Any],
    include_schema_version: bool = True,
) -> dict[str, Any]:
    fields = {"schemaVersion": {"const": schema_id}} if include_schema_version else {}
    fields.update(properties)
    required_fields = (["schemaVersion"] if include_schema_version else []) + list(required)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": schema_id,
        "type": "object",
        "additionalProperties": False,
        "required": required_fields,
        "properties": fields,
    }


_STRING_LIST = {"type": "array", "items": {"type": "string"}}
_OBJECT = {"type": "object"}


PLAN_MANIFEST_SCHEMAS: dict[str, dict[str, Any]] = {
    MANIFEST_SCHEMA: _closed_object_schema(
        MANIFEST_SCHEMA,
        required=["status", "planRevision", "package"],
        properties={
            "status": {"enum": ["DRAFT", "REOPENED", "FROZEN"]},
            "planRevision": {"type": "integer", "minimum": 1},
            "package": {"$ref": "#/$defs/package"},
            "planFiles": _STRING_LIST,
            "packageIntegrity": {"$ref": "#/$defs/packageIntegrity"},
            "author": {"anyOf": [{"type": "string"}, {"$ref": "#/$defs/author"}]},
            "baseRevision": {"$ref": "#/$defs/baseRevision"},
            "importState": _OBJECT,
            "externalImport": _OBJECT,
            "specification": _OBJECT,
            "readOnly": _STRING_LIST,
            "forbiddenWrites": _STRING_LIST,
            "leadOwned": {"type": "array", "items": {"type": "object"}},
            "workstreams": {"type": "array", "items": {"type": "object"}},
            "acceptance": _OBJECT,
            "acceptanceCriteria": {"type": "array", "items": {"type": "object"}},
            "validation": _OBJECT,
            "orchestration": _OBJECT,
            "implementationAudit": {"$ref": "#/$defs/implementationAudit"},
            "developerOverview": {"type": ["string", "null"]},
            "releaseTarget": _OBJECT,
            "releaseImpact": {"type": ["string", "object", "null"]},
            "nonGoals": _STRING_LIST,
            "finalAuditGates": {"type": "array", "items": {"type": ["string", "object"]}},
            "securityGates": {"type": ["array", "object"]},
            "sandbox": _OBJECT,
            "runtimePolicy": _OBJECT,
            "budgetPolicy": _OBJECT,
            "budgets": _OBJECT,
            "contextLimits": _OBJECT,
            "dependsOn": _STRING_LIST,
            "reviewMesh": _OBJECT,
            "contextCheckpointPolicy": _OBJECT,
            "controllerGates": _OBJECT,
            "planReview": _OBJECT,
            "repositoryReferences": {"type": "array", "items": {"type": "object"}},
            "tierResolution": _OBJECT,
            "taskTemplates": _OBJECT,
            "compatibility": _OBJECT,
            "extensions": {"$ref": "#/$defs/extensions"},
        },
    ),
    MANIFEST_VALIDATION_SCHEMA: _closed_object_schema(
        MANIFEST_VALIDATION_SCHEMA,
        required=["status", "packageId", "planRevision", "blockers", "validationDigest"],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "packageId": {"type": ["string", "null"]},
            "planRevision": {"type": ["integer", "null"], "minimum": 0},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "legacyCompatibility": {"type": "boolean"},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}

PLAN_MANIFEST_SCHEMAS[MANIFEST_SCHEMA]["$defs"] = {
    "package": _closed_object_schema(
        "agent-plan-package.v1",
        required=["id"],
        include_schema_version=False,
        properties={
            "id": {"type": "string", "minLength": 1},
            "title": {"type": "string"},
            "workspaceRoot": {"type": "string"},
            "artifactRoot": {"type": "string"},
            "root": {"type": "string"},
            "planArtifactRoot": {"type": "string"},
        },
    ),
    "author": _closed_object_schema(
        "agent-plan-author.v1",
        required=["id"],
        include_schema_version=False,
        properties={
            "id": {"type": "string", "minLength": 1},
            "surface": {"type": "string"},
            "runId": {"type": "string"},
        },
    ),
    "baseRevision": _closed_object_schema(
        "agent-plan-base-revision.v1",
        required=["ref", "sha"],
        include_schema_version=False,
        properties={"ref": {"type": "string"}, "sha": {"type": "string"}},
    ),
    "packageIntegrity": _closed_object_schema(
        "agent-plan-package-integrity.v1",
        required=["required", "lockSchemaVersion", "inventorySource", "undeclaredTopLevelFiles"],
        include_schema_version=False,
        properties={
            "required": {"type": "boolean"},
            "lockSchemaVersion": {"enum": ["agent-plan-lock.v1", "agent-plan-lock.v2"]},
            "inventorySource": {"const": "planFiles"},
            "undeclaredTopLevelFiles": {"const": "reject"},
            "allowedUnlistedFiles": _STRING_LIST,
        },
    ),
    "implementationAudit": _closed_object_schema(
        "agent-plan-implementation-audit-policy.v1",
        required=["required", "finalRequired"],
        include_schema_version=False,
        properties={
            "required": {"type": "boolean"},
            "finalRequired": {"type": "boolean"},
        },
    ),
    "extensions": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "agent-plan-extensions.v1",
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "securityAnalysis": {
                "type": "object",
                "required": ["profileId", "activation", "implementationAudit"],
                "additionalProperties": True,
                "properties": {
                    "profileId": {"const": "security-analysis.v1"},
                    "activation": {"enum": ["read-only-by-default", "explicit-plan-opt-in"]},
                    "implementationAudit": {"type": "object"},
                    "verificationEvidence": {"type": "object"},
                },
            }
        },
    },
}

__all__ = ["MANIFEST_SCHEMA", "MANIFEST_VALIDATION_SCHEMA", "PLAN_MANIFEST_SCHEMAS"]
