"""Schemas for criterion-scoped independent evidence."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schema_builders import open_object_schema

INDEPENDENCE_REQUIREMENT_SCHEMA = "agent-independence-requirement.v1"
INDEPENDENT_EVIDENCE_SCHEMA = "agent-independent-evidence.v1"
INDEPENDENT_EVIDENCE_VALIDATION_SCHEMA = "agent-independent-evidence-validation.v1"

INDEPENDENCE_DIMENSIONS = ("producer", "implementation", "source")
INDEPENDENCE_METHODS = ("deterministic-check", "human-review", "statistical-check")
INDEPENDENCE_SOURCE_POLICIES = ("exact-revision", "current-lineage", "any-current")
INDEPENDENT_EVIDENCE_STATUSES = ("PASS", "FAIL", "UNAVAILABLE")

INDEPENDENT_EVIDENCE_SCHEMAS = {
    INDEPENDENCE_REQUIREMENT_SCHEMA: open_object_schema(
        INDEPENDENCE_REQUIREMENT_SCHEMA,
        required=[
            "schemaVersion",
            "required",
            "requiredDimensions",
            "allowedMethods",
            "prohibitedProducerClasses",
            "sourcePolicy",
            "productionPromotionClaimed",
            "requirementDigest",
        ],
        properties={
            "required": {"type": "boolean"},
            "requiredDimensions": {"type": "array", "items": {"enum": list(INDEPENDENCE_DIMENSIONS)}},
            "allowedMethods": {"type": "array", "items": {"enum": list(INDEPENDENCE_METHODS)}},
            "prohibitedProducerClasses": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "sourcePolicy": {"enum": list(INDEPENDENCE_SOURCE_POLICIES)},
            "productionPromotionClaimed": {"const": False},
            "requirementDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    INDEPENDENT_EVIDENCE_SCHEMA: open_object_schema(
        INDEPENDENT_EVIDENCE_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "evidenceId",
            "criterionId",
            "requirementDigest",
            "sourceRevision",
            "sourceLineageDigest",
            "method",
            "producerClass",
            "producerIdentityHash",
            "implementationDigest",
            "findings",
            "unavailableReason",
            "rawReasoningStored",
            "rawTranscriptStored",
            "productionPromotionClaimed",
            "evidenceDigest",
        ],
        properties={
            "status": {"enum": list(INDEPENDENT_EVIDENCE_STATUSES)},
            "evidenceId": {"type": "string", "minLength": 1},
            "criterionId": {"type": "string", "minLength": 1},
            "requirementDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "sourceRevision": {"type": "string", "minLength": 1},
            "sourceLineageDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "method": {"enum": list(INDEPENDENCE_METHODS)},
            "producerClass": {"type": "string", "minLength": 1},
            "producerIdentityHash": {"type": "string", "minLength": 64, "maxLength": 64},
            "implementationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
            "findings": {"type": "array", "items": {"type": "object"}},
            "unavailableReason": {"type": ["string", "null"]},
            "rawReasoningStored": {"const": False},
            "rawTranscriptStored": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "evidenceDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
    INDEPENDENT_EVIDENCE_VALIDATION_SCHEMA: open_object_schema(
        INDEPENDENT_EVIDENCE_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "evidenceId",
            "criterionId",
            "evidenceStatus",
            "independenceStatus",
            "blockers",
            "evidenceDigest",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "evidenceId": {"type": ["string", "null"]},
            "criterionId": {"type": ["string", "null"]},
            "evidenceStatus": {"type": ["string", "null"]},
            "independenceStatus": {"enum": ["REQUIRED_PASS", "OPTIONAL_PASS", "NOT_PROVEN", "UNAVAILABLE"]},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "evidenceDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "validationDigest": {"type": "string", "minLength": 64, "maxLength": 64},
        },
    ),
}


def build_independence_requirement(
    *,
    required: bool = True,
    required_dimensions: list[str] | None = None,
    allowed_methods: list[str] | None = None,
    prohibited_producer_classes: list[str] | None = None,
    source_policy: str = "exact-revision",
) -> dict[str, Any]:
    """Build a criterion-level independence requirement."""

    body = {
        "schemaVersion": INDEPENDENCE_REQUIREMENT_SCHEMA,
        "required": bool(required),
        "requiredDimensions": list(required_dimensions or INDEPENDENCE_DIMENSIONS),
        "allowedMethods": list(allowed_methods or INDEPENDENCE_METHODS),
        "prohibitedProducerClasses": list(prohibited_producer_classes or []),
        "sourcePolicy": source_policy,
        "productionPromotionClaimed": False,
    }
    body = {**body, "requirementDigest": canonical_digest(body)}
    validation = validate_independence_requirement(body)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "independence-requirement-invalid",
            "independence requirement is invalid",
            {"validation": validation},
        )
    return body


def validate_independence_requirement(value: Any) -> dict[str, Any]:
    """Validate a frozen criterion's explicit independence requirement."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(value, dict):
        blockers.append({"code": "independence-requirement-object-invalid"})
        return _requirement_validation(value, blockers)
    if value.get("schemaVersion") != INDEPENDENCE_REQUIREMENT_SCHEMA:
        blockers.append({"code": "independence-requirement-schema-invalid"})
    if not isinstance(value.get("required"), bool):
        blockers.append({"code": "independence-requirement-required-invalid"})
    dimensions = value.get("requiredDimensions")
    if (
        not isinstance(dimensions, list)
        or not dimensions
        or not all(isinstance(item, str) and item in INDEPENDENCE_DIMENSIONS for item in dimensions)
        or len(dimensions) != len(set(item for item in dimensions if isinstance(item, str)))
    ):
        blockers.append({"code": "independence-requirement-dimensions-invalid"})
    methods = value.get("allowedMethods")
    if (
        not isinstance(methods, list)
        or not methods
        or not all(isinstance(item, str) and item in INDEPENDENCE_METHODS for item in methods)
        or len(methods) != len(set(item for item in methods if isinstance(item, str)))
    ):
        blockers.append({"code": "independence-requirement-methods-invalid"})
    producers = value.get("prohibitedProducerClasses")
    if not isinstance(producers, list) or any(not isinstance(item, str) or not item for item in producers):
        blockers.append({"code": "independence-requirement-producer-policy-invalid"})
    if value.get("sourcePolicy") not in INDEPENDENCE_SOURCE_POLICIES:
        blockers.append({"code": "independence-requirement-source-policy-invalid"})
    if value.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "independence-requirement-production-claim"})
    expected_digest = canonical_digest({key: item for key, item in value.items() if key != "requirementDigest"})
    if value.get("requirementDigest") != expected_digest:
        blockers.append({"code": "independence-requirement-digest-mismatch"})
    return _requirement_validation(value, blockers)


def build_independent_evidence(
    *,
    evidence_id: str,
    criterion_id: str,
    requirement: dict[str, Any],
    source_revision: str,
    source_lineage_digest: str,
    method: str,
    producer_class: str,
    producer_identity_hash: str,
    implementation_digest: str,
    status: str = "PASS",
    findings: list[dict[str, Any]] | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    """Build a bounded evidence record without storing reviewer internals."""

    requirement_validation = validate_independence_requirement(requirement)
    if requirement_validation["status"] != "PASS":
        raise LifecycleError(
            "independence-requirement-invalid",
            "independence requirement is invalid",
            {"validation": requirement_validation},
        )
    body = {
        "schemaVersion": INDEPENDENT_EVIDENCE_SCHEMA,
        "status": status,
        "evidenceId": evidence_id,
        "criterionId": criterion_id,
        "requirementDigest": requirement["requirementDigest"],
        "sourceRevision": source_revision,
        "sourceLineageDigest": source_lineage_digest,
        "method": method,
        "producerClass": producer_class,
        "producerIdentityHash": producer_identity_hash,
        "implementationDigest": implementation_digest,
        "findings": list(findings or []),
        "unavailableReason": unavailable_reason,
        "rawReasoningStored": False,
        "rawTranscriptStored": False,
        "productionPromotionClaimed": False,
    }
    body = {**body, "evidenceDigest": canonical_digest(body)}
    validation = validate_independent_evidence(body, requirement=requirement)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "independent-evidence-invalid",
            "independent evidence is invalid",
            {"validation": validation},
        )
    return body


def validate_independent_evidence(
    evidence: Any,
    *,
    requirement: dict[str, Any] | None = None,
    expected_source_revision: str | None = None,
    expected_source_lineage_digest: str | None = None,
    primary_producer_class: str | None = None,
    primary_implementation_digest: str | None = None,
) -> dict[str, Any]:
    """Validate evidence and fail closed only when its criterion requires it."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(evidence, dict):
        blockers.append({"code": "independent-evidence-object-invalid"})
        return _evidence_validation(evidence, blockers, "UNAVAILABLE")
    if evidence.get("schemaVersion") != INDEPENDENT_EVIDENCE_SCHEMA:
        blockers.append({"code": "independent-evidence-schema-invalid"})
    _required_text(evidence.get("evidenceId"), "independent-evidence-id-missing", blockers)
    _required_text(evidence.get("criterionId"), "independent-evidence-criterion-id-missing", blockers)
    _required_text(evidence.get("sourceRevision"), "independent-evidence-source-revision-missing", blockers)
    _digest(evidence.get("requirementDigest"), "independent-evidence-requirement-digest-invalid", blockers)
    _digest(evidence.get("sourceLineageDigest"), "independent-evidence-source-lineage-invalid", blockers)
    _digest(evidence.get("producerIdentityHash"), "independent-evidence-producer-identity-invalid", blockers)
    _digest(evidence.get("implementationDigest"), "independent-evidence-implementation-digest-invalid", blockers)
    if evidence.get("status") not in INDEPENDENT_EVIDENCE_STATUSES:
        blockers.append({"code": "independent-evidence-status-invalid"})
    if evidence.get("method") not in INDEPENDENCE_METHODS:
        blockers.append({"code": "independent-evidence-method-invalid"})
    _required_text(evidence.get("producerClass"), "independent-evidence-producer-class-missing", blockers)
    if not isinstance(evidence.get("findings"), list) or not all(
        isinstance(item, dict) for item in evidence["findings"]
    ):
        blockers.append({"code": "independent-evidence-findings-invalid"})
    if evidence.get("status") == "UNAVAILABLE" and not _non_empty_text(evidence.get("unavailableReason")):
        blockers.append({"code": "independent-evidence-unavailable-reason-missing"})
    if evidence.get("status") != "UNAVAILABLE" and evidence.get("unavailableReason") is not None:
        blockers.append({"code": "independent-evidence-unavailable-reason-unexpected"})
    if evidence.get("rawReasoningStored") is not False:
        blockers.append({"code": "independent-evidence-raw-reasoning"})
    if evidence.get("rawTranscriptStored") is not False:
        blockers.append({"code": "independent-evidence-raw-transcript"})
    if evidence.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "independent-evidence-production-claim"})

    required = False
    if requirement is not None:
        requirement_validation = validate_independence_requirement(requirement)
        if requirement_validation["status"] != "PASS":
            blockers.append({"code": "independent-evidence-requirement-invalid", "validation": requirement_validation})
            return _evidence_validation(evidence, blockers, "NOT_PROVEN")
        elif evidence.get("requirementDigest") != requirement.get("requirementDigest"):
            blockers.append({"code": "independent-evidence-requirement-mismatch"})
        required = requirement.get("required") is True
        if evidence.get("method") not in requirement.get("allowedMethods", []):
            blockers.append({"code": "independent-evidence-method-not-allowed"})
        if evidence.get("producerClass") in requirement.get("prohibitedProducerClasses", []):
            blockers.append({"code": "independent-evidence-producer-not-independent"})
    if expected_source_revision is not None and evidence.get("sourceRevision") != expected_source_revision:
        blockers.append({"code": "independent-evidence-source-stale"})
    if (
        expected_source_lineage_digest is not None
        and evidence.get("sourceLineageDigest") != expected_source_lineage_digest
    ):
        blockers.append({"code": "independent-evidence-lineage-mismatch"})
    if primary_producer_class is not None and evidence.get("producerClass") == primary_producer_class:
        blockers.append({"code": "independent-evidence-producer-not-independent"})
    if (
        primary_implementation_digest is not None
        and evidence.get("implementationDigest") == primary_implementation_digest
    ):
        blockers.append({"code": "independent-evidence-implementation-not-independent"})
    if required and evidence.get("status") != "PASS":
        blockers.append({"code": "independent-evidence-required"})

    expected_digest = canonical_digest({key: item for key, item in evidence.items() if key != "evidenceDigest"})
    if evidence.get("evidenceDigest") != expected_digest:
        blockers.append({"code": "independent-evidence-digest-mismatch"})
    if blockers:
        independence_status = "UNAVAILABLE" if evidence.get("status") == "UNAVAILABLE" else "NOT_PROVEN"
    elif required:
        independence_status = "REQUIRED_PASS"
    else:
        independence_status = "OPTIONAL_PASS"
    return _evidence_validation(evidence, blockers, independence_status)


def require_independent_evidence_pass(validation: dict[str, Any]) -> dict[str, Any]:
    """Require a valid independent evidence record for a declared criterion."""

    if validation.get("status") != "PASS" or validation.get("independenceStatus") != "REQUIRED_PASS":
        raise LifecycleError(
            "independent-evidence-required",
            "required independent evidence did not pass",
            {"validation": validation},
        )
    return validation


def _requirement_validation(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-independence-requirement-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "required": value.get("required")
        if isinstance(value, dict) and isinstance(value.get("required"), bool)
        else None,
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _evidence_validation(value: Any, blockers: list[dict[str, Any]], independence_status: str) -> dict[str, Any]:
    body = {
        "schemaVersion": INDEPENDENT_EVIDENCE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "evidenceId": value.get("evidenceId")
        if isinstance(value, dict) and isinstance(value.get("evidenceId"), str)
        else None,
        "criterionId": value.get("criterionId")
        if isinstance(value, dict) and isinstance(value.get("criterionId"), str)
        else None,
        "evidenceStatus": value.get("status")
        if isinstance(value, dict) and isinstance(value.get("status"), str)
        else None,
        "independenceStatus": independence_status,
        "blockers": blockers,
        "evidenceDigest": value.get("evidenceDigest") if isinstance(value, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _required_text(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _non_empty_text(value):
        blockers.append({"code": code})


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        blockers.append({"code": code})


__all__ = [
    "INDEPENDENCE_DIMENSIONS",
    "INDEPENDENCE_METHODS",
    "INDEPENDENCE_REQUIREMENT_SCHEMA",
    "INDEPENDENCE_SOURCE_POLICIES",
    "INDEPENDENT_EVIDENCE_SCHEMA",
    "INDEPENDENT_EVIDENCE_SCHEMAS",
    "INDEPENDENT_EVIDENCE_STATUSES",
    "INDEPENDENT_EVIDENCE_VALIDATION_SCHEMA",
    "build_independence_requirement",
    "build_independent_evidence",
    "require_independent_evidence_pass",
    "validate_independence_requirement",
    "validate_independent_evidence",
]
