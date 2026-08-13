"""Neutral validation for adapter-provided context checkpoint events."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.context_checkpoint_schemas import CHECKPOINT_MODES
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.context.checkpoints import EVENT_SCHEMA, _reject_authority_fields, validate_native_hook_evidence


def build_context_checkpoint_event(
    *,
    event_type: str,
    session_id: str,
    run_id: str,
    operation_id: str,
    state_revision: int,
    capture_mode: str,
    checkpoint_digest: str | None,
    payload: dict[str, Any] | None = None,
    recorded_at: str = "1970-01-01T00:00:00Z",
    event_id: str | None = None,
) -> dict[str, Any]:
    if event_type not in {"context.checkpoint.created", "context.checkpoint.unavailable"}:
        raise LifecycleError("context-event-type-invalid", "unsupported context checkpoint event type")
    if capture_mode not in CHECKPOINT_MODES:
        raise LifecycleError("context-event-mode-invalid", "unsupported context checkpoint event mode")
    if not isinstance(payload, dict):
        payload = {}
    _reject_authority_fields(payload, path="payload")
    payload, redaction_applied = redact_value(payload)
    if redaction_applied:
        payload = {**payload, "redactionApplied": True}
    body = {
        "schemaVersion": EVENT_SCHEMA,
        "eventId": event_id or canonical_digest({"sessionId": session_id, "runId": run_id, "operationId": operation_id, "stateRevision": state_revision, "eventType": event_type})[:24],
        "eventType": event_type,
        "sessionId": session_id,
        "runId": run_id,
        "operationId": operation_id,
        "stateRevision": state_revision,
        "captureMode": capture_mode,
        "checkpointDigest": checkpoint_digest,
        "recordedAt": recorded_at,
        "payload": payload,
        "productionPromotionClaimed": False,
    }
    body["eventDigest"] = canonical_digest(body)
    return body


def validate_context_checkpoint_event(
    event: dict[str, Any],
    *,
    expected_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(event, dict):
        blockers.append({"code": "context-event-object-required"})
        return _event_validation(None, blockers)
    required = ("schemaVersion", "eventId", "eventType", "sessionId", "runId", "operationId", "stateRevision", "captureMode", "checkpointDigest", "recordedAt", "payload", "productionPromotionClaimed", "eventDigest")
    missing = [key for key in required if key not in event]
    if missing:
        blockers.append({"code": "context-event-fields-missing", "fields": missing})
    if event.get("schemaVersion") != EVENT_SCHEMA:
        blockers.append({"code": "context-event-schema-invalid"})
    if event.get("eventType") == "context.checkpoint.created" and not isinstance(event.get("checkpointDigest"), str):
        blockers.append({"code": "context-event-checkpoint-missing"})
    if event.get("eventType") == "context.checkpoint.unavailable" and event.get("checkpointDigest") is not None:
        blockers.append({"code": "context-event-unavailable-has-checkpoint"})
    if event.get("captureMode") not in CHECKPOINT_MODES:
        blockers.append({"code": "context-event-mode-invalid"})
    if event.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "context-event-production-claim"})
    payload = event.get("payload")
    if not isinstance(payload, dict):
        blockers.append({"code": "context-event-payload-invalid"})
    else:
        try:
            _reject_authority_fields(payload, path="payload")
        except LifecycleError as exc:
            blockers.append({"code": exc.code, "message": exc.message})
        redacted, changed = redact_value(payload)
        if changed and redacted != payload:
            blockers.append({"code": "context-event-unredacted-sensitive-input"})
        if event.get("captureMode") == "NATIVE_HOOK":
            evidence = payload.get("nativeHookEvidence")
            try:
                validate_native_hook_evidence(evidence)
            except LifecycleError as exc:
                blockers.append({"code": f"context-event-{exc.code.removeprefix('context-checkpoint-')}", "message": exc.message})
    expected_digest = canonical_digest({key: value for key, value in event.items() if key != "eventDigest"})
    if event.get("eventDigest") != expected_digest:
        blockers.append({"code": "context-event-digest-mismatch"})
    if expected_lineage:
        mismatch = {
            key: {"expected": value, "actual": event.get(key)}
            for key, value in expected_lineage.items()
            if event.get(key) != value
        }
        if mismatch:
            blockers.append({"code": "context-event-lineage-mismatch", "fields": mismatch})
    return _event_validation(event.get("eventId") if isinstance(event.get("eventId"), str) else None, blockers)


def require_context_checkpoint_event_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") == "FAIL":
        raise LifecycleError("context-event-validation-failed", "context checkpoint event validation failed", {"validation": validation})
    return validation


def _event_validation(event_id: str | None, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-context-checkpoint-event-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "eventId": event_id,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}
