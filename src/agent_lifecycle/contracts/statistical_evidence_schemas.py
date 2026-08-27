"""Contracts for provenance-bound statistical evidence."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, cast

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schema_builders import open_object_schema

STATISTICAL_EVIDENCE_REQUIREMENT_SCHEMA = "agent-statistical-evidence-requirement.v1"
STATISTICAL_EVIDENCE_SET_SCHEMA = "agent-statistical-evidence-set.v1"
STATISTICAL_EVIDENCE_VALIDATION_SCHEMA = "agent-statistical-evidence-validation.v1"

CONFIDENCE_METHODS = ("RULE_OF_THREE_95",)
SOURCE_CLASSES = ("IMPLEMENTATION", "INDEPENDENT_HOLDOUT", "EXTERNAL_OBSERVATION")
MAX_STATISTICAL_SAMPLES = 10000
_SAMPLE_FIELDS = (
    "sampleIdentity",
    "sourceClass",
    "derivation",
    "sourceRevision",
    "sourceLineageDigest",
    "producerClass",
    "producerIdentityHash",
    "sharedProducerDisclosed",
    "observedError",
)

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}

STATISTICAL_EVIDENCE_SCHEMAS: dict[str, dict[str, Any]] = {
    STATISTICAL_EVIDENCE_REQUIREMENT_SCHEMA: open_object_schema(
        STATISTICAL_EVIDENCE_REQUIREMENT_SCHEMA,
        required=[
            "schemaVersion",
            "required",
            "confidenceMethod",
            "threshold",
            "confidenceLevel",
            "zeroObservedErrorsRequired",
            "independentSourceRequired",
            "productionPromotionClaimed",
            "requirementDigest",
        ],
        properties={
            "required": {"type": "boolean"},
            "confidenceMethod": {"enum": list(CONFIDENCE_METHODS)},
            "threshold": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
            "confidenceLevel": {"const": 0.95},
            "zeroObservedErrorsRequired": {"const": True},
            "independentSourceRequired": {"type": "boolean"},
            "productionPromotionClaimed": {"const": False},
            "requirementDigest": _DIGEST,
        },
    ),
    STATISTICAL_EVIDENCE_SET_SCHEMA: open_object_schema(
        STATISTICAL_EVIDENCE_SET_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "criterionId",
            "requirementDigest",
            "sourceRevision",
            "sourceLineageDigest",
            "sampleCount",
            "effectiveIndependentCount",
            "requiredSampleCount",
            "observedErrors",
            "samples",
            "blockers",
            "adequate",
            "rawSamplesStored",
            "productionPromotionClaimed",
            "evidenceDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "criterionId": {"type": "string", "minLength": 1},
            "requirementDigest": _DIGEST,
            "sourceRevision": {"type": "string", "minLength": 1},
            "sourceLineageDigest": _DIGEST,
            "sampleCount": {"type": "integer", "minimum": 0},
            "effectiveIndependentCount": {"type": "integer", "minimum": 0},
            "requiredSampleCount": {"type": "integer", "minimum": 1},
            "observedErrors": {"type": "integer", "minimum": 0},
            "samples": {
                "type": "array",
                "maxItems": MAX_STATISTICAL_SAMPLES,
                "items": {"type": "object"},
            },
            "blockers": {"type": "array", "items": {"type": "object"}},
            "adequate": {"type": "boolean"},
            "rawSamplesStored": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "evidenceDigest": _DIGEST,
        },
    ),
    STATISTICAL_EVIDENCE_VALIDATION_SCHEMA: open_object_schema(
        STATISTICAL_EVIDENCE_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "criterionId",
            "effectiveIndependentCount",
            "requiredSampleCount",
            "adequate",
            "blockers",
            "evidenceDigest",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "criterionId": {"type": ["string", "null"]},
            "effectiveIndependentCount": {"type": "integer", "minimum": 0},
            "requiredSampleCount": {"type": "integer", "minimum": 0},
            "adequate": {"type": "boolean"},
            "blockers": {"type": "array", "items": {"type": "object"}},
            "evidenceDigest": {"type": ["string", "null"]},
            "validationDigest": _DIGEST,
        },
    ),
}


def build_statistical_evidence_requirement(
    *,
    threshold: float = 0.02,
    required: bool = True,
    independent_source_required: bool = True,
    confidence_method: str = "RULE_OF_THREE_95",
) -> dict[str, Any]:
    """Build a bounded zero-error statistical evidence requirement."""

    body = {
        "schemaVersion": STATISTICAL_EVIDENCE_REQUIREMENT_SCHEMA,
        "required": bool(required),
        "confidenceMethod": confidence_method,
        "threshold": threshold,
        "confidenceLevel": 0.95,
        "zeroObservedErrorsRequired": True,
        "independentSourceRequired": bool(independent_source_required),
        "productionPromotionClaimed": False,
    }
    requirement = {**body, "requirementDigest": canonical_digest(body)}
    validation = validate_statistical_evidence_requirement(requirement)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "statistical-evidence-requirement-invalid",
            "statistical evidence requirement is invalid",
            {"validation": validation},
        )
    return requirement


def validate_statistical_evidence_requirement(value: Any) -> dict[str, Any]:
    """Validate a criterion-level statistical evidence declaration."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(value, dict):
        blockers.append({"code": "statistical-requirement-object-invalid"})
        return _requirement_validation(value, blockers)
    if value.get("schemaVersion") != STATISTICAL_EVIDENCE_REQUIREMENT_SCHEMA:
        blockers.append({"code": "statistical-requirement-schema-invalid"})
    if not isinstance(value.get("required"), bool):
        blockers.append({"code": "statistical-requirement-required-invalid"})
    if value.get("confidenceMethod") not in CONFIDENCE_METHODS:
        blockers.append({"code": "statistical-confidence-method-unsupported"})
    if _threshold(value.get("threshold")) is None:
        blockers.append({"code": "statistical-threshold-invalid"})
    if value.get("confidenceLevel") != 0.95:
        blockers.append({"code": "statistical-confidence-level-invalid"})
    if value.get("zeroObservedErrorsRequired") is not True:
        blockers.append({"code": "statistical-zero-error-policy-invalid"})
    if not isinstance(value.get("independentSourceRequired"), bool):
        blockers.append({"code": "statistical-independence-policy-invalid"})
    if value.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "statistical-requirement-production-claim"})
    expected = canonical_digest({key: item for key, item in value.items() if key != "requirementDigest"})
    if value.get("requirementDigest") != expected:
        blockers.append({"code": "statistical-requirement-digest-mismatch"})
    return _requirement_validation(value, blockers)


def build_statistical_evidence_set(
    *,
    criterion_id: str,
    requirement: dict[str, Any],
    samples: list[dict[str, Any]],
    source_revision: str,
    source_lineage_digest: str,
    implementation_producer_identity_hashes: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate explicit sample metadata and bind the result into one receipt."""

    requirement_validation = validate_statistical_evidence_requirement(requirement)
    if requirement_validation["status"] != "PASS":
        raise LifecycleError(
            "statistical-evidence-requirement-invalid",
            "statistical evidence requirement is invalid",
            {"validation": requirement_validation},
        )
    if not isinstance(criterion_id, str) or not criterion_id:
        raise LifecycleError("statistical-evidence-criterion-missing", "criterion id is required")
    if not isinstance(source_revision, str) or not source_revision:
        raise LifecycleError("statistical-evidence-source-revision-missing", "source revision is required")
    if not _is_digest(source_lineage_digest):
        raise LifecycleError("statistical-evidence-lineage-invalid", "source lineage digest is invalid")
    if not isinstance(samples, list):
        raise LifecycleError("statistical-evidence-samples-invalid", "samples must be an array")
    if any(not _is_digest(item) for item in (implementation_producer_identity_hashes or [])):
        raise LifecycleError(
            "statistical-evidence-implementation-producer-invalid",
            "implementation producer identities must be canonical digests",
        )
    if len(samples) > MAX_STATISTICAL_SAMPLES:
        raise LifecycleError(
            "statistical-evidence-sample-limit",
            "statistical evidence exceeds the sample limit",
            {"sampleCount": len(samples), "maxSamples": MAX_STATISTICAL_SAMPLES},
        )
    body = _evaluate(
        criterion_id=criterion_id,
        requirement=requirement,
        samples=samples,
        source_revision=source_revision,
        source_lineage_digest=source_lineage_digest,
        implementation_producer_identity_hashes=implementation_producer_identity_hashes or [],
    )
    return {**body, "evidenceDigest": canonical_digest(body)}


def validate_statistical_evidence_set(
    evidence: Any,
    *,
    requirement: dict[str, Any],
    expected_source_revision: str,
    expected_source_lineage_digest: str,
    implementation_producer_identity_hashes: list[str] | None = None,
) -> dict[str, Any]:
    """Rebuild statistical evidence so declared counts cannot grant authority."""

    blockers: list[dict[str, Any]] = []
    requirement_validation = validate_statistical_evidence_requirement(requirement)
    if requirement_validation["status"] != "PASS":
        blockers.append({"code": "statistical-evidence-requirement-invalid"})
        return _evidence_validation(evidence, blockers, 0, 0, False)
    if not isinstance(evidence, dict):
        blockers.append({"code": "statistical-evidence-object-invalid"})
        return _evidence_validation(evidence, blockers, 0, 0, False)
    if evidence.get("schemaVersion") != STATISTICAL_EVIDENCE_SET_SCHEMA:
        blockers.append({"code": "statistical-evidence-schema-invalid"})
    if not isinstance(evidence.get("criterionId"), str) or not evidence["criterionId"]:
        blockers.append({"code": "statistical-evidence-criterion-missing"})
    if evidence.get("requirementDigest") != requirement.get("requirementDigest"):
        blockers.append({"code": "statistical-evidence-requirement-mismatch"})
    if evidence.get("sourceRevision") != expected_source_revision:
        blockers.append({"code": "statistical-evidence-source-stale"})
    if evidence.get("sourceLineageDigest") != expected_source_lineage_digest:
        blockers.append({"code": "statistical-evidence-lineage-mismatch"})
    raw_samples = evidence.get("samples")
    samples = cast(list[dict[str, Any]], raw_samples) if isinstance(raw_samples, list) else []
    if len(samples) > MAX_STATISTICAL_SAMPLES:
        blockers.append(
            {
                "code": "statistical-evidence-sample-limit",
                "sampleCount": len(samples),
                "maxSamples": MAX_STATISTICAL_SAMPLES,
            }
        )
        return _evidence_validation(evidence, blockers, 0, 0, False)
    rebuilt = _evaluate(
        criterion_id=str(evidence.get("criterionId", "")),
        requirement=requirement,
        samples=samples,
        source_revision=expected_source_revision,
        source_lineage_digest=expected_source_lineage_digest,
        implementation_producer_identity_hashes=implementation_producer_identity_hashes or [],
    )
    blockers.extend(rebuilt["blockers"])
    for field in (
        "status",
        "sampleCount",
        "effectiveIndependentCount",
        "requiredSampleCount",
        "observedErrors",
        "samples",
        "adequate",
        "rawSamplesStored",
        "productionPromotionClaimed",
    ):
        if evidence.get(field) != rebuilt.get(field):
            blockers.append({"code": "statistical-evidence-derived-field-mismatch", "field": field})
    expected_digest = canonical_digest({key: item for key, item in evidence.items() if key != "evidenceDigest"})
    if evidence.get("evidenceDigest") != expected_digest:
        blockers.append({"code": "statistical-evidence-digest-mismatch"})
    return _evidence_validation(
        evidence,
        _deduplicate_blockers(blockers),
        rebuilt["effectiveIndependentCount"],
        rebuilt["requiredSampleCount"],
        rebuilt["adequate"] and not blockers,
    )


def required_rule_of_three_sample_count(threshold: float) -> int:
    """Return ceil(3 / threshold) without binary floating-point drift."""

    parsed = _threshold(threshold)
    if parsed is None:
        raise LifecycleError("statistical-threshold-invalid", "threshold must be greater than zero and at most one")
    return int((Decimal(3) / parsed).to_integral_value(rounding=ROUND_CEILING))


def _evaluate(
    *,
    criterion_id: str,
    requirement: dict[str, Any],
    samples: list[dict[str, Any]],
    source_revision: str,
    source_lineage_digest: str,
    implementation_producer_identity_hashes: list[str],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    required_count = required_rule_of_three_sample_count(requirement["threshold"])
    implementation_producers = set(implementation_producer_identity_hashes)
    seen: set[str] = set()
    effective = 0
    observed_errors = 0
    projected_samples = [_project_sample(sample) for sample in samples]
    for index, sample in enumerate(projected_samples):
        if not isinstance(sample, dict):
            blockers.append({"code": "statistical-sample-object-invalid", "index": index})
            continue
        identity_value = sample.get("sampleIdentity")
        if not _is_digest(identity_value):
            blockers.append({"code": "statistical-sample-identity-invalid", "index": index})
            continue
        identity = cast(str, identity_value)
        duplicate = identity in seen
        if duplicate:
            blockers.append({"code": "statistical-sample-identity-duplicate", "sampleIdentity": identity})
        seen.add(identity)
        if sample.get("observedError") is True:
            observed_errors += 1
        elif sample.get("observedError") is not False:
            blockers.append({"code": "statistical-sample-outcome-invalid", "sampleIdentity": identity})
        current = True
        if sample.get("sourceRevision") != source_revision:
            blockers.append({"code": "statistical-sample-source-stale", "sampleIdentity": identity})
            current = False
        if sample.get("sourceLineageDigest") != source_lineage_digest:
            blockers.append({"code": "statistical-sample-lineage-mismatch", "sampleIdentity": identity})
            current = False
        if sample.get("sourceClass") not in SOURCE_CLASSES:
            blockers.append({"code": "statistical-sample-source-class-invalid", "sampleIdentity": identity})
            current = False
        if not isinstance(sample.get("derivation"), str) or not sample["derivation"]:
            blockers.append({"code": "statistical-sample-derivation-missing", "sampleIdentity": identity})
            current = False
        if not isinstance(sample.get("producerClass"), str) or not sample["producerClass"]:
            blockers.append({"code": "statistical-sample-producer-class-missing", "sampleIdentity": identity})
            current = False
        producer = sample.get("producerIdentityHash")
        if not _is_digest(producer):
            blockers.append({"code": "statistical-sample-producer-invalid", "sampleIdentity": identity})
            current = False
        independent = sample.get("sourceClass") == "INDEPENDENT_HOLDOUT"
        if requirement.get("independentSourceRequired") is True and not independent:
            current = False
        if requirement.get("independentSourceRequired") is True and producer in implementation_producers:
            if sample.get("sharedProducerDisclosed") is not True:
                blockers.append({"code": "statistical-shared-producer-undisclosed", "sampleIdentity": identity})
            blockers.append({"code": "statistical-sample-producer-not-independent", "sampleIdentity": identity})
            current = False
        if current and not duplicate:
            effective += 1
    if observed_errors and requirement.get("zeroObservedErrorsRequired") is True:
        blockers.append({"code": "statistical-rule-of-three-observed-errors", "observedErrors": observed_errors})
    if effective < required_count:
        blockers.append(
            {
                "code": "statistical-effective-sample-insufficient",
                "required": required_count,
                "actual": effective,
            }
        )
    blockers = _deduplicate_blockers(blockers)
    adequate = not blockers and effective >= required_count and observed_errors == 0
    return {
        "schemaVersion": STATISTICAL_EVIDENCE_SET_SCHEMA,
        "status": "PASS" if adequate else "FAIL",
        "criterionId": criterion_id,
        "requirementDigest": requirement["requirementDigest"],
        "sourceRevision": source_revision,
        "sourceLineageDigest": source_lineage_digest,
        "sampleCount": len(samples),
        "effectiveIndependentCount": effective,
        "requiredSampleCount": required_count,
        "observedErrors": observed_errors,
        "samples": projected_samples,
        "blockers": blockers,
        "adequate": adequate,
        "rawSamplesStored": False,
        "productionPromotionClaimed": False,
    }


def _requirement_validation(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-statistical-evidence-requirement-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "required": value.get("required") if isinstance(value, dict) else None,
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _evidence_validation(
    value: Any,
    blockers: list[dict[str, Any]],
    effective_count: int,
    required_count: int,
    adequate: bool,
) -> dict[str, Any]:
    body = {
        "schemaVersion": STATISTICAL_EVIDENCE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers and adequate else "FAIL",
        "criterionId": value.get("criterionId") if isinstance(value, dict) else None,
        "effectiveIndependentCount": effective_count,
        "requiredSampleCount": required_count,
        "adequate": adequate and not blockers,
        "blockers": blockers,
        "evidenceDigest": value.get("evidenceDigest") if isinstance(value, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _threshold(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if Decimal(0) < parsed <= Decimal(1) else None


def _project_sample(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {field: value.get(field) for field in _SAMPLE_FIELDS}


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _deduplicate_blockers(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for blocker in blockers:
        unique[canonical_digest(blocker)] = blocker
    return [unique[key] for key in sorted(unique)]


__all__ = [
    "CONFIDENCE_METHODS",
    "MAX_STATISTICAL_SAMPLES",
    "SOURCE_CLASSES",
    "STATISTICAL_EVIDENCE_REQUIREMENT_SCHEMA",
    "STATISTICAL_EVIDENCE_SCHEMAS",
    "STATISTICAL_EVIDENCE_SET_SCHEMA",
    "STATISTICAL_EVIDENCE_VALIDATION_SCHEMA",
    "build_statistical_evidence_requirement",
    "build_statistical_evidence_set",
    "required_rule_of_three_sample_count",
    "validate_statistical_evidence_requirement",
    "validate_statistical_evidence_set",
]
