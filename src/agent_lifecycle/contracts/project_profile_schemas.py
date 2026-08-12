"""Portable contracts for project-local workflow profiles."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.schema_builders import open_object_schema
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS

PROJECT_PROFILE_SCHEMA = "agent-project-workflow-profile.v1"
EFFECTIVE_PROJECT_PROFILE_SCHEMA = "agent-effective-project-workflow-profile.v1"
GUIDED_ACTION_RECEIPT_SCHEMA = "agent-guided-action-receipt.v1"
PROJECT_PROFILE_BOUNDARY_SCHEMA = "agent-project-profile-boundary-validation.v1"

PROJECT_PROFILE_MODES = ("auto", "research", "plan", "review", "implement")
PROJECT_PROFILE_RISKS = ("auto", "S0", "S1", "S2")
PROJECT_PROFILE_MODEL_CLASSES = (
    "no-model",
    "budget",
    "local-compact",
    "standard-code",
    "local-standard-code",
    "strong-reasoning",
    "local-strong-review",
    "specialist-review",
)

PROJECT_PROFILE_STAGES = (
    "intake",
    "research",
    "planning",
    "review",
    "implementation",
    "audit",
    "finalization",
)

PROFILE_POLICY_KEYS = (
    "routingProfile",
    "riskPolicy",
    "baselineProfile",
    "hostModelProfile",
)

STAGE_SETTING_KEYS = (
    "mode",
    "risk",
    "modelClass",
    "reviewMesh",
    "minReviewers",
    "maxAttempts",
    "maxInvocations",
    "maxWallSeconds",
    "guidanceRef",
)

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}
_STAGE_SETTINGS = {
    "type": "object",
    "properties": {
        "mode": {"enum": list(PROJECT_PROFILE_MODES)},
        "risk": {"enum": list(PROJECT_PROFILE_RISKS)},
        "modelClass": {"enum": list(PROJECT_PROFILE_MODEL_CLASSES)},
        "reviewMesh": {"enum": ["off", *REVIEW_MESH_MODE_IDS]},
        "minReviewers": {"type": "integer", "minimum": 0, "maximum": 16},
        "maxAttempts": {"type": "integer", "minimum": 1, "maximum": 10},
        "maxInvocations": {"type": "integer", "minimum": 1, "maximum": 100},
        "maxWallSeconds": {"type": "integer", "minimum": 1, "maximum": 86400},
        "guidanceRef": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}


PROJECT_PROFILE_SCHEMAS: dict[str, dict[str, Any]] = {
    PROJECT_PROFILE_SCHEMA: open_object_schema(
        PROJECT_PROFILE_SCHEMA,
        required=[
            "schemaVersion",
            "profileId",
            "defaultAdapter",
            "defaultMode",
            "defaultRisk",
            "policies",
            "stages",
        ],
        properties={
            "profileId": {"type": "string", "minLength": 1, "maxLength": 128},
            "defaultAdapter": {"type": ["string", "null"], "minLength": 1},
            "defaultMode": {"enum": list(PROJECT_PROFILE_MODES)},
            "defaultRisk": {"enum": list(PROJECT_PROFILE_RISKS)},
            "policies": {
                "type": "object",
                "properties": {key: {"type": ["string", "null"]} for key in PROFILE_POLICY_KEYS},
                "additionalProperties": False,
            },
            "stages": {
                "type": "object",
                "propertyNames": {"enum": list(PROJECT_PROFILE_STAGES)},
                "additionalProperties": _STAGE_SETTINGS,
            },
            "productionPromotionClaimed": {"const": False},
        },
    ),
    EFFECTIVE_PROJECT_PROFILE_SCHEMA: open_object_schema(
        EFFECTIVE_PROJECT_PROFILE_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "profileId",
            "sourceProfileDigest",
            "defaultAdapter",
            "defaultMode",
            "defaultRisk",
            "policies",
            "stages",
            "authority",
            "blockers",
            "productionPromotionClaimed",
            "effectiveProfileDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "profileId": {"type": "string", "minLength": 1},
            "sourceProfileDigest": _DIGEST,
            "defaultAdapter": {"type": ["string", "null"], "minLength": 1},
            "defaultMode": {"enum": list(PROJECT_PROFILE_MODES)},
            "defaultRisk": {"enum": ["S0", "S1", "S2"]},
            "policies": {"type": "object"},
            "stages": {"type": "object"},
            "authority": {"type": "object"},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "effectiveProfileDigest": _DIGEST,
        },
    ),
    GUIDED_ACTION_RECEIPT_SCHEMA: open_object_schema(
        GUIDED_ACTION_RECEIPT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "startReceipt",
            "effectiveProfile",
            "profileDigest",
            "stageGuidance",
            "nextAction",
            "blockers",
            "modelCallsStarted",
            "hostLaunchStarted",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["READY", "REVIEW_REQUIRED", "BLOCKED", "PASS"]},
            "startReceipt": {"type": "object"},
            "effectiveProfile": {"type": "object"},
            "profileDigest": _DIGEST,
            "stageGuidance": {"type": "object"},
            "nextAction": {"type": "object"},
            "blockers": _BLOCKERS,
            "modelCallsStarted": {"const": False},
            "hostLaunchStarted": {"type": "boolean"},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    PROJECT_PROFILE_BOUNDARY_SCHEMA: open_object_schema(
        PROJECT_PROFILE_BOUNDARY_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "checkedFiles",
            "checks",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "checkedFiles": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}
