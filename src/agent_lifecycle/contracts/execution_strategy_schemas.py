"""Built-in schemas for provider-neutral execution strategy receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema

STAGE_BINDING_DIGEST_FIELDS = (
    "selectedBindingDigest",
    "registrySha256",
    "hostModelProfileSha256",
    "hostBindingDigest",
    "launchProfileSha256",
    "parameterSupportSha256",
    "versionQualificationSha256",
    "parameterDigest",
)
STAGE_BINDING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["stage", "modelClass", *STAGE_BINDING_DIGEST_FIELDS],
    "properties": {
        "stage": {"enum": ["intake", "research", "planning", "review", "implementation", "audit", "finalization"]},
        "modelClass": {
            "enum": [
                "budget",
                "local-compact",
                "standard-code",
                "local-standard-code",
                "strong-reasoning",
                "local-strong-review",
                "specialist-review",
            ]
        },
        **{key: {"type": "string", "pattern": "^[0-9a-f]{64}$"} for key in STAGE_BINDING_DIGEST_FIELDS},
    },
}

EXECUTION_STRATEGY_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-execution-strategy.v1": open_object_schema(
        "agent-execution-strategy.v1",
        required=[
            "schemaVersion",
            "status",
            "lineage",
            "quality",
            "phaseRoutes",
            "packet",
            "reviewMesh",
            "resourceCaps",
            "usageEvidence",
            "sourceDecisionDigests",
            "authority",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "strategyDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "BLOCKED"]},
            "lineage": {"type": "object"},
            "quality": {"type": "object"},
            "phaseRoutes": {"type": "array", "items": {"type": "object"}},
            "modelRoute": {"type": "object"},
            "stageBinding": STAGE_BINDING_SCHEMA,
            "packet": {"type": "object"},
            "reviewMesh": {"type": "object"},
            "resourceCaps": {"type": "object"},
            "usageEvidence": {"type": "object"},
            "sourceDecisionDigests": {"type": "object"},
            "authority": {"type": "object"},
            "adoptionBinding": {"type": "object"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "strategyDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-execution-strategy-validation.v1": open_object_schema(
        "agent-execution-strategy-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "strategyStatus",
            "qualityFloorPreserved",
            "blockers",
            "strategyDigest",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "strategyStatus": {"enum": ["PASS", "BLOCKED"]},
            "qualityFloorPreserved": {"type": "boolean"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "strategyDigest": {"type": ["string", "null"]},
            "productionPromotionClaimed": {"const": False},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}
