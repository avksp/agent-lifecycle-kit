"""Event capture receipts for neutral adapter event streams."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    validate_lifecycle_control_attestation,
    validate_lifecycle_control_decision,
    validate_lifecycle_control_event_batch,
    validate_lifecycle_control_policy,
    validate_lifecycle_control_request,
)
from agent_lifecycle.contracts.redaction import REDACTED_VALUE, is_sensitive_key
from agent_lifecycle.host_protocol.events import validate_adapter_event_stream

EVENT_CAPTURE_OPERATION = "adapter-event-stream"
EVENT_CAPTURE_STATUS = "DECLARED"
EVENT_STREAM_RECEIPT_SCHEMA = "agent-adapter-event-stream-receipt.v1"
EVENT_CAPTURE_VALIDATION_SCHEMA = "agent-adapter-event-capture-validation.v1"
LIFECYCLE_CONTROL_VALIDATION_SCHEMA = "agent-adapter-lifecycle-control-validation.v1"
EVENT_CATEGORIES = (
    "command",
    "file-change",
    "lifecycle-transition",
    "model-usage",
    "user-decision",
    "validation",
)


def adapter_declares_event_capture(
    *,
    descriptor: dict[str, Any] | None = None,
    projection: dict[str, Any] | None = None,
    capability_manifest: dict[str, Any] | None = None,
) -> bool:
    """Return whether adapter metadata declares neutral event capture."""

    return any(
        (
            _descriptor_declares(descriptor),
            _projection_declares(projection),
            _capability_manifest_declares(capability_manifest),
        )
    )


def event_capture_declaration() -> dict[str, Any]:
    return {
        "status": EVENT_CAPTURE_STATUS,
        "portableEventSchema": "agent-adapter-event.v1",
        "categories": list(EVENT_CATEGORIES),
        "producerBoundary": "adapter-owned",
        "promotionRequired": False,
    }


def build_adapter_event_stream(
    *,
    host: str,
    adapter_id: str,
    run_id: str,
    task_id: str,
    operation_id: str,
    command: str,
    exit_code: int,
    changed_files: list[str] | None = None,
    usage: dict[str, Any] | None = None,
    result_path: str | None = None,
    blocker: str | None = None,
    recorded_at: str = "2026-01-01T00:00:00Z",
) -> list[dict[str, Any]]:
    """Build a compact neutral stream from one bounded host operation."""

    _required_string(host, "host")
    _required_string(adapter_id, "adapterId")
    _required_string(run_id, "runId")
    _required_string(task_id, "taskId")
    _required_string(operation_id, "operationId")
    _required_string(command, "command")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        raise LifecycleError("invalid-adapter-event-producer-input", "exitCode must be an integer")
    files = list(changed_files or [])
    stream = [
        _event(
            1,
            "session.started",
            "INFO",
            host,
            adapter_id,
            run_id,
            task_id,
            operation_id,
            recorded_at,
            {"category": "lifecycle-transition"},
        ),
        _event(
            2,
            "task.launched",
            "PASS",
            host,
            adapter_id,
            run_id,
            task_id,
            operation_id,
            recorded_at,
            {"category": "lifecycle-transition"},
        ),
        _event(
            3,
            "command.completed",
            "PASS" if exit_code == 0 else "FAIL",
            host,
            adapter_id,
            run_id,
            task_id,
            operation_id,
            recorded_at,
            {"category": "command", "command": command, "exitCode": exit_code},
        ),
        _event(
            4,
            "writes.summarized",
            "PASS",
            host,
            adapter_id,
            run_id,
            task_id,
            operation_id,
            recorded_at,
            {"category": "file-change", "changedFiles": files},
        ),
    ]
    sequence = 5
    if usage is not None:
        if not isinstance(usage, dict):
            raise LifecycleError("invalid-adapter-event-producer-input", "usage must be an object")
        stream.append(
            _event(
                sequence,
                "usage.reported",
                "PASS",
                host,
                adapter_id,
                run_id,
                task_id,
                operation_id,
                recorded_at,
                {"category": "model-usage", **usage},
            )
        )
        sequence += 1
    if exit_code == 0 and blocker is None:
        _required_string(result_path, "resultPath")
        stream.append(
            _event(
                sequence,
                "task.completed",
                "PASS",
                host,
                adapter_id,
                run_id,
                task_id,
                operation_id,
                recorded_at,
                {"category": "lifecycle-transition", "resultPath": result_path},
            )
        )
    else:
        stream.append(
            _event(
                sequence,
                "task.blocked",
                "BLOCKED",
                host,
                adapter_id,
                run_id,
                task_id,
                operation_id,
                recorded_at,
                {"category": "lifecycle-transition", "blocker": blocker or f"command exited {exit_code}"},
            )
        )
    return stream


def build_event_stream_receipt(
    events: list[dict[str, Any]],
    *,
    descriptor: dict[str, Any],
    producer_id: str,
    emitted_at: str | None = None,
) -> dict[str, Any]:
    validation = validate_adapter_event_stream(events)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "adapter-event-validation-failed", "adapter event stream validation failed", {"validation": validation}
        )
    _required_string(producer_id, "producer.id")
    host = _required_string(descriptor.get("host"), "descriptor.host")
    adapter_id = _required_string(descriptor.get("adapterId"), "descriptor.adapterId")
    if validation["host"] != host or validation["adapterId"] != adapter_id:
        raise LifecycleError("adapter-event-receipt-lineage-mismatch", "event stream does not match adapter descriptor")
    body = {
        "schemaVersion": EVENT_STREAM_RECEIPT_SCHEMA,
        "status": "PASS",
        "adapterId": adapter_id,
        "host": host,
        "runId": validation["runId"],
        "taskId": validation["taskId"],
        "operationId": events[0]["operationId"],
        "producer": {
            "id": producer_id,
            "boundary": "adapter-owned",
            "portableEventSchema": "agent-adapter-event.v1",
        },
        "descriptorDigest": canonical_digest(descriptor),
        "eventStreamDigest": canonical_digest(events),
        "eventCount": validation["eventCount"],
        "eventTypes": validation["eventTypes"],
        "terminalEvent": validation["terminalEvent"],
        "emittedAt": emitted_at or _now_iso(),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_event_capture_receipt(
    receipt: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    descriptor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    _validate_receipt_shape(receipt, blockers)
    stream_validation = validate_adapter_event_stream(events)
    if stream_validation["status"] == "FAIL":
        blockers.extend(_tag_blockers(stream_validation["blockers"], "event-stream"))
    if receipt.get("eventStreamDigest") != canonical_digest(events):
        blockers.append({"code": "adapter-event-stream-stale", "message": "event stream digest does not match receipt"})
    stored_digest = receipt.get("receiptDigest")
    if stored_digest is not None and stored_digest != canonical_digest(
        {key: value for key, value in receipt.items() if key != "receiptDigest"}
    ):
        blockers.append(
            {"code": "adapter-event-receipt-digest-mismatch", "message": "receiptDigest does not match receipt"}
        )
    if receipt.get("eventCount") != len(events):
        blockers.append({"code": "adapter-event-count-mismatch", "message": "event count does not match receipt"})
    if events:
        first = events[0]
        for key in ("adapterId", "host", "runId", "taskId", "operationId"):
            if receipt.get(key) != first.get(key):
                blockers.append({"code": "adapter-event-receipt-lineage-mismatch", "field": key})
    if descriptor is not None:
        if receipt.get("descriptorDigest") != canonical_digest(descriptor):
            blockers.append(
                {"code": "adapter-event-descriptor-stale", "message": "descriptor digest does not match receipt"}
            )
        for key in ("adapterId", "host"):
            if receipt.get(key) != descriptor.get(key):
                blockers.append({"code": "adapter-event-receipt-descriptor-mismatch", "field": key})
    status = "PASS" if not blockers else "FAIL"
    body = {
        "schemaVersion": EVENT_CAPTURE_VALIDATION_SCHEMA,
        "status": status,
        "adapterId": receipt.get("adapterId"),
        "host": receipt.get("host"),
        "runId": receipt.get("runId"),
        "taskId": receipt.get("taskId"),
        "operationId": receipt.get("operationId"),
        "declaredEventCapture": True,
        "eventCount": len(events),
        "streamValidation": stream_validation,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def validate_event_capture_conformance(
    *,
    descriptor: dict[str, Any],
    events: list[dict[str, Any]] | None = None,
    receipt: dict[str, Any] | None = None,
    projection: dict[str, Any] | None = None,
    capability_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    declared = adapter_declares_event_capture(
        descriptor=descriptor,
        projection=projection,
        capability_manifest=capability_manifest,
    )
    blockers: list[dict[str, Any]] = []
    receipt_validation: dict[str, Any] | None = None
    if declared and events is None:
        blockers.append(
            {
                "code": "adapter-event-capture-stream-missing",
                "message": "declared event capture requires an event stream fixture",
            }
        )
    if declared and receipt is None:
        blockers.append(
            {
                "code": "adapter-event-capture-receipt-missing",
                "message": "declared event capture requires an event stream receipt",
            }
        )
    if declared and events is not None and receipt is not None:
        receipt_validation = validate_event_capture_receipt(receipt, events, descriptor=descriptor)
        if receipt_validation["status"] == "FAIL":
            blockers.extend(_tag_blockers(receipt_validation["blockers"], "event-capture-receipt"))
    body = {
        "schemaVersion": EVENT_CAPTURE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "adapterId": descriptor.get("adapterId"),
        "host": descriptor.get("host"),
        "declaredEventCapture": declared,
        "eventCount": len(events or []),
        "receiptValidation": receipt_validation,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_event_capture_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError(
            "adapter-event-capture-validation-failed",
            "adapter event capture validation failed",
            {"validation": payload},
        )
    return payload


def validate_lifecycle_control_bundle(
    *,
    policy: dict[str, Any],
    request: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    attestation: dict[str, Any] | None = None,
    reference_time: datetime | None = None,
) -> dict[str, Any]:
    """Validate bounded lifecycle envelopes and their shared request lineage."""

    blockers: list[dict[str, Any]] = []
    policy_validation = validate_lifecycle_control_policy(policy)
    if policy_validation["status"] != "PASS":
        blockers.extend(_tag_blockers(policy_validation["blockers"], "policy"))
    policy_limits = policy.get("limits") if policy_validation["status"] == "PASS" else None
    request_validation = None
    decision_validation = None
    event_validation = None
    attestation_validation = None
    provided = any(value is not None for value in (request, decision, events, attestation))
    if not provided:
        blockers.append({"code": "lifecycle-control-input-missing"})
    for surface, value in (
        ("request", request),
        ("decision", decision),
        ("events", events),
        ("attestation", attestation),
    ):
        _validate_camel_case_sensitive_keys(value, surface, blockers)
    if request is not None:
        request_validation = validate_lifecycle_control_request(
            request, policy_limits=policy_limits, reference_time=reference_time
        )
        if request_validation["status"] != "PASS":
            blockers.extend(_tag_blockers(request_validation["blockers"], "request"))
    if decision is not None:
        decision_validation = validate_lifecycle_control_decision(decision, policy_limits=policy_limits)
        if decision_validation["status"] != "PASS":
            blockers.extend(_tag_blockers(decision_validation["blockers"], "decision"))
    if events is not None:
        event_validation = validate_lifecycle_control_event_batch(
            events, policy_limits=policy_limits, reference_time=reference_time
        )
        if event_validation["status"] != "PASS":
            blockers.extend(_tag_blockers(event_validation["blockers"], "events"))
    if attestation is not None:
        attestation_validation = validate_lifecycle_control_attestation(
            attestation, policy_limits=policy_limits, reference_time=reference_time
        )
        if attestation_validation["status"] != "PASS":
            blockers.extend(_tag_blockers(attestation_validation["blockers"], "attestation"))
    _validate_lifecycle_control_lineage(
        request=request,
        decision=decision,
        events=events or [],
        attestation=attestation,
        blockers=blockers,
    )
    body = {
        "schemaVersion": LIFECYCLE_CONTROL_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "policy": policy_validation,
        "request": request_validation,
        "decision": decision_validation,
        "events": event_validation,
        "attestation": attestation_validation,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_lifecycle_control_bundle_pass(payload: dict[str, Any]) -> dict[str, Any]:
    """Raise a stable error when lifecycle-control CLI evidence is invalid."""

    if payload.get("status") == "FAIL":
        raise LifecycleError(
            "lifecycle-control-validation-failed",
            "lifecycle control evidence validation failed",
            {"validation": payload},
        )
    return payload


def _event(
    sequence: int,
    event_type: str,
    status: str,
    host: str,
    adapter_id: str,
    run_id: str,
    task_id: str,
    operation_id: str,
    recorded_at: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-adapter-event.v1",
        "eventId": f"{operation_id}-{sequence:02d}",
        "host": host,
        "adapterId": adapter_id,
        "runId": run_id,
        "taskId": task_id,
        "operationId": operation_id,
        "sequence": sequence,
        "eventType": event_type,
        "status": status,
        "recordedAt": recorded_at,
        "payload": payload,
    }


def _descriptor_declares(descriptor: dict[str, Any] | None) -> bool:
    if not isinstance(descriptor, dict):
        return False
    capture = descriptor.get("eventCapture")
    if isinstance(capture, dict) and capture.get("status") == EVENT_CAPTURE_STATUS:
        return True
    operations = descriptor.get("operations")
    return isinstance(operations, list) and any(
        isinstance(item, dict) and item.get("name") == EVENT_CAPTURE_OPERATION for item in operations
    )


def _projection_declares(projection: dict[str, Any] | None) -> bool:
    if not isinstance(projection, dict):
        return False
    bridge = projection.get("eventBridge")
    return isinstance(bridge, dict) and bridge.get("portableEventSchema") == "agent-adapter-event.v1"


def _capability_manifest_declares(capability_manifest: dict[str, Any] | None) -> bool:
    if not isinstance(capability_manifest, dict):
        return False
    capture = capability_manifest.get("eventCapture")
    if isinstance(capture, dict) and capture.get("status") == EVENT_CAPTURE_STATUS:
        return True
    capabilities = capability_manifest.get("capabilities")
    return isinstance(capabilities, list) and any(
        isinstance(item, dict) and item.get("name") == EVENT_CAPTURE_OPERATION for item in capabilities
    )


def _validate_receipt_shape(receipt: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if not isinstance(receipt, dict):
        blockers.append({"code": "invalid-adapter-event-receipt", "message": "receipt must be an object"})
        return
    required = {
        "schemaVersion",
        "status",
        "adapterId",
        "host",
        "runId",
        "taskId",
        "operationId",
        "producer",
        "descriptorDigest",
        "eventStreamDigest",
        "eventCount",
        "eventTypes",
        "terminalEvent",
        "emittedAt",
        "productionPromotionClaimed",
    }
    missing = sorted(required.difference(receipt))
    if missing:
        blockers.append(
            {
                "code": "invalid-adapter-event-receipt",
                "message": "required receipt fields are missing",
                "fields": missing,
            }
        )
    if receipt.get("schemaVersion") != EVENT_STREAM_RECEIPT_SCHEMA:
        blockers.append(
            {
                "code": "invalid-adapter-event-receipt-schema",
                "message": "unsupported event stream receipt schemaVersion",
            }
        )
    if receipt.get("status") != "PASS":
        blockers.append({"code": "adapter-event-receipt-not-pass", "message": "event stream receipt must be PASS"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append(
            {
                "code": "adapter-event-receipt-production-claim",
                "message": "event stream receipt must not claim production promotion",
            }
        )
    if not isinstance(receipt.get("eventCount"), int) or isinstance(receipt.get("eventCount"), bool):
        blockers.append({"code": "invalid-adapter-event-receipt", "message": "eventCount must be an integer"})
    if not isinstance(receipt.get("eventTypes"), list):
        blockers.append({"code": "invalid-adapter-event-receipt", "message": "eventTypes must be an array"})


def _tag_blockers(blockers: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    return [{**item, "source": source} for item in blockers if isinstance(item, dict)]


def _validate_lifecycle_control_lineage(
    *,
    request: dict[str, Any] | None,
    decision: dict[str, Any] | None,
    events: list[dict[str, Any]],
    attestation: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> None:
    if request is None:
        if decision is not None or attestation is not None:
            blockers.append({"code": "lifecycle-control-request-required-for-proof", "surface": "bundle"})
        request_digests = {
            event.get("requestDigest")
            for event in events
            if isinstance(event, dict) and isinstance(event.get("requestDigest"), str)
        }
        if events and (
            len(request_digests) != 1
            or any(not isinstance(event, dict) or not event.get("requestDigest") for event in events)
        ):
            blockers.append({"code": "lifecycle-control-event-batch-lineage-mismatch", "surface": "events"})
        return
    request_digest = request.get("requestDigest")
    if isinstance(decision, dict):
        if decision.get("requestDigest") != request_digest:
            blockers.append({"code": "lifecycle-control-request-lineage-mismatch", "surface": "decision"})
        if decision.get("operation") != request.get("operation"):
            blockers.append({"code": "lifecycle-control-operation-lineage-mismatch", "surface": "decision"})
    if isinstance(attestation, dict):
        attestation_fields = (
            "producerId",
            "adapterId",
            "hostVersion",
            "operation",
            "nonce",
            "planDigest",
            "lockDigest",
            "stateRevision",
            "actionDigest",
        )
        for field in attestation_fields:
            if attestation.get(field) != request.get(field):
                blockers.append(
                    {
                        "code": "lifecycle-control-attestation-lineage-mismatch",
                        "surface": "attestation",
                        "field": field,
                    }
                )
    for index, event in enumerate(events):
        if isinstance(event, dict) and event.get("requestDigest") != request_digest:
            blockers.append({"code": "lifecycle-control-request-lineage-mismatch", "surface": "events", "index": index})


def _validate_camel_case_sensitive_keys(
    value: Any, surface: str, blockers: list[dict[str, Any]], path: str = ""
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}".strip(".")
            if isinstance(key, str):
                normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
                if normalized != key and is_sensitive_key(normalized) and item != REDACTED_VALUE:
                    blockers.append(
                        {
                            "code": "lifecycle-control-unredacted-sensitive-value",
                            "surface": surface,
                            "field": child_path,
                        }
                    )
            _validate_camel_case_sensitive_keys(item, surface, blockers, child_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_camel_case_sensitive_keys(item, surface, blockers, f"{path}[{index}]")


def _required_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-adapter-event-producer-input", f"{label} is required")
    return value


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
