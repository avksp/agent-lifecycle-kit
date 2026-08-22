"""Contracts for optional, provider-neutral adapter lifecycle control."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes, canonical_digest
from agent_lifecycle.contracts.lifecycle_control_definitions import (
    _LEVEL_RANK,
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
    LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA,
    LIFECYCLE_CONTROL_REQUEST_SCHEMA,
    MAX_CONTROL_NESTING,
    MAX_CONTROL_PAYLOAD_BYTES,
    MAX_CONTROL_REDACTION_STRING_LENGTH,
    MAX_CONTROL_STRING_LENGTH,
    QUALIFICATION_STATUSES,
)

if TYPE_CHECKING:
    LIFECYCLE_CONTROL_SCHEMAS: dict[str, dict[str, Any]]


def _validate_json_shape(value: Any, blockers: list[dict[str, Any]], code: str, *, depth: int = 0) -> None:
    from agent_lifecycle.contracts.lifecycle_control_validation import _validate_json_shape as impl

    return impl(value, blockers, code, depth=depth)


def _require_runtime_limit(value: Any, minimum: int, maximum: int, field: str) -> None:
    from agent_lifecycle.contracts.lifecycle_control_validation import _require_runtime_limit as impl

    return impl(value, minimum, maximum, field)


def _sanitize_control_value(value: Any, *, depth: int = 0) -> Any:
    from agent_lifecycle.contracts.lifecycle_control_validation import _sanitize_control_value as impl

    return impl(value, depth=depth)


def build_default_lifecycle_control_policy() -> dict[str, Any]:
    """Build the safe default policy without enabling host enforcement."""

    operations = {
        operation: {
            "declaredLevel": "GUIDANCE_ONLY",
            "supported": False,
            "qualified": False,
            "effectiveLevel": "GUIDANCE_ONLY",
            "qualificationStatus": "UNQUALIFIED",
            "hostOwnedPreAction": False,
        }
        for operation in CONTROL_OPERATIONS
    }
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_POLICY_SCHEMA,
        "policyId": "provider-neutral-adapter-lifecycle-control",
        "revision": 1,
        "defaultLevel": "GUIDANCE_ONLY",
        "operations": operations,
        "limits": {
            "maxEvents": 64,
            "maxPayloadBytes": 8192,
            "maxChangedPaths": 64,
            "maxAttestationAgeSeconds": 300,
            "maxNonceBytes": 128,
        },
        "authority": {
            "modelWritable": False,
            "settingsAutoEdited": False,
            "keysExternal": True,
            "providerIdentityUsed": False,
        },
        "productionPromotionClaimed": False,
    }
    return {**body, "policyDigest": canonical_digest(body)}


def resolve_lifecycle_control(
    policy: dict[str, Any],
    operation: str,
    *,
    requested_level: str | None = None,
) -> dict[str, Any]:
    """Resolve an operation level without treating declarations as proof."""

    validation = validate_lifecycle_control_policy(policy)
    blockers = list(validation["blockers"])
    policy_is_valid = validation["status"] == "PASS"
    policy_object = policy if isinstance(policy, dict) else {}
    entry = (
        policy_object.get("operations", {}).get(operation)
        if policy_is_valid and isinstance(policy_object.get("operations"), dict)
        else None
    )
    if operation not in CONTROL_OPERATIONS:
        blockers.append({"code": "control-operation-unsupported", "operation": operation})
        entry = {}
    elif not policy_is_valid:
        entry = {}
    elif not isinstance(entry, dict):
        blockers.append({"code": "control-operation-unsupported", "operation": operation})
        entry = {}
    effective = entry.get("effectiveLevel", "GUIDANCE_ONLY")
    if effective not in CONTROL_LEVELS:
        effective = "GUIDANCE_ONLY"
        blockers.append({"code": "control-effective-level-invalid", "operation": operation})
    if isinstance(entry, dict):
        if entry.get("supported") is not True and _LEVEL_RANK.get(effective, 0) > _LEVEL_RANK["GUIDANCE_ONLY"]:
            blockers.append({"code": "control-support-not-proven", "operation": operation})
            effective = "GUIDANCE_ONLY"
        if entry.get("qualified") is not True and effective == "ENFORCED":
            blockers.append({"code": "control-qualification-not-proven", "operation": operation})
            effective = "GUIDANCE_ONLY"
    if requested_level not in (None, *CONTROL_LEVELS):
        blockers.append({"code": "control-requested-level-invalid"})
    if requested_level in CONTROL_LEVELS and _LEVEL_RANK[effective] < _LEVEL_RANK[requested_level]:
        blockers.append(
            {"code": "control-requested-level-unavailable", "requested": requested_level, "effective": effective}
        )
    return {
        "schemaVersion": LIFECYCLE_CONTROL_DECISION_SCHEMA,
        "status": "PASS" if not blockers else "REVIEW_REQUIRED",
        "operation": operation,
        "declaredLevel": entry.get("declaredLevel", "GUIDANCE_ONLY"),
        "supported": entry.get("supported", False),
        "qualified": entry.get("qualified", False),
        "effectiveLevel": effective,
        "qualificationStatus": entry.get("qualificationStatus", "UNQUALIFIED"),
        "hostOwnedPreAction": entry.get("hostOwnedPreAction", False),
        "blockers": blockers,
        "policyDigest": policy_object.get("policyDigest")
        if isinstance(policy_object.get("policyDigest"), str)
        else None,
        "productionPromotionClaimed": False,
    }


def build_lifecycle_control_request(
    *,
    request_id: str,
    adapter_id: str,
    host: str,
    host_version: str,
    operation: str,
    run_id: str,
    task_id: str,
    package_id: str,
    plan_revision: int,
    plan_digest: str,
    lock_digest: str,
    state_revision: int,
    action_digest: str,
    paths: list[str],
    requested_level: str = "GUIDANCE_ONLY",
    producer_id: str = "host-producer",
    nonce: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a bounded request that contains no prompt or environment data."""

    nonce = nonce or secrets.token_hex(16)
    created_at = created_at or _now_iso()
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_REQUEST_SCHEMA,
        "requestId": request_id,
        "adapterId": adapter_id,
        "host": host,
        "hostVersion": host_version,
        "operation": operation,
        "runId": run_id,
        "taskId": task_id,
        "packageId": package_id,
        "planRevision": plan_revision,
        "planDigest": plan_digest,
        "lockDigest": lock_digest,
        "stateRevision": state_revision,
        "actionDigest": action_digest,
        "paths": list(paths),
        "requestedLevel": requested_level,
        "producerId": producer_id,
        "nonce": nonce,
        "createdAt": created_at,
        "productionPromotionClaimed": False,
    }
    return {**body, "requestDigest": canonical_digest(body)}


def build_lifecycle_control_decision(
    request: dict[str, Any],
    *,
    status: str,
    effective_level: str,
    host_action_allowed: bool,
    blockers: list[dict[str, Any]] | None = None,
    max_payload_bytes: int = MAX_CONTROL_PAYLOAD_BYTES,
) -> dict[str, Any]:
    """Build a deterministic decision bound to one control request."""

    request_validation = validate_lifecycle_control_request(request)
    if request_validation["status"] != "PASS":
        raise LifecycleError(
            "control-request-invalid", "cannot decide an invalid lifecycle control request", request_validation
        )
    if status not in CONTROL_STATUSES or effective_level not in CONTROL_LEVELS:
        raise LifecycleError("control-decision-invalid", "unsupported control decision status or level")
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_DECISION_SCHEMA,
        "status": status,
        "requestDigest": request["requestDigest"],
        "operation": request["operation"],
        "effectiveLevel": effective_level,
        "hostActionAllowed": bool(host_action_allowed),
        "authority": "frozen-plan-and-state" if effective_level == "ENFORCED" else "guidance-only",
        "blockers": list(blockers or []),
        "productionPromotionClaimed": False,
    }
    if status == "BLOCKED" and host_action_allowed:
        raise LifecycleError("control-decision-invalid", "blocked decision cannot allow host action")
    shape_blockers: list[dict[str, Any]] = []
    _validate_json_shape(body, shape_blockers, "control-decision-shape")
    if shape_blockers:
        raise LifecycleError("control-decision-payload-invalid", "lifecycle control decision has an invalid JSON shape")
    _require_runtime_limit(max_payload_bytes, 512, MAX_CONTROL_PAYLOAD_BYTES, "maxPayloadBytes")
    if len(canonical_bytes(body)) > max_payload_bytes:
        raise LifecycleError(
            "control-decision-payload-too-large", "lifecycle control decision exceeds the configured byte limit"
        )
    return {**body, "decisionDigest": canonical_digest(body)}


def build_lifecycle_control_event(
    request: dict[str, Any],
    *,
    event_id: str,
    event_type: str,
    status: str,
    producer_id: str,
    outcome: dict[str, Any] | None = None,
    changed_paths: list[str] | None = None,
    recorded_at: str | None = None,
    max_payload_bytes: int = MAX_CONTROL_PAYLOAD_BYTES,
    max_changed_paths: int = 64,
) -> dict[str, Any]:
    """Build a redacted bounded event tied to the request nonce and digest."""

    if validate_lifecycle_control_request(request)["status"] != "PASS":
        raise LifecycleError("control-request-invalid", "cannot build an event for an invalid request")
    if event_type not in CONTROL_EVENT_TYPES or status not in CONTROL_STATUSES:
        raise LifecycleError("control-event-invalid", "unsupported control event type or status")
    _require_runtime_limit(max_payload_bytes, 512, MAX_CONTROL_PAYLOAD_BYTES, "maxPayloadBytes")
    _require_runtime_limit(max_changed_paths, 1, 64, "maxChangedPaths")
    recorded_at = recorded_at or _now_iso()
    event_paths = list(changed_paths or [])
    if len(event_paths) > max_changed_paths:
        raise LifecycleError("control-event-path-limit", "lifecycle control event has too many changed paths")
    safe_outcome = _sanitize_control_value(dict(outcome or {}))
    shape_blockers: list[dict[str, Any]] = []
    _validate_json_shape(safe_outcome, shape_blockers, "control-event-outcome-shape")
    if shape_blockers:
        raise LifecycleError(
            "control-event-payload-invalid", "lifecycle control event payload has an invalid JSON shape"
        )
    try:
        payload_bytes = len(canonical_bytes(safe_outcome))
    except LifecycleError as exc:
        raise LifecycleError(
            "control-event-payload-invalid", "lifecycle control event payload cannot be canonicalized"
        ) from exc
    if payload_bytes > max_payload_bytes:
        raise LifecycleError(
            "control-event-payload-too-large",
            "lifecycle control event payload exceeds the configured byte limit",
            {"byteCount": payload_bytes, "maxBytes": max_payload_bytes},
        )
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_EVENT_SCHEMA,
        "eventId": event_id,
        "eventType": event_type,
        "status": status,
        "requestDigest": request["requestDigest"],
        "operation": request["operation"],
        "producer": {"id": producer_id, "boundary": "host-owned"},
        "nonce": request["nonce"],
        "changedPaths": event_paths,
        "outcome": safe_outcome,
        "recordedAt": recorded_at,
        "productionPromotionClaimed": False,
    }
    return {**body, "eventDigest": canonical_digest(body)}


def lifecycle_control_limits(policy: dict[str, Any]) -> dict[str, int]:
    """Return validated runtime limits for policy-aware envelope validation."""

    validation = validate_lifecycle_control_policy(policy)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "lifecycle-control-policy-invalid", "cannot use limits from an invalid control policy", validation
        )
    return {key: int(value) for key, value in policy["limits"].items()}


def build_lifecycle_control_attestation(
    *,
    attestation_id: str,
    producer_id: str,
    adapter_id: str,
    host_version: str,
    operation: str,
    nonce: str,
    issued_at: str,
    expires_at: str,
    plan_digest: str,
    lock_digest: str,
    state_revision: int,
    action_digest: str,
    outcome_digest: str,
    key_id: str,
    signature: str,
) -> dict[str, Any]:
    """Build a domain-separated attestation envelope; signing stays external."""

    body = {
        "schemaVersion": LIFECYCLE_CONTROL_ATTESTATION_SCHEMA,
        "attestationId": attestation_id,
        "domain": LIFECYCLE_CONTROL_ATTESTATION_SCHEMA,
        "producerId": producer_id,
        "adapterId": adapter_id,
        "hostVersion": host_version,
        "operation": operation,
        "nonce": nonce,
        "issuedAt": issued_at,
        "expiresAt": expires_at,
        "planDigest": plan_digest,
        "lockDigest": lock_digest,
        "stateRevision": state_revision,
        "actionDigest": action_digest,
        "outcomeDigest": outcome_digest,
        "keyId": key_id,
        "signature": signature,
        "productionPromotionClaimed": False,
    }
    return {**body, "attestationDigest": canonical_digest(body)}


def build_lifecycle_control_qualification_receipt(
    *,
    adapter_id: str,
    host: str,
    host_version: str,
    operation: str,
    declared_level: str,
    supported_level: str,
    qualified_level: str,
    status: str,
    positive_evidence: list[dict[str, Any]],
    negative_evidence: list[dict[str, Any]],
    evidence_refs: list[str],
    blockers: list[dict[str, Any]] | None = None,
    max_payload_bytes: int = MAX_CONTROL_PAYLOAD_BYTES,
) -> dict[str, Any]:
    """Build a qualification result without promoting a host automatically."""

    body = {
        "schemaVersion": LIFECYCLE_CONTROL_QUALIFICATION_SCHEMA,
        "status": status,
        "adapterId": adapter_id,
        "host": host,
        "hostVersion": host_version,
        "operation": operation,
        "declaredLevel": declared_level,
        "supportedLevel": supported_level,
        "qualifiedLevel": qualified_level,
        "positiveEvidence": _sanitize_control_value(list(positive_evidence)),
        "negativeEvidence": _sanitize_control_value(list(negative_evidence)),
        "evidenceRefs": list(evidence_refs),
        "blockers": list(blockers or []),
        "productionPromotionClaimed": False,
    }
    shape_blockers: list[dict[str, Any]] = []
    _validate_json_shape(body, shape_blockers, "control-qualification-shape")
    if shape_blockers:
        raise LifecycleError("control-qualification-invalid", "qualification receipt has an invalid JSON shape")
    _require_runtime_limit(max_payload_bytes, 512, MAX_CONTROL_PAYLOAD_BYTES, "maxPayloadBytes")
    if len(canonical_bytes(body)) > max_payload_bytes:
        raise LifecycleError(
            "control-qualification-payload-too-large", "qualification receipt exceeds the configured byte limit"
        )
    return {**body, "receiptDigest": canonical_digest(body)}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_lifecycle_control_policy(policy: dict[str, Any]) -> dict[str, Any]:
    from agent_lifecycle.contracts.lifecycle_control_validation import validate_lifecycle_control_policy as impl

    return impl(policy)


def validate_lifecycle_control_request(
    request: dict[str, Any],
    *,
    policy_limits: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_REQUEST_AGE_SECONDS,
) -> dict[str, Any]:
    from agent_lifecycle.contracts.lifecycle_control_validation import validate_lifecycle_control_request as impl

    return impl(request, policy_limits=policy_limits, reference_time=reference_time, max_age_seconds=max_age_seconds)


def validate_lifecycle_control_decision(
    decision: dict[str, Any], *, policy_limits: dict[str, Any] | None = None
) -> dict[str, Any]:
    from agent_lifecycle.contracts.lifecycle_control_validation import validate_lifecycle_control_decision as impl

    return impl(decision, policy_limits=policy_limits)


def validate_lifecycle_control_event(
    event: dict[str, Any],
    *,
    policy_limits: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_EVENT_AGE_SECONDS,
) -> dict[str, Any]:
    from agent_lifecycle.contracts.lifecycle_control_validation import validate_lifecycle_control_event as impl

    return impl(event, policy_limits=policy_limits, reference_time=reference_time, max_age_seconds=max_age_seconds)


def validate_lifecycle_control_event_batch(
    events: list[dict[str, Any]], *, policy_limits: dict[str, Any] | None = None, reference_time: datetime | None = None
) -> dict[str, Any]:
    from agent_lifecycle.contracts.lifecycle_control_validation import validate_lifecycle_control_event_batch as impl

    return impl(events, policy_limits=policy_limits, reference_time=reference_time)


def validate_lifecycle_control_attestation(
    attestation: dict[str, Any],
    *,
    policy_limits: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_ATTESTATION_AGE_SECONDS,
    max_nonce_bytes: int = 128,
) -> dict[str, Any]:
    from agent_lifecycle.contracts.lifecycle_control_validation import validate_lifecycle_control_attestation as impl

    return impl(
        attestation,
        policy_limits=policy_limits,
        reference_time=reference_time,
        max_age_seconds=max_age_seconds,
        max_nonce_bytes=max_nonce_bytes,
    )


def validate_lifecycle_control_qualification_receipt(
    receipt: dict[str, Any], *, policy_limits: dict[str, Any] | None = None
) -> dict[str, Any]:
    from agent_lifecycle.contracts.lifecycle_control_validation import (
        validate_lifecycle_control_qualification_receipt as impl,
    )

    return impl(receipt, policy_limits=policy_limits)


def __getattr__(name: str) -> Any:
    """Load the registry from the composition module without an import cycle."""

    if name == "LIFECYCLE_CONTROL_SCHEMAS":
        from agent_lifecycle.contracts.schemas import _LIFECYCLE_CONTROL_SCHEMAS

        return _LIFECYCLE_CONTROL_SCHEMAS
    raise AttributeError(name)


__all__ = [
    "CONTROL_EVENT_TYPES",
    "CONTROL_LEVELS",
    "CONTROL_OPERATIONS",
    "CONTROL_STATUSES",
    "DEFAULT_MAX_ATTESTATION_AGE_SECONDS",
    "DEFAULT_MAX_EVENT_AGE_SECONDS",
    "DEFAULT_MAX_REQUEST_AGE_SECONDS",
    "LIFECYCLE_CONTROL_SCHEMAS",
    "MAX_CONTROL_NESTING",
    "MAX_CONTROL_PAYLOAD_BYTES",
    "MAX_CONTROL_REDACTION_STRING_LENGTH",
    "MAX_CONTROL_STRING_LENGTH",
    "QUALIFICATION_STATUSES",
    "build_default_lifecycle_control_policy",
    "build_lifecycle_control_attestation",
    "build_lifecycle_control_decision",
    "build_lifecycle_control_event",
    "build_lifecycle_control_qualification_receipt",
    "build_lifecycle_control_request",
    "lifecycle_control_limits",
    "resolve_lifecycle_control",
    "validate_lifecycle_control_attestation",
    "validate_lifecycle_control_decision",
    "validate_lifecycle_control_event",
    "validate_lifecycle_control_event_batch",
    "validate_lifecycle_control_policy",
    "validate_lifecycle_control_qualification_receipt",
    "validate_lifecycle_control_request",
]
