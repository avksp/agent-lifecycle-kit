"""Contracts for bounded review rounds and immutable finding dispositions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.external_job_schemas import validate_external_job_result
from agent_lifecycle.contracts.review_verdict import validate_review_verdict
from agent_lifecycle.contracts.schema_builders import open_object_schema

REVIEW_ROUND_PARTICIPATION_SCHEMA = "agent-review-round-participation.v1"
FINDING_DISPOSITION_SCHEMA = "agent-finding-disposition.v1"
REVIEW_ROUND_EVALUATION_SCHEMA = "agent-review-round-evaluation.v1"

FINDING_DISPOSITIONS = ("CONFIRMED", "REJECTED", "UNAVAILABLE", "APPROVAL_REQUIRED")
ROUND_EXHAUSTION_OUTCOMES = ("REPLAN_REQUIRED", "SPLIT_REQUIRED", "OPERATOR_DECISION", "BLOCKED")
ROUND_OUTCOMES = ("ACCEPTED", "CONTINUE", *ROUND_EXHAUSTION_OUTCOMES)
_DIGEST = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_ID = {"type": "string", "minLength": 1, "maxLength": 256}

REVIEW_ROUND_SCHEMAS: dict[str, dict[str, Any]] = {
    REVIEW_ROUND_PARTICIPATION_SCHEMA: open_object_schema(
        REVIEW_ROUND_PARTICIPATION_SCHEMA,
        required=[
            "schemaVersion",
            "reviewerId",
            "participating",
            "reasonCodes",
            "reviewVerdict",
            "findings",
            "jobRequest",
            "jobStatus",
            "jobResult",
            "reviewVerdictDigest",
            "jobResultDigest",
            "resourceUseObserved",
            "authorityClaimed",
            "productionPromotionClaimed",
            "participationDigest",
        ],
        properties={
            "reviewerId": _ID,
            "participating": {"type": "boolean"},
            "reasonCodes": {"type": "array", "items": _ID, "maxItems": 32},
            "reviewVerdict": {"type": ["object", "null"]},
            "findings": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "jobRequest": {"type": ["object", "null"]},
            "jobStatus": {"type": ["object", "null"]},
            "jobResult": {"type": ["object", "null"]},
            "reviewVerdictDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
            "jobResultDigest": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
            "resourceUseObserved": {"type": "boolean"},
            "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "participationDigest": _DIGEST,
        },
    ),
    FINDING_DISPOSITION_SCHEMA: open_object_schema(
        FINDING_DISPOSITION_SCHEMA,
        required=[
            "schemaVersion",
            "findingId",
            "findingDigest",
            "disposition",
            "reasonCode",
            "evidenceDigests",
            "operationId",
            "terminal",
            "authorityClaimed",
            "productionPromotionClaimed",
            "dispositionDigest",
        ],
        properties={
            "findingId": _ID,
            "findingDigest": _DIGEST,
            "disposition": {"enum": list(FINDING_DISPOSITIONS)},
            "reasonCode": _ID,
            "evidenceDigests": {"type": "array", "minItems": 1, "maxItems": 128, "items": _DIGEST},
            "operationId": _ID,
            "terminal": {"const": True},
            "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "dispositionDigest": _DIGEST,
        },
    ),
    REVIEW_ROUND_EVALUATION_SCHEMA: open_object_schema(
        REVIEW_ROUND_EVALUATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "round",
            "maxRounds",
            "outcome",
            "participatingReviewerIds",
            "resourceUseCount",
            "findingIds",
            "openBlockingFindingIds",
            "missingDispositionFindingIds",
            "blockers",
            "authorityClaimed",
            "productionPromotionClaimed",
            "evaluationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "round": {"type": "integer", "minimum": 1, "maximum": 10},
            "maxRounds": {"type": "integer", "minimum": 1, "maximum": 10},
            "outcome": {"enum": list(ROUND_OUTCOMES)},
            "participatingReviewerIds": {"type": "array", "items": _ID},
            "resourceUseCount": {"type": "integer", "minimum": 0},
            "findingIds": {"type": "array", "items": _ID},
            "openBlockingFindingIds": {"type": "array", "items": _ID},
            "missingDispositionFindingIds": {"type": "array", "items": _ID},
            "blockers": {"type": "array", "items": {"type": "object"}, "maxItems": 256},
            "authorityClaimed": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "evaluationDigest": _DIGEST,
        },
    ),
}


def build_review_round_participation(
    *,
    reviewer_id: str,
    review_verdict: dict[str, Any] | None,
    findings: list[dict[str, Any]],
    job_request: dict[str, Any] | None,
    job_status: dict[str, Any] | None,
    job_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Bind a reviewer verdict to terminal external-job evidence."""

    _required_id(reviewer_id, "reviewerId")
    if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
        raise LifecycleError("review-round-findings-invalid", "findings must be an object list")
    reason_codes: list[str] = []
    verdict_valid = False
    if isinstance(review_verdict, dict):
        verdict_validation = validate_review_verdict(review_verdict, findings=findings)
        verdict_valid = verdict_validation["status"] == "PASS"
        if not verdict_valid:
            reason_codes.append("review-verdict-invalid")
    else:
        reason_codes.append("review-verdict-missing")
    job_eligible = False
    if isinstance(job_result, dict):
        job_validation = validate_external_job_result(job_result, request=job_request, status=job_status)
        job_eligible = job_validation.get("blockingEligible") is True
        if job_validation.get("status") != "PASS":
            reason_codes.append("external-job-result-invalid")
        elif not job_eligible:
            reason_codes.append("external-job-result-not-eligible")
    else:
        reason_codes.append("external-job-result-missing")
    verdict_digest = canonical_digest(review_verdict) if isinstance(review_verdict, dict) else None
    verdict_output_bound = (
        verdict_digest is not None
        and isinstance(job_result, dict)
        and job_result.get("outputDigest") == verdict_digest
        and isinstance(job_result.get("outputBytes"), int)
        and not isinstance(job_result.get("outputBytes"), bool)
        and job_result["outputBytes"] > 0
    )
    if verdict_valid and job_eligible and not verdict_output_bound:
        reason_codes.append("review-verdict-job-output-mismatch")
    participating = verdict_valid and job_eligible and verdict_output_bound
    body = {
        "schemaVersion": REVIEW_ROUND_PARTICIPATION_SCHEMA,
        "reviewerId": reviewer_id,
        "participating": participating,
        "reasonCodes": sorted(set(reason_codes)),
        "reviewVerdict": dict(review_verdict) if isinstance(review_verdict, dict) else None,
        "findings": [dict(item) for item in findings],
        "jobRequest": dict(job_request) if isinstance(job_request, dict) else None,
        "jobStatus": dict(job_status) if isinstance(job_status, dict) else None,
        "jobResult": dict(job_result) if isinstance(job_result, dict) else None,
        "reviewVerdictDigest": verdict_digest,
        "jobResultDigest": job_result.get("resultDigest") if isinstance(job_result, dict) else None,
        "resourceUseObserved": any(isinstance(item, dict) for item in (job_request, job_status, job_result)),
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "participationDigest": canonical_digest(body)}


def validate_review_round_participation(receipt: Any) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    value = receipt if isinstance(receipt, dict) else {}
    if not isinstance(receipt, dict):
        blockers.append({"code": "review-round-participation-not-object"})
    if value.get("schemaVersion") != REVIEW_ROUND_PARTICIPATION_SCHEMA:
        blockers.append({"code": "review-round-participation-schema-invalid"})
    try:
        rebuilt = build_review_round_participation(
            reviewer_id=value.get("reviewerId"),
            review_verdict=value.get("reviewVerdict"),
            findings=value.get("findings"),
            job_request=value.get("jobRequest"),
            job_status=value.get("jobStatus"),
            job_result=value.get("jobResult"),
        )
    except LifecycleError as exc:
        blockers.append({"code": exc.code})
        rebuilt = None
    if rebuilt is not None and rebuilt != value:
        blockers.append({"code": "review-round-participation-content-mismatch"})
    if value.get("authorityClaimed") is not False or value.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-round-participation-authority-boundary"})
    expected = canonical_digest({key: item for key, item in value.items() if key != "participationDigest"})
    if value.get("participationDigest") != expected:
        blockers.append({"code": "review-round-participation-digest-mismatch"})
    return _validation("agent-review-round-participation-validation.v1", blockers)


def build_finding_disposition(
    *,
    finding: dict[str, Any],
    disposition: str,
    reason_code: str,
    evidence_digests: list[str],
    operation_id: str,
) -> dict[str, Any]:
    """Create one terminal, evidence-bound disposition for a finding."""

    finding_id = finding.get("id") if isinstance(finding, dict) else None
    _required_id(finding_id, "finding.id")
    if disposition not in FINDING_DISPOSITIONS:
        raise LifecycleError("finding-disposition-invalid", "disposition is unsupported")
    _required_id(reason_code, "reasonCode")
    _required_id(operation_id, "operationId")
    if disposition == "REJECTED" and reason_code != "false-positive":
        raise LifecycleError("finding-disposition-rejection-reason-invalid", "REJECTED requires false-positive")
    evidence = _digest_list(evidence_digests, "evidenceDigests")
    body = {
        "schemaVersion": FINDING_DISPOSITION_SCHEMA,
        "findingId": finding_id,
        "findingDigest": canonical_digest(finding),
        "disposition": disposition,
        "reasonCode": reason_code,
        "evidenceDigests": evidence,
        "operationId": operation_id,
        "terminal": True,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "dispositionDigest": canonical_digest(body)}


def validate_finding_disposition(disposition: Any) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    value = disposition if isinstance(disposition, dict) else {}
    if not isinstance(disposition, dict):
        blockers.append({"code": "finding-disposition-not-object"})
    if value.get("schemaVersion") != FINDING_DISPOSITION_SCHEMA:
        blockers.append({"code": "finding-disposition-schema-invalid"})
    try:
        _required_id(value.get("findingId"), "findingId")
        _required_id(value.get("reasonCode"), "reasonCode")
        _required_id(value.get("operationId"), "operationId")
        _digest(value.get("findingDigest"), "findingDigest")
        _digest_list(value.get("evidenceDigests"), "evidenceDigests")
    except LifecycleError as exc:
        blockers.append({"code": exc.code})
    if value.get("disposition") not in FINDING_DISPOSITIONS:
        blockers.append({"code": "finding-disposition-invalid"})
    if value.get("disposition") == "REJECTED" and value.get("reasonCode") != "false-positive":
        blockers.append({"code": "finding-disposition-rejection-reason-invalid"})
    if value.get("terminal") is not True:
        blockers.append({"code": "finding-disposition-not-terminal"})
    if value.get("authorityClaimed") is not False or value.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "finding-disposition-authority-boundary"})
    expected = canonical_digest({key: item for key, item in value.items() if key != "dispositionDigest"})
    if value.get("dispositionDigest") != expected:
        blockers.append({"code": "finding-disposition-digest-mismatch"})
    return _validation("agent-finding-disposition-validation.v1", blockers)


def merge_finding_dispositions(existing: list[dict[str, Any]], updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge exact replays while rejecting every conflicting terminal update."""

    merged: dict[str, dict[str, Any]] = {}
    for item in [*existing, *updates]:
        validation = validate_finding_disposition(item)
        if validation["status"] != "PASS":
            raise LifecycleError("finding-disposition-invalid", "finding disposition failed validation", validation)
        finding_id = item["findingId"]
        prior = merged.get(finding_id)
        if prior is not None and prior != item:
            raise LifecycleError(
                "finding-disposition-conflict",
                "finding already has a different terminal disposition",
                {"findingId": finding_id},
            )
        merged[finding_id] = dict(item)
    return [merged[key] for key in sorted(merged)]


def build_review_round_evaluation(
    *,
    round_number: int,
    max_rounds: int,
    outcome: str,
    participating_reviewer_ids: list[str],
    resource_use_count: int,
    finding_ids: list[str],
    open_blocking_finding_ids: list[str],
    missing_disposition_finding_ids: list[str],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    _round_budget(round_number, "round")
    _round_budget(max_rounds, "maxRounds")
    if round_number > max_rounds:
        raise LifecycleError("review-round-budget-exceeded", "round exceeds maxRounds")
    if outcome not in ROUND_OUTCOMES:
        raise LifecycleError("review-round-outcome-invalid", "round outcome is unsupported")
    if outcome == "ACCEPTED" and blockers:
        raise LifecycleError("review-round-acceptance-blocked", "ACCEPTED cannot carry blockers")
    if outcome != "ACCEPTED" and not blockers:
        raise LifecycleError("review-round-nonaccepting-without-blockers", "non-accepting outcome requires blockers")
    if not isinstance(resource_use_count, int) or isinstance(resource_use_count, bool) or resource_use_count < 0:
        raise LifecycleError("review-round-resource-count-invalid", "resourceUseCount must be a non-negative integer")
    if not isinstance(blockers, list) or any(not isinstance(item, dict) for item in blockers):
        raise LifecycleError("review-round-blockers-invalid", "blockers must be an object list")
    body = {
        "schemaVersion": REVIEW_ROUND_EVALUATION_SCHEMA,
        "status": "PASS" if outcome == "ACCEPTED" else "FAIL",
        "round": round_number,
        "maxRounds": max_rounds,
        "outcome": outcome,
        "participatingReviewerIds": _id_list(participating_reviewer_ids, "participatingReviewerIds"),
        "resourceUseCount": resource_use_count,
        "findingIds": _id_list(finding_ids, "findingIds"),
        "openBlockingFindingIds": _id_list(open_blocking_finding_ids, "openBlockingFindingIds"),
        "missingDispositionFindingIds": _id_list(missing_disposition_finding_ids, "missingDispositionFindingIds"),
        "blockers": blockers,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "evaluationDigest": canonical_digest(body)}


def validate_review_round_evaluation(evaluation: Any) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    value = evaluation if isinstance(evaluation, dict) else {}
    if not isinstance(evaluation, dict):
        blockers.append({"code": "review-round-evaluation-not-object"})
    if value.get("schemaVersion") != REVIEW_ROUND_EVALUATION_SCHEMA:
        blockers.append({"code": "review-round-evaluation-schema-invalid"})
    try:
        rebuilt = build_review_round_evaluation(
            round_number=value.get("round"),
            max_rounds=value.get("maxRounds"),
            outcome=value.get("outcome"),
            participating_reviewer_ids=value.get("participatingReviewerIds"),
            resource_use_count=value.get("resourceUseCount"),
            finding_ids=value.get("findingIds"),
            open_blocking_finding_ids=value.get("openBlockingFindingIds"),
            missing_disposition_finding_ids=value.get("missingDispositionFindingIds"),
            blockers=value.get("blockers"),
        )
    except LifecycleError as exc:
        blockers.append({"code": exc.code})
        rebuilt = None
    if rebuilt is not None and rebuilt != value:
        blockers.append({"code": "review-round-evaluation-content-mismatch"})
    if value.get("authorityClaimed") is not False or value.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "review-round-evaluation-authority-boundary"})
    expected = canonical_digest({key: item for key, item in value.items() if key != "evaluationDigest"})
    if value.get("evaluationDigest") != expected:
        blockers.append({"code": "review-round-evaluation-digest-mismatch"})
    return _validation("agent-review-round-evaluation-validation.v1", blockers)


def _validation(schema: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {"schemaVersion": schema, "status": "PASS" if not blockers else "FAIL", "blockers": blockers}
    return {**body, "validationDigest": canonical_digest(body)}


def _required_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise LifecycleError("review-round-field-invalid", f"{field} must be a bounded non-empty string")


def _digest(value: Any, field: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise LifecycleError("review-round-digest-invalid", f"{field} must be a lowercase SHA-256 digest")


def _digest_list(values: Any, field: str) -> list[str]:
    if not isinstance(values, list) or not values:
        raise LifecycleError("review-round-evidence-invalid", f"{field} must be a non-empty digest list")
    for value in values:
        _digest(value, field)
    return sorted(set(values))


def _id_list(values: Any, field: str) -> list[str]:
    if not isinstance(values, list):
        raise LifecycleError("review-round-field-invalid", f"{field} must be a string list")
    for value in values:
        _required_id(value, field)
    return sorted(set(values))


def _round_budget(value: Any, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10:
        raise LifecycleError("review-round-budget-invalid", f"{field} must be an integer from 1 through 10")


__all__ = [
    "FINDING_DISPOSITIONS",
    "FINDING_DISPOSITION_SCHEMA",
    "REVIEW_ROUND_EVALUATION_SCHEMA",
    "REVIEW_ROUND_PARTICIPATION_SCHEMA",
    "REVIEW_ROUND_SCHEMAS",
    "ROUND_EXHAUSTION_OUTCOMES",
    "ROUND_OUTCOMES",
    "build_finding_disposition",
    "build_review_round_evaluation",
    "build_review_round_participation",
    "merge_finding_dispositions",
    "validate_finding_disposition",
    "validate_review_round_evaluation",
    "validate_review_round_participation",
]
