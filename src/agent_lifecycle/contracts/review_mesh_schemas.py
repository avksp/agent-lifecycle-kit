"""Built-in JSON schemas for optional Review Mesh contracts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.schema_builders import open_object_schema

REVIEW_MESH_MODE_IDS = (
    "leader-draft-multi-review",
    "parallel-research-synthesis",
    "implementation-audit-panel",
)

RAW_REVIEW_VERSION = "reviewer-output.v1"
RAW_REVIEW_STATUSES = ("PASS", "FAIL", "SKIPPED")
RESPONSE_CONTRACT_VERSION = "agent-review-response-contract.v1"


def raw_reviewer_schema() -> dict[str, Any]:
    """Describe the public raw payload, never the normalized mesh result."""
    return open_object_schema(
        RAW_REVIEW_VERSION,
        required=["schemaVersion", "status", "findings"],
        properties={
            "status": {"enum": list(RAW_REVIEW_STATUSES)},
            "findings": {"type": "array", "items": {"type": "object"}},
            "budgetUsage": {"type": "object"},
            "sessionUsage": {"type": "object", "description": "Untrusted observation; qualified route context is separate"},
            "commandOutcomes": {"type": "array", "items": {"type": "object"}},
        },
    )


def build_response_contract(
    extensions: dict[str, Any] | None = None,
    *,
    raw_version: str = RAW_REVIEW_VERSION,
) -> dict[str, Any]:
    """Generate only supported typed constraints; this is not a schema engine."""
    if raw_version != RAW_REVIEW_VERSION:
        raise LifecycleError("review-response-version-unsupported", "Unsupported raw response version")
    selected = {} if extensions is None else extensions
    if type(selected) is not dict or set(selected).difference({"coverage"}):
        raise LifecycleError("review-response-extension-unsupported", "Unsupported response extension")
    schema = raw_reviewer_schema()
    schema["required"] += ["contractDigest", "subjectDigest", "assignmentDigest"]
    for field in ("contractDigest", "subjectDigest", "assignmentDigest"):
        schema["properties"][field] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    normalized = {}
    if "coverage" in selected:
        extension = selected["coverage"]
        if type(extension) is not dict or set(extension) != {"type", "paths"} or extension["type"] != "array":
            raise LifecycleError("review-response-extension-unsupported", "Coverage requires array type and paths")
        paths = extension["paths"]
        if type(paths) is not list or len(paths) > 256:
            raise LifecycleError("review-response-coverage-invalid", "Coverage paths must be bounded")
        names = [normalize_repo_path(path) for path in paths]
        if len(set(names)) != len(names):
            raise LifecycleError("review-response-coverage-invalid", "Coverage paths must be unique")
        names = sorted(names)
        normalized["coverage"] = {"type": "array", "paths": names}
        items: dict[str, Any] = {"type": "string", "minLength": 1}
        if names:
            items["enum"] = names
        schema["properties"]["coverage"] = {
            "type": "array",
            "items": items,
            "uniqueItems": True,
            "minItems": len(names),
            "maxItems": len(names),
        }
        schema["required"].append("coverage")
    body = {
        "schemaVersion": RESPONSE_CONTRACT_VERSION,
        "rawSchemaVersion": raw_version,
        "extensions": normalized,
        "schema": schema,
    }
    return {**body, "contractDigest": canonical_digest(body)}


def require_response_contract(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise LifecycleError("review-response-contract-invalid", "Response contract is required")
    expected = build_response_contract(value.get("extensions"), raw_version=value.get("rawSchemaVersion", ""))
    if canonical_digest(value) != canonical_digest(expected):
        raise LifecycleError("review-response-contract-mismatch", "Instructions and collector contracts differ")
    return expected


REVIEW_MESH_SCHEMAS: dict[str, dict[str, Any]] = {
    "agent-review-mesh-profile.v1": open_object_schema(
        "agent-review-mesh-profile.v1",
        required=[
            "schemaVersion",
            "profileId",
            "status",
            "enabledByDefault",
            "activationMode",
            "modes",
            "defaultMode",
            "advisoryByDefault",
            "blockingRequiresPlanOptIn",
            "requiresExplicitActivation",
            "budgetUnits",
            "budgetCap",
            "independencePolicy",
            "reviewerModelClasses",
            "crossCheckProfile",
            "concreteProviderModelNamesInPortableContract",
            "productionPromotionClaimed",
            "profileDigest",
        ],
        properties={
            "profileId": {"type": "string", "minLength": 1},
            "status": {"const": "OPTIONAL"},
            "enabledByDefault": {"const": False},
            "activationMode": {"const": "opt-in"},
            "modes": {"type": "array", "items": {"enum": list(REVIEW_MESH_MODE_IDS)}},
            "defaultMode": {"enum": list(REVIEW_MESH_MODE_IDS)},
            "advisoryByDefault": {"const": True},
            "blockingRequiresPlanOptIn": {"const": True},
            "requiresExplicitActivation": {"const": True},
            "liveCallsAllowed": {"type": "boolean"},
            "budgetUnits": {"const": "tokens-and-resources"},
            "budgetCap": {"type": "object"},
            "independencePolicy": {"type": "object"},
            "reviewerModelClasses": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "crossCheckProfile": {"type": "object"},
            "concreteProviderModelNamesInPortableContract": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-review-mesh-assignment.v1": open_object_schema(
        "agent-review-mesh-assignment.v1",
        required=[
            "schemaVersion",
            "assignmentId",
            "profileId",
            "profileDigest",
            "mode",
            "phase",
            "subject",
            "reviewer",
            "budgetCap",
            "blocking",
            "advisory",
            "productionPromotionClaimed",
            "assignmentDigest",
        ],
        properties={
            "assignmentId": {"type": "string", "minLength": 1},
            "profileId": {"type": "string", "minLength": 1},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "mode": {"enum": list(REVIEW_MESH_MODE_IDS)},
            "phase": {"type": "string", "minLength": 1},
            "subject": {"type": "object"},
            "reviewer": {"type": "object"},
            "budgetCap": {"type": "object"},
            "blocking": {"type": "boolean"},
            "advisory": {"type": "boolean"},
            "evidenceIds": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "independenceRequirement": {"type": ["object", "null"]},
            "productionPromotionClaimed": {"const": False},
            "assignmentDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-review-mesh-result.v1": open_object_schema(
        "agent-review-mesh-result.v1",
        required=[
            "schemaVersion",
            "status",
            "resultId",
            "assignmentId",
            "profileId",
            "profileDigest",
            "mode",
            "phase",
            "subject",
            "reviewer",
            "findings",
            "budgetUsage",
            "independence",
            "crossCheckReceipt",
            "blockers",
            "productionPromotionClaimed",
            "resultDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL", "SKIPPED"]},
            "resultId": {"type": "string", "minLength": 1},
            "assignmentId": {"type": "string", "minLength": 1},
            "profileId": {"type": "string", "minLength": 1},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "mode": {"enum": list(REVIEW_MESH_MODE_IDS)},
            "phase": {"type": "string", "minLength": 1},
            "subject": {"type": "object"},
            "reviewer": {"type": "object"},
            "independenceRequirement": {"type": ["object", "null"]},
            "findings": {"type": "array", "items": {"type": "object"}},
            "budgetUsage": {"type": "object"},
            "budgetUsageStatus": {"enum": ["UNAVAILABLE"]},
            "independence": {"type": "object"},
            "crossCheckReceipt": {"type": ["object", "null"]},
            "independentEvidence": {"type": ["object", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "resultDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-review-mesh-synthesis.v1": open_object_schema(
        "agent-review-mesh-synthesis.v1",
        required=[
            "schemaVersion",
            "status",
            "profileId",
            "profileDigest",
            "mode",
            "subject",
            "resultDigests",
            "agreement",
            "conflicts",
            "acceptedFindings",
            "rejectedFindings",
            "unresolvedFindings",
            "productionPromotionClaimed",
            "synthesisDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL", "INCONCLUSIVE"]},
            "profileId": {"type": "string", "minLength": 1},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "mode": {"enum": list(REVIEW_MESH_MODE_IDS)},
            "subject": {"type": "object"},
            "resultDigests": {"type": "array", "items": {"type": "string", "minLength": 64, "maxLength": 64}},
            "agreement": {"type": "array", "items": {"type": "object"}},
            "conflicts": {"type": "array", "items": {"type": "object"}},
            "acceptedFindings": {"type": "array", "items": {"type": "object"}},
            "rejectedFindings": {"type": "array", "items": {"type": "object"}},
            "unresolvedFindings": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "synthesisDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-review-mesh-quorum-receipt.v1": open_object_schema(
        "agent-review-mesh-quorum-receipt.v1",
        required=[
            "schemaVersion",
            "status",
            "profileId",
            "profileDigest",
            "mode",
            "subject",
            "quorumPolicy",
            "reviewerCount",
            "requiredRolesSatisfied",
            "quorumSatisfied",
            "blockingFindingsUnresolved",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL", "SKIPPED"]},
            "profileId": {"type": "string", "minLength": 1},
            "profileDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "mode": {"enum": list(REVIEW_MESH_MODE_IDS)},
            "subject": {"type": "object"},
            "quorumPolicy": {"type": "object"},
            "reviewerCount": {"type": "integer", "minimum": 0},
            "requiredRolesSatisfied": {"type": "boolean"},
            "quorumSatisfied": {"type": "boolean"},
            "blockingFindingsUnresolved": {"type": "boolean"},
            "independenceRequirement": {"type": ["object", "null"]},
            "independentEvidence": {"type": "array", "items": {"type": "object"}},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    "agent-review-mesh-quorum-validation.v1": open_object_schema(
        "agent-review-mesh-quorum-validation.v1",
        required=[
            "schemaVersion",
            "status",
            "profileId",
            "mode",
            "quorumSatisfied",
            "blockers",
            "receiptDigest",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "profileId": {"type": ["string", "null"]},
            "mode": {"type": ["string", "null"]},
            "quorumSatisfied": {"type": ["boolean", "null"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "receiptDigest": {"type": ["string", "null"], "minLength": 64, "maxLength": 64},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}

REVIEW_MESH_SCHEMAS["agent-review-mesh-result.v1"]["allOf"] = [
    {
        "if": {"properties": {"crossCheckReceipt": {"type": "null"}}, "required": ["crossCheckReceipt"]},
        "then": {
            "required": ["budgetUsageStatus", "roundParticipation"],
            "properties": {
                "budgetUsageStatus": {"const": "UNAVAILABLE"},
                "roundParticipation": {
                    "type": "object",
                    "required": ["eligible"],
                    "properties": {"eligible": {"const": False}},
                },
            },
        },
    },
]
