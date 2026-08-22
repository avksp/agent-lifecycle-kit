"""Runtime validation for optional adapter lifecycle control envelopes."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.lifecycle_control_definitions import (
    _ATTESTATION_FIELDS,
    _DECISION_FIELDS,
    _DIGEST_FIELDS,
    _EVENT_FIELDS,
    _LEVEL_RANK,
    _POLICY_AUTHORITY_FIELDS,
    _POLICY_FIELDS,
    _POLICY_LIMIT_FIELDS,
    _POLICY_OPERATION_FIELDS,
    _QUALIFICATION_FIELDS,
    _REQUEST_FIELDS,
    _UNTRUSTED_KEYS,
    CONTROL_EVENT_TYPES,
    CONTROL_LEVELS,
    CONTROL_OPERATIONS,
    CONTROL_STATUSES,
    DEFAULT_MAX_ATTESTATION_AGE_SECONDS,
    DEFAULT_MAX_EVENT_AGE_SECONDS,
    DEFAULT_MAX_REQUEST_AGE_SECONDS,
    LIFECYCLE_CONTROL_ATTESTATION_SCHEMA,
    LIFECYCLE_CONTROL_DECISION_SCHEMA,
    LIFECYCLE_CONTROL_EVENT_SCHEMA,
    LIFECYCLE_CONTROL_POLICY_SCHEMA,
    LIFECYCLE_CONTROL_POLICY_VALIDATION_SCHEMA,
    LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA,
    LIFECYCLE_CONTROL_QUALIFICATION_VALIDATION_SCHEMA,
    LIFECYCLE_CONTROL_REQUEST_SCHEMA,
    MAX_CONTROL_NESTING,
    MAX_CONTROL_PAYLOAD_BYTES,
    MAX_CONTROL_REDACTION_STRING_LENGTH,
    MAX_CONTROL_STRING_LENGTH,
    QUALIFICATION_STATUSES,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.redaction import is_sensitive_key, redact_value


def validate_lifecycle_control_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate policy authority and prevent level escalation from metadata."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(policy, dict):
        return _validation_result(None, [{"code": "control-policy-not-object"}])
    _reject_unknown_fields(policy, _POLICY_FIELDS, blockers, "control-policy-unknown-field")
    if policy.get("schemaVersion") != LIFECYCLE_CONTROL_POLICY_SCHEMA:
        blockers.append({"code": "control-policy-schema"})
    _validate_json_shape(policy, blockers, "control-policy-shape")
    policy_id = policy.get("policyId")
    if not isinstance(policy_id, str) or not 1 <= len(policy_id) <= MAX_CONTROL_STRING_LENGTH:
        blockers.append({"code": "control-policy-id"})
    if (
        not isinstance(policy.get("revision"), int)
        or isinstance(policy.get("revision"), bool)
        or policy["revision"] < 1
    ):
        blockers.append({"code": "control-policy-revision"})
    if policy.get("defaultLevel") not in {"OFF", "GUIDANCE_ONLY"}:
        blockers.append({"code": "control-policy-default-escalation"})
    operations = policy.get("operations")
    if not isinstance(operations, dict):
        blockers.append({"code": "control-policy-operations"})
    else:
        unknown = sorted(set(operations).difference(CONTROL_OPERATIONS))
        blockers.extend({"code": "control-policy-operation-unsupported", "operation": item} for item in unknown)
        for operation in CONTROL_OPERATIONS:
            entry = operations.get(operation)
            if not isinstance(entry, dict):
                blockers.append({"code": "control-policy-operation-missing", "operation": operation})
                continue
            _reject_unknown_fields(
                entry,
                _POLICY_OPERATION_FIELDS,
                blockers,
                "control-policy-operation-unknown-field",
                path=f"operations.{operation}",
            )
            _validate_operation_entry(operation, entry, blockers)
    limits = policy.get("limits")
    if not isinstance(limits, dict):
        blockers.append({"code": "control-policy-limits"})
    else:
        _reject_unknown_fields(
            limits, _POLICY_LIMIT_FIELDS, blockers, "control-policy-limit-unknown-field", path="limits"
        )
        _positive_bounded(limits, "maxEvents", 1, 256, blockers)
        _positive_bounded(limits, "maxPayloadBytes", 512, MAX_CONTROL_PAYLOAD_BYTES, blockers)
        _positive_bounded(limits, "maxChangedPaths", 1, 64, blockers)
        _positive_bounded(limits, "maxAttestationAgeSeconds", 1, 3600, blockers)
        _positive_bounded(limits, "maxNonceBytes", 16, 128, blockers)
    authority = policy.get("authority")
    if not isinstance(authority, dict):
        blockers.append({"code": "control-policy-authority"})
    else:
        _reject_unknown_fields(
            authority, _POLICY_AUTHORITY_FIELDS, blockers, "control-policy-authority-unknown-field", path="authority"
        )
        expected = {
            "modelWritable": False,
            "settingsAutoEdited": False,
            "keysExternal": True,
            "providerIdentityUsed": False,
        }
        for key, value in expected.items():
            if authority.get(key) is not value:
                blockers.append({"code": "control-policy-authority-invariant", "field": key})
    if policy.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "control-policy-production-claim"})
    _validate_self_digest(policy, "policyDigest", blockers, "control-policy-digest")
    return _validation_result(
        policy_id if isinstance(policy_id, str) else None, blockers, digest=policy.get("policyDigest")
    )


def validate_lifecycle_control_request(
    request: dict[str, Any],
    *,
    policy_limits: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_REQUEST_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate request bounds and reject model-controlled authority fields."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(request, dict):
        return _generic_validation(LIFECYCLE_CONTROL_REQUEST_SCHEMA, [{"code": "control-request-not-object"}])
    max_nonce_bytes = _runtime_limit(policy_limits, "maxNonceBytes", 16, 128, 128, blockers)
    max_changed_paths = _runtime_limit(policy_limits, "maxChangedPaths", 1, 64, 64, blockers)
    _validate_json_shape(request, blockers, "control-request-shape")
    _reject_unknown_fields(request, _REQUEST_FIELDS, blockers, "control-request-unknown-field")
    if request.get("schemaVersion") != LIFECYCLE_CONTROL_REQUEST_SCHEMA:
        blockers.append({"code": "control-request-schema"})
    _check_common_identity(request, blockers)
    _validate_string(request.get("nonce"), "nonce", 16, max_nonce_bytes, blockers, "control-request-nonce")
    if request.get("operation") not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-request-operation"})
    if request.get("requestedLevel") not in CONTROL_LEVELS:
        blockers.append({"code": "control-request-level"})
    if request.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "control-request-production-claim"})
    _reject_untrusted_keys(request, blockers)
    _validate_paths(request.get("paths"), blockers, "control-request-paths", max_count=max_changed_paths)
    _validate_self_digest(request, "requestDigest", blockers, "control-request-digest")
    _validate_timestamp(request.get("createdAt"), blockers, "control-request-created-at")
    _validate_freshness(
        request.get("createdAt"),
        reference_time=reference_time,
        max_age_seconds=max_age_seconds,
        blockers=blockers,
        code_prefix="control-request",
    )
    return _generic_validation(LIFECYCLE_CONTROL_REQUEST_SCHEMA, blockers)


def validate_lifecycle_control_decision(
    decision: dict[str, Any], *, policy_limits: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate a decision without granting authority to its producer."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(decision, dict):
        return _generic_validation(LIFECYCLE_CONTROL_DECISION_SCHEMA, [{"code": "control-decision-not-object"}])
    max_payload_bytes = _runtime_limit(
        policy_limits, "maxPayloadBytes", 512, MAX_CONTROL_PAYLOAD_BYTES, MAX_CONTROL_PAYLOAD_BYTES, blockers
    )
    _validate_json_shape(decision, blockers, "control-decision-shape")
    _reject_unknown_fields(decision, _DECISION_FIELDS, blockers, "control-decision-unknown-field")
    if decision.get("schemaVersion") != LIFECYCLE_CONTROL_DECISION_SCHEMA:
        blockers.append({"code": "control-decision-schema"})
    if decision.get("status") not in CONTROL_STATUSES:
        blockers.append({"code": "control-decision-status"})
    if decision.get("effectiveLevel") not in CONTROL_LEVELS:
        blockers.append({"code": "control-decision-level"})
    if decision.get("operation") not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-decision-operation"})
    if decision.get("authority") not in {"frozen-plan-and-state", "guidance-only", "none"}:
        blockers.append({"code": "control-decision-authority"})
    if not isinstance(decision.get("hostActionAllowed"), bool):
        blockers.append({"code": "control-decision-host-action"})
    _validate_blockers(decision.get("blockers"), blockers, "control-decision-blockers")
    if decision.get("status") == "BLOCKED" and decision.get("hostActionAllowed") is not False:
        blockers.append({"code": "control-decision-block-allow-conflict"})
    if decision.get("effectiveLevel") == "ENFORCED" and decision.get("authority") != "frozen-plan-and-state":
        blockers.append({"code": "control-decision-enforced-authority"})
    if decision.get("hostActionAllowed") is True and not (
        decision.get("status") == "PASS" and decision.get("effectiveLevel") == "ENFORCED"
    ):
        blockers.append({"code": "control-decision-host-action-escalation"})
    _validate_payload_size(decision, blockers, max_bytes=max_payload_bytes)
    _reject_untrusted_keys(decision, blockers)
    _validate_redaction(decision, blockers, "control-decision-redaction")
    if decision.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "control-decision-production-claim"})
    _validate_self_digest(decision, "decisionDigest", blockers, "control-decision-digest")
    _validate_digest(decision.get("requestDigest"), blockers, "control-decision-request-digest")
    return _generic_validation(LIFECYCLE_CONTROL_DECISION_SCHEMA, blockers)


def validate_lifecycle_control_event(
    event: dict[str, Any],
    *,
    policy_limits: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_EVENT_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate event lineage, bounded paths and redaction-safe payloads."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(event, dict):
        return _generic_validation(LIFECYCLE_CONTROL_EVENT_SCHEMA, [{"code": "control-event-not-object"}])
    max_payload_bytes = _runtime_limit(
        policy_limits, "maxPayloadBytes", 512, MAX_CONTROL_PAYLOAD_BYTES, MAX_CONTROL_PAYLOAD_BYTES, blockers
    )
    max_changed_paths = _runtime_limit(policy_limits, "maxChangedPaths", 1, 64, 64, blockers)
    max_nonce_bytes = _runtime_limit(policy_limits, "maxNonceBytes", 16, 128, 128, blockers)
    _validate_json_shape(event, blockers, "control-event-shape")
    _reject_unknown_fields(event, _EVENT_FIELDS, blockers, "control-event-unknown-field")
    if event.get("schemaVersion") != LIFECYCLE_CONTROL_EVENT_SCHEMA:
        blockers.append({"code": "control-event-schema"})
    _validate_string(event.get("eventId"), "eventId", 1, MAX_CONTROL_STRING_LENGTH, blockers, "control-event-id")
    _validate_string(event.get("nonce"), "nonce", 16, max_nonce_bytes, blockers, "control-event-nonce")
    if event.get("eventType") not in CONTROL_EVENT_TYPES:
        blockers.append({"code": "control-event-type"})
    if event.get("status") not in CONTROL_STATUSES:
        blockers.append({"code": "control-event-status"})
    if event.get("operation") not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-event-operation"})
    producer = event.get("producer")
    if (
        not isinstance(producer, dict)
        or not isinstance(producer.get("id"), str)
        or producer.get("boundary") != "host-owned"
    ):
        blockers.append({"code": "control-event-producer-boundary"})
    elif not isinstance(producer.get("id"), str) or not 1 <= len(producer["id"]) <= MAX_CONTROL_STRING_LENGTH:
        blockers.append({"code": "control-event-producer-id"})
    _reject_untrusted_keys(event, blockers)
    _validate_paths(event.get("changedPaths"), blockers, "control-event-paths", max_count=max_changed_paths)
    _validate_payload_size(event.get("outcome"), blockers, max_bytes=max_payload_bytes)
    _validate_payload_size(event, blockers, max_bytes=max_payload_bytes)
    _validate_digest(event.get("requestDigest"), blockers, "control-event-request-digest")
    _validate_timestamp(event.get("recordedAt"), blockers, "control-event-recorded-at")
    _validate_freshness(
        event.get("recordedAt"),
        reference_time=reference_time,
        max_age_seconds=max_age_seconds,
        blockers=blockers,
        code_prefix="control-event",
    )
    if event.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "control-event-production-claim"})
    _validate_self_digest(event, "eventDigest", blockers, "control-event-digest")
    _validate_redaction(event, blockers, "control-event-redaction")
    return _generic_validation(LIFECYCLE_CONTROL_EVENT_SCHEMA, blockers)


def validate_lifecycle_control_event_batch(
    events: list[dict[str, Any]],
    *,
    policy_limits: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """Validate an event collection and apply the policy event-count limit."""

    blockers: list[dict[str, Any]] = []
    max_events = _runtime_limit(policy_limits, "maxEvents", 1, 256, 64, blockers)
    if not isinstance(events, list):
        blockers.append({"code": "control-event-batch-shape"})
        events = []
    elif len(events) > max_events:
        blockers.append({"code": "control-event-batch-limit", "maxEvents": max_events})
    results = [
        validate_lifecycle_control_event(item, policy_limits=policy_limits, reference_time=reference_time)
        for item in events[:max_events]
    ]
    for index, result in enumerate(results):
        if result["status"] != "PASS":
            blockers.append({"code": "control-event-invalid", "index": index, "details": result["blockers"]})
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_EVENT_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "eventCount": len(events),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def validate_lifecycle_control_attestation(
    attestation: dict[str, Any],
    *,
    policy_limits: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_ATTESTATION_AGE_SECONDS,
    max_nonce_bytes: int = 128,
) -> dict[str, Any]:
    """Validate attestation bounds and freshness without accepting a signature as authority."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(attestation, dict):
        return _generic_validation(LIFECYCLE_CONTROL_ATTESTATION_SCHEMA, [{"code": "control-attestation-not-object"}])
    max_nonce_bytes = _runtime_limit(policy_limits, "maxNonceBytes", 16, 128, max_nonce_bytes, blockers)
    max_age_seconds = _runtime_limit(
        policy_limits,
        "maxAttestationAgeSeconds",
        1,
        3600,
        max_age_seconds,
        blockers,
    )
    _validate_json_shape(attestation, blockers, "control-attestation-shape")
    _reject_unknown_fields(attestation, _ATTESTATION_FIELDS, blockers, "control-attestation-unknown-field")
    if attestation.get("schemaVersion") != LIFECYCLE_CONTROL_ATTESTATION_SCHEMA:
        blockers.append({"code": "control-attestation-schema"})
    for field in ("attestationId", "producerId", "adapterId", "hostVersion", "keyId"):
        _validate_string(
            attestation.get(field), field, 1, MAX_CONTROL_STRING_LENGTH, blockers, f"control-attestation-{field}"
        )
    _validate_string(attestation.get("nonce"), "nonce", 16, max_nonce_bytes, blockers, "control-attestation-nonce")
    _validate_string(attestation.get("signature"), "signature", 1, 2048, blockers, "control-attestation-signature")
    _validate_integer(
        attestation.get("stateRevision"), "stateRevision", 1, blockers, "control-attestation-state-revision"
    )
    if attestation.get("domain") != LIFECYCLE_CONTROL_ATTESTATION_SCHEMA:
        blockers.append({"code": "control-attestation-domain"})
    if attestation.get("operation") not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-attestation-operation"})
    for field in (*_DIGEST_FIELDS, "outcomeDigest"):
        _validate_digest(attestation.get(field), blockers, f"control-attestation-{field}")
    _validate_timestamp(attestation.get("issuedAt"), blockers, "control-attestation-issued-at")
    _validate_timestamp(attestation.get("expiresAt"), blockers, "control-attestation-expires-at")
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or not 1 <= max_age_seconds <= 3600:
        blockers.append({"code": "control-attestation-max-age-invalid"})
        max_age_seconds = DEFAULT_MAX_ATTESTATION_AGE_SECONDS
    issued = _parse_time(attestation.get("issuedAt"))
    expires = _parse_time(attestation.get("expiresAt"))
    if issued is not None and expires is not None:
        if expires <= issued:
            blockers.append({"code": "control-attestation-expiry-order"})
        if (expires - issued).total_seconds() > max_age_seconds:
            blockers.append({"code": "control-attestation-expiry-too-long"})
        current = datetime.now(UTC) if reference_time is None else _coerce_reference_time(reference_time)
        if current is None:
            blockers.append({"code": "control-attestation-reference-time"})
        elif current < issued:
            blockers.append({"code": "control-attestation-not-yet-valid"})
        elif current > expires:
            blockers.append({"code": "control-attestation-expired"})
    if attestation.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "control-attestation-production-claim"})
    _reject_untrusted_keys(attestation, blockers)
    _validate_self_digest(attestation, "attestationDigest", blockers, "control-attestation-digest")
    _validate_redaction(attestation, blockers, "control-attestation-redaction")
    return _generic_validation(LIFECYCLE_CONTROL_ATTESTATION_SCHEMA, blockers)


def validate_lifecycle_control_qualification_receipt(
    receipt: dict[str, Any], *, policy_limits: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Require both positive and negative evidence before qualifying enforcement."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        return _qualification_validation("UNAVAILABLE", [{"code": "control-qualification-not-object"}])
    max_payload_bytes = _runtime_limit(
        policy_limits, "maxPayloadBytes", 512, MAX_CONTROL_PAYLOAD_BYTES, MAX_CONTROL_PAYLOAD_BYTES, blockers
    )
    _validate_json_shape(receipt, blockers, "control-qualification-shape")
    _reject_unknown_fields(receipt, _QUALIFICATION_FIELDS, blockers, "control-qualification-unknown-field")
    if receipt.get("schemaVersion") != LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA:
        blockers.append({"code": "control-qualification-schema"})
    for field in ("adapterId", "host", "hostVersion"):
        _validate_string(
            receipt.get(field), field, 1, MAX_CONTROL_STRING_LENGTH, blockers, f"control-qualification-{field}"
        )
    if receipt.get("operation") not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-qualification-operation"})
    status = receipt.get("status")
    if status not in QUALIFICATION_STATUSES:
        blockers.append({"code": "control-qualification-status"})
        status = "UNAVAILABLE"
    levels = [receipt.get(field) for field in ("declaredLevel", "supportedLevel", "qualifiedLevel")]
    if any(level not in CONTROL_LEVELS for level in levels):
        blockers.append({"code": "control-qualification-level"})
    elif not (_LEVEL_RANK[str(levels[0])] >= _LEVEL_RANK[str(levels[1])] >= _LEVEL_RANK[str(levels[2])]):
        blockers.append({"code": "control-qualification-level-escalation"})
    positive = receipt.get("positiveEvidence")
    negative = receipt.get("negativeEvidence")
    if not isinstance(positive, list) or not isinstance(negative, list):
        blockers.append({"code": "control-qualification-evidence-shape"})
        positive = []
        negative = []
    elif len(positive) > 64 or len(negative) > 64:
        blockers.append({"code": "control-qualification-evidence-bound"})
    elif any(not isinstance(item, dict) for item in positive + negative):
        blockers.append({"code": "control-qualification-evidence-item"})
    evidence_refs = receipt.get("evidenceRefs")
    if (
        not isinstance(evidence_refs, list)
        or len(evidence_refs) > 64
        or any(
            not isinstance(item, str) or not item for item in (evidence_refs if isinstance(evidence_refs, list) else [])
        )
    ):
        blockers.append({"code": "control-qualification-evidence-refs"})
    _validate_blockers(receipt.get("blockers"), blockers, "control-qualification-blockers")
    if receipt.get("qualifiedLevel") == "ENFORCED" and (not positive or not negative):
        blockers.append({"code": "control-qualification-negative-evidence-required"})
    if receipt.get("status") != "QUALIFIED" and receipt.get("qualifiedLevel") == "ENFORCED":
        blockers.append({"code": "control-qualification-status-escalation"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "control-qualification-production-claim"})
    _reject_untrusted_keys(receipt, blockers)
    _validate_payload_size(receipt, blockers, max_bytes=max_payload_bytes)
    _validate_self_digest(receipt, "receiptDigest", blockers, "control-qualification-digest")
    _validate_redaction(receipt, blockers, "control-qualification-redaction")
    return _qualification_validation(status, blockers)


def _validate_operation_entry(operation: str, entry: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    for field in ("declaredLevel", "effectiveLevel"):
        if entry.get(field) not in CONTROL_LEVELS:
            blockers.append({"code": "control-policy-level", "operation": operation, "field": field})
    if entry.get("supported") not in {True, False} or entry.get("qualified") not in {True, False}:
        blockers.append({"code": "control-policy-status", "operation": operation})
    if entry.get("qualificationStatus") not in {"UNQUALIFIED", "QUALIFIED", "UNAVAILABLE", "BLOCKED"}:
        blockers.append({"code": "control-policy-qualification-status", "operation": operation})
    if entry.get("hostOwnedPreAction") not in {True, False}:
        blockers.append({"code": "control-policy-pre-action-ownership", "operation": operation})
    declared = entry.get("declaredLevel")
    effective = entry.get("effectiveLevel")
    if declared in _LEVEL_RANK and effective in _LEVEL_RANK and _LEVEL_RANK[effective] > _LEVEL_RANK[declared]:
        blockers.append({"code": "control-policy-level-escalation", "operation": operation})
    if (
        entry.get("supported") is not True
        and effective in _LEVEL_RANK
        and _LEVEL_RANK[effective] > _LEVEL_RANK["GUIDANCE_ONLY"]
    ):
        blockers.append({"code": "control-policy-unsupported-effective-level", "operation": operation})
    if entry.get("qualified") is not True and effective == "ENFORCED":
        blockers.append({"code": "control-policy-unqualified-enforced", "operation": operation})
    if entry.get("qualified") is True and entry.get("qualificationStatus") != "QUALIFIED":
        blockers.append({"code": "control-policy-qualified-status", "operation": operation})


def _check_common_identity(value: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    for field in ("requestId", "adapterId", "host", "hostVersion", "runId", "taskId", "packageId", "producerId"):
        _validate_string(value.get(field), field, 1, MAX_CONTROL_STRING_LENGTH, blockers, "control-request-field")
    for field in ("planRevision", "stateRevision"):
        _validate_integer(value.get(field), field, 1, blockers, "control-request-revision")
    for field in _DIGEST_FIELDS:
        _validate_digest(value.get(field), blockers, f"control-request-{field}")


def _reject_unknown_fields(
    value: dict[str, Any],
    allowed: set[str],
    blockers: list[dict[str, Any]],
    code: str,
    *,
    path: str = "",
) -> None:
    for field in sorted((key for key in value if key not in allowed), key=str):
        blockers.append({"code": code, "field": f"{path}.{field}".strip(".")})


def _validate_paths(value: Any, blockers: list[dict[str, Any]], code: str, *, max_count: int = 64) -> None:
    if not isinstance(value, list) or len(value) > max_count:
        blockers.append({"code": code, "reason": "array-bound"})
        return
    for path in value:
        if not isinstance(path, str):
            blockers.append({"code": code, "reason": "path-not-string"})
            continue
        try:
            if normalize_repo_path(path) != path:
                blockers.append({"code": code, "reason": "path-not-normalized", "path": path})
        except LifecycleError:
            blockers.append({"code": code, "reason": "path-unsafe", "path": path})


def _validate_digest(value: Any, blockers: list[dict[str, Any]], code: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        blockers.append({"code": code})


def _validate_self_digest(value: dict[str, Any], field: str, blockers: list[dict[str, Any]], code: str) -> None:
    digest = value.get(field)
    _validate_digest(digest, blockers, code)
    try:
        computed = canonical_digest({key: item for key, item in value.items() if key != field})
    except (LifecycleError, TypeError):
        blockers.append({"code": f"{code}-input-invalid"})
        return
    if isinstance(digest, str) and digest == computed:
        return
    if isinstance(digest, str) and len(digest) == 64:
        blockers.append({"code": f"{code}-mismatch"})


def _validate_timestamp(value: Any, blockers: list[dict[str, Any]], code: str) -> None:
    if not isinstance(value, str) or len(value) > 64 or _parse_time(value) is None:
        blockers.append({"code": code})


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _coerce_reference_time(value: datetime) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(UTC)


def _validate_string(
    value: Any,
    field: str,
    minimum: int,
    maximum: int,
    blockers: list[dict[str, Any]],
    code: str,
) -> None:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        blockers.append({"code": code, "field": field})


def _validate_integer(value: Any, field: str, minimum: int, blockers: list[dict[str, Any]], code: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        blockers.append({"code": code, "field": field})


def _validate_blockers(value: Any, blockers: list[dict[str, Any]], code: str) -> None:
    if not isinstance(value, list) or len(value) > 64 or any(not isinstance(item, dict) for item in value):
        blockers.append({"code": code})


def _runtime_limit(
    policy_limits: dict[str, Any] | None,
    field: str,
    minimum: int,
    maximum: int,
    default: int,
    blockers: list[dict[str, Any]],
) -> int:
    if policy_limits is None:
        return default
    value = policy_limits.get(field) if isinstance(policy_limits, dict) else None
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        blockers.append({"code": "control-runtime-limit", "field": field})
        return default
    return value


def _require_runtime_limit(value: Any, minimum: int, maximum: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise LifecycleError("control-runtime-limit-invalid", f"invalid lifecycle control limit: {field}")


def _validate_freshness(
    value: Any,
    *,
    reference_time: datetime | None,
    max_age_seconds: int,
    blockers: list[dict[str, Any]],
    code_prefix: str,
) -> None:
    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or not 1 <= max_age_seconds <= 86400:
        blockers.append({"code": f"{code_prefix}-max-age-invalid"})
        return
    parsed = _parse_time(value)
    if parsed is None:
        return
    current = datetime.now(UTC) if reference_time is None else _coerce_reference_time(reference_time)
    if current is None:
        blockers.append({"code": f"{code_prefix}-reference-time"})
        return
    if current < parsed:
        blockers.append({"code": f"{code_prefix}-not-yet-valid"})
    elif (current - parsed).total_seconds() > max_age_seconds:
        blockers.append({"code": f"{code_prefix}-stale"})


def _validate_payload_size(
    value: Any, blockers: list[dict[str, Any]], *, max_bytes: int = MAX_CONTROL_PAYLOAD_BYTES
) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "control-event-outcome-shape"})
        return
    try:
        payload_bytes = len(canonical_bytes(value))
    except (LifecycleError, TypeError):
        blockers.append({"code": "control-event-payload-invalid"})
        return
    if payload_bytes > max_bytes:
        blockers.append({"code": "control-event-payload-too-large", "maxBytes": max_bytes})


def _validate_json_shape(value: Any, blockers: list[dict[str, Any]], code: str, *, depth: int = 0) -> None:
    if depth > MAX_CONTROL_NESTING:
        blockers.append({"code": code, "reason": "nesting-bound"})
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                blockers.append({"code": code, "reason": "object-key-not-string"})
            _validate_json_shape(item, blockers, code, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate_json_shape(item, blockers, code, depth=depth + 1)
    elif isinstance(value, str) and len(value) > MAX_CONTROL_REDACTION_STRING_LENGTH:
        blockers.append({"code": code, "reason": "string-bound"})
    elif isinstance(value, float) and not math.isfinite(value):
        blockers.append({"code": code, "reason": "non-finite-number"})
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        blockers.append({"code": code, "reason": "value-type"})


def _validate_redaction(value: Any, blockers: list[dict[str, Any]], code: str) -> None:
    try:
        if len(canonical_bytes(value)) > MAX_CONTROL_PAYLOAD_BYTES:
            return
        redacted, _changed = redact_value(value)
    except (LifecycleError, MemoryError, RecursionError, TypeError, ValueError):
        blockers.append({"code": code, "reason": "redaction-failed"})
        return
    if redacted != value:
        blockers.append({"code": code, "reason": "unredacted-sensitive-value"})


def _positive_bounded(
    value: dict[str, Any], field: str, minimum: int, maximum: int, blockers: list[dict[str, Any]]
) -> None:
    item = value.get(field)
    if not isinstance(item, int) or isinstance(item, bool) or not minimum <= item <= maximum:
        blockers.append({"code": "control-policy-limit", "field": field})


def _reject_untrusted_keys(value: Any, blockers: list[dict[str, Any]], *, path: str = "") -> None:
    _reject_untrusted_keys_bounded(value, blockers, path=path, depth=0)


def _reject_untrusted_keys_bounded(value: Any, blockers: list[dict[str, Any]], *, path: str, depth: int) -> None:
    if depth > MAX_CONTROL_NESTING:
        blockers.append({"code": "control-nesting-too-deep", "field": path})
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and (key in _UNTRUSTED_KEYS or is_sensitive_key(key)) and item != "<redacted>":
                blockers.append({"code": "control-untrusted-field", "field": f"{path}.{key}".strip(".")})
            if item != "<redacted>":
                _reject_untrusted_keys_bounded(item, blockers, path=f"{path}.{key}".strip("."), depth=depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_untrusted_keys_bounded(item, blockers, path=f"{path}[{index}]", depth=depth + 1)


def _sanitize_control_value(value: Any, *, depth: int = 0) -> Any:
    """Keep untrusted producer fields bounded without retaining their content."""

    if depth > MAX_CONTROL_NESTING:
        raise LifecycleError(
            "control-nesting-too-deep", "lifecycle control payload is nested beyond the configured limit"
        )
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key in _UNTRUSTED_KEYS:
                result[key] = "<redacted>"
            else:
                result[key] = _sanitize_control_value(item, depth=depth + 1)
        redacted, _ = redact_value(result)
        return redacted
    if isinstance(value, list):
        return [_sanitize_control_value(item, depth=depth + 1) for item in value]
    return value


def _generic_validation(schema: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": schema,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _validation_result(policy_id: str | None, blockers: list[dict[str, Any]], *, digest: Any = None) -> dict[str, Any]:
    safe_digest = digest if isinstance(digest, str) else None
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_POLICY_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "policyId": policy_id,
        "policyDigest": safe_digest,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _qualification_validation(status: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_QUALIFICATION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "qualificationStatus": status,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}
