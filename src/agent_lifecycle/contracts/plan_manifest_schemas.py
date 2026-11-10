"""Closed schema definitions for the canonical plan manifest envelope."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.review_remedy_schemas import AUTHORITY_VERSION, REMEDY_SCHEMAS

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
    **REMEDY_SCHEMAS,
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
            "workstreams": {
                "type": "array",
                "items": {"type": "object", "properties": {"artifactPaths": {"$ref": "#/$defs/artifactPaths"}}},
            },
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
            "reviewRemedyAuthority": REMEDY_SCHEMAS[AUTHORITY_VERSION],
            "contextCheckpointPolicy": _OBJECT,
            "controllerGates": _OBJECT,
            "planReview": _OBJECT,
            "repositoryReferences": {"type": "array", "items": {"type": "object"}},
            "tierResolution": _OBJECT,
            "taskTemplates": _OBJECT,
            "compatibility": _OBJECT,
            "extensions": {"$ref": "#/$defs/extensions"},
            "immutableInput": _OBJECT,
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
    "artifactPaths": _closed_object_schema(
        "agent-plan-artifact-paths.v1",
        required=["result", "review"],
        include_schema_version=False,
        properties={"result": {"type": "string", "minLength": 1}, "review": {"type": "string", "minLength": 1}},
    ),
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
            "prerequisiteAcceptance": {
                "type": "object",
                "additionalProperties": False,
                "required": ["required", "dependencies"],
                "properties": {
                    "required": {"type": "boolean"},
                    "dependencies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["packageId", "sourceRevision", "evidencePath", "sha256"],
                            "properties": {
                                "packageId": {"type": "string", "minLength": 1},
                                "sourceRevision": {"type": "string", "minLength": 1},
                                "evidencePath": {"type": "string", "minLength": 1},
                                "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                            },
                        },
                    },
                },
            },
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
            },
        },
    },
}

DECISION_REQUIREMENT_SCHEMA = "agent-decision-research-requirement.v1"
DECISION_RECORD_SCHEMA = "agent-decision-research-record.v1"
DECISION_SCOPE = "FROZEN_CONTEXT_INPUTS"
DECISION_CAPS = {
    "maxInputs": (1, 8),
    "maxInputBytes": (1, 65536),
    "maxRecordBytes": (1, 262144),
    "maxEntryPoints": (1, 3),
    "maxAlternatives": (1, 3),
    "maxProbes": (0, 1),
    "maxReviewRounds": (1, 2),
}
DECISION_CRITERIA = {
    "S0": ("requirement-fit",),
    "S1": ("requirement-fit", "security"),
    "S2": ("requirement-fit", "architecture", "security", "resources", "feasibility"),
}


def _decision_object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties) if required is None else required,
    }


_DECISION_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_DECISION_TEXT = {"type": "string", "minLength": 1, "maxLength": 4096}
_DECISION_ID = {"type": "string", "minLength": 1, "maxLength": 128}
_DECISION_LEAF = {
    "type": "string",
    "minLength": 1,
    "maxLength": 255,
    "pattern": r"^[^/\\:\x00]+$",
}
_DECISION_PROFILE = _decision_object(
    {
        "tier": {"enum": list(DECISION_CRITERIA)},
        "requiredCriteria": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "items": _DECISION_ID,
        },
        **{name: {"type": "integer", "minimum": low, "maximum": high} for name, (low, high) in DECISION_CAPS.items()},
    }
)
_DECISION_INPUT = _decision_object(
    {
        "sourceId": _DECISION_ID,
        "path": _DECISION_LEAF,
        "sha256": _DECISION_DIGEST,
    }
)
_DECISION_RECORD_REF = _decision_object(
    {
        "path": _DECISION_LEAF,
        "sha256": _DECISION_DIGEST,
    }
)
_DECISION_REQUIREMENT_PROPERTIES = {
    "schemaVersion": {"const": DECISION_REQUIREMENT_SCHEMA},
    "scope": {"const": DECISION_SCOPE},
    "profile": _DECISION_PROFILE,
    "inputs": {
        "type": "array",
        "minItems": 1,
        "maxItems": 8,
        "items": _DECISION_INPUT,
    },
    "record": _DECISION_RECORD_REF,
    "scopeDigest": _DECISION_DIGEST,
    "inputDigest": _DECISION_DIGEST,
    "policyDigest": _DECISION_DIGEST,
}
_DECISION_ALTERNATIVE = _decision_object(
    {
        "id": _DECISION_ID,
        "kind": {"enum": ["NO_CHANGE", "SIMPLIFY", "REPLACE"]},
        "title": _DECISION_ID,
        "rationale": _DECISION_TEXT,
    }
)
_DECISION_ASSESSMENT = _decision_object(
    {
        "criterion": _DECISION_ID,
        "status": {"enum": ["ADDRESSED", "NOT_APPLICABLE"]},
        "rationale": _DECISION_TEXT,
        "sourceIds": {
            "type": "array",
            "maxItems": 8,
            "uniqueItems": True,
            "items": _DECISION_ID,
        },
    },
    required=["criterion", "status", "rationale"],
)
_DECISION_BUDGET = _decision_object(
    {
        "maxCommands": {"type": "integer", "minimum": 1, "maximum": 100},
        "maxActiveSeconds": {"type": "integer", "minimum": 1, "maximum": 3600},
        "reservedCommands": {"type": "integer", "minimum": 1, "maximum": 99},
        "usageStatus": {"enum": ["UNAVAILABLE", "DECLARED"]},
        "usedCommands": {"type": ["integer", "null"], "minimum": 0},
        "usedActiveSeconds": {"type": ["number", "null"], "minimum": 0},
    }
)
_DECISION_RECORD_PROPERTIES: dict[str, Any] = {
    "schemaVersion": {"const": DECISION_RECORD_SCHEMA},
    "scopeDigest": _DECISION_DIGEST,
    "inputDigest": _DECISION_DIGEST,
    "policyDigest": _DECISION_DIGEST,
    "ownerId": _DECISION_ID,
    "entryPoints": {
        "type": "array",
        "minItems": 1,
        "maxItems": 3,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1, "maxLength": 255},
    },
    "alternatives": {
        "type": "array",
        "minItems": 1,
        "maxItems": 3,
        "items": _DECISION_ALTERNATIVE,
    },
    "selectedAlternativeId": _DECISION_ID,
    "outcome": {"enum": ["KEEP", "SIMPLIFY", "REPLACE", "SPLIT", "STOP"]},
    "assessments": {
        "type": "array",
        "minItems": 1,
        "maxItems": 16,
        "items": _DECISION_ASSESSMENT,
    },
    "budget": _DECISION_BUDGET,
    "probeCount": {"type": "integer", "minimum": 0, "maximum": 1},
    "reviewRoundCount": {"type": "integer", "minimum": 1, "maximum": 2},
    "sourceOfTruth": {"const": False},
    "lifecycleAuthority": {"const": "none"},
    "productionPromotionClaimed": {"const": False},
    "optimalityClaimed": {"const": False},
    "evidencePackage": {"type": "object"},
}
for _schema_id, _properties, _required in (
    (
        DECISION_REQUIREMENT_SCHEMA,
        _DECISION_REQUIREMENT_PROPERTIES,
        list(_DECISION_REQUIREMENT_PROPERTIES),
    ),
    (
        DECISION_RECORD_SCHEMA,
        _DECISION_RECORD_PROPERTIES,
        [key for key in _DECISION_RECORD_PROPERTIES if key != "evidencePackage"],
    ),
):
    PLAN_MANIFEST_SCHEMAS[_schema_id] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _schema_id,
        **_decision_object(_properties, _required),
    }
PLAN_MANIFEST_SCHEMAS[MANIFEST_SCHEMA]["properties"]["workstreams"]["items"]["properties"]["decisionResearch"] = (
    PLAN_MANIFEST_SCHEMAS[DECISION_REQUIREMENT_SCHEMA]
)

__all__ = ["MANIFEST_SCHEMA", "MANIFEST_VALIDATION_SCHEMA", "PLAN_MANIFEST_SCHEMAS"]
