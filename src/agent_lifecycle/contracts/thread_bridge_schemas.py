"""Portable contracts for the optional host-thread bridge."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.contracts.schema_builders import open_object_schema

THREAD_CAPABILITY_SCHEMA = "agent-thread-capability.v1"
THREAD_OPERATION_REQUEST_SCHEMA = "agent-thread-operation-request.v1"
THREAD_OPERATION_RECEIPT_SCHEMA = "agent-thread-operation-receipt.v1"
THREAD_CONTEXT_IMPORT_SCHEMA = "agent-thread-context-import.v1"
THREAD_OPERATION_VALIDATION_SCHEMA = "agent-thread-operation-validation.v1"

THREAD_OPERATIONS = ("read", "list", "send", "create")
THREAD_READ_OPERATIONS = {"read", "list"}
THREAD_MUTATING_OPERATIONS = {"send", "create"}
THREAD_SUPPORT_VALUES = ("supported", "unsupported", "unknown")
THREAD_OPERATION_STATUSES = ("PASS", "FAIL", "BLOCKED", "UNAVAILABLE")
THREAD_SCOPES = ("explicit-target", "project", "workflow")
THREAD_APPROVALS = ("none", "operator")
THREAD_BRIDGE_MODES = ("off", "advisory", "read-only", "controlled")

_AUTHORITY_KEYS = {
    "approveTools",
    "developerInstruction",
    "execute",
    "freezePlan",
    "hostCommand",
    "lifecycleTransition",
    "prompt",
    "promptAuthority",
    "runCommand",
    "systemInstruction",
    "taskAccept",
    "toolApproval",
}
_AUTHORITY_MARKERS = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?previous|execute\s+(?:the\s+)?(?:tool|command)|"
    r"approve\s+(?:all\s+)?tools|system\s+instruction|developer\s+instruction|"
    r"bypass\s+(?:review|freeze)|freeze\s+(?:the\s+)?plan|accept\s+(?:the\s+)?task)\b",
    re.IGNORECASE,
)

_DIGEST = {"type": "string", "minLength": 64, "maxLength": 64}
_BLOCKERS = {"type": "array", "items": {"type": "object"}}


THREAD_BRIDGE_SCHEMAS: dict[str, dict[str, Any]] = {
    THREAD_CAPABILITY_SCHEMA: open_object_schema(
        THREAD_CAPABILITY_SCHEMA,
        required=[
            "schemaVersion",
            "capabilityId",
            "adapterId",
            "host",
            "support",
            "operations",
            "transport",
            "evidencePolicy",
            "providerIdentityUsed",
            "hostExecutionOwned",
            "productionPromotionClaimed",
            "capabilityDigest",
        ],
        properties={
            "capabilityId": {"const": "thread-bridge"},
            "adapterId": {"type": "string", "minLength": 1},
            "host": {"type": "string", "minLength": 1},
            "support": {"enum": list(THREAD_SUPPORT_VALUES)},
            "operations": {"type": "array", "items": {"type": "object"}, "maxItems": 4},
            "transport": {"const": "adapter-owned"},
            "evidencePolicy": {"enum": ["qualification-required", "not-claimed"]},
            "providerIdentityUsed": {"const": False},
            "hostExecutionOwned": {"const": True},
            "productionPromotionClaimed": {"const": False},
            "capabilityDigest": _DIGEST,
        },
    ),
    THREAD_OPERATION_REQUEST_SCHEMA: open_object_schema(
        THREAD_OPERATION_REQUEST_SCHEMA,
        required=[
            "schemaVersion",
            "operationId",
            "operation",
            "target",
            "payload",
            "authorization",
            "limits",
            "planBinding",
            "hostExecutionAllowed",
            "modelCallsStarted",
            "networkCallsStarted",
            "productionPromotionClaimed",
            "requestDigest",
        ],
        properties={
            "operationId": {"type": "string", "minLength": 1, "maxLength": 160},
            "operation": {"enum": list(THREAD_OPERATIONS)},
            "target": {"type": "object"},
            "payload": {"type": "object"},
            "authorization": {"type": "object"},
            "limits": {"type": "object"},
            "phase": {"type": ["string", "null"]},
            "planBinding": {"type": ["object", "null"]},
            "hostExecutionAllowed": {"const": False},
            "modelCallsStarted": {"const": False},
            "networkCallsStarted": {"const": False},
            "productionPromotionClaimed": {"const": False},
            "requestDigest": _DIGEST,
        },
    ),
    THREAD_OPERATION_RECEIPT_SCHEMA: open_object_schema(
        THREAD_OPERATION_RECEIPT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "operation",
            "target",
            "requestDigest",
            "capabilityDigest",
            "result",
            "redactionStatus",
            "sourceOfTruth",
            "proof",
            "rawContentStored",
            "nativeTargetIdStored",
            "hostExecutionStarted",
            "modelCallsStarted",
            "blockers",
            "productionPromotionClaimed",
            "receiptDigest",
        ],
        properties={
            "status": {"enum": list(THREAD_OPERATION_STATUSES)},
            "operationId": {"type": "string", "minLength": 1},
            "operation": {"enum": list(THREAD_OPERATIONS)},
            "target": {"type": "object"},
            "requestDigest": _DIGEST,
            "capabilityDigest": {"type": ["string", "null"], "minLength": 0, "maxLength": 64},
            "adapterId": {"type": ["string", "null"]},
            "host": {"type": ["string", "null"]},
            "result": {"type": "object"},
            "redactionStatus": {"type": "object"},
            "sourceOfTruth": {"const": False},
            "proof": {"const": False},
            "rawContentStored": {"const": False},
            "nativeTargetIdStored": {"const": False},
            "hostExecutionStarted": {"type": "boolean"},
            "modelCallsStarted": {"const": False},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "receiptDigest": _DIGEST,
        },
    ),
    THREAD_CONTEXT_IMPORT_SCHEMA: open_object_schema(
        THREAD_CONTEXT_IMPORT_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "sourceReceiptDigest",
            "source",
            "content",
            "resourceCaps",
            "redactionStatus",
            "sourceOfTruth",
            "proof",
            "rawContentStored",
            "authority",
            "productionPromotionClaimed",
            "importDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "operationId": {"type": "string", "minLength": 1},
            "sourceReceiptDigest": _DIGEST,
            "source": {"type": "object"},
            "content": {"type": "object"},
            "resourceCaps": {"type": "object"},
            "redactionStatus": {"type": "object"},
            "sourceOfTruth": {"const": False},
            "proof": {"const": False},
            "rawContentStored": {"const": False},
            "authority": {"type": "object"},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "importDigest": _DIGEST,
        },
    ),
    THREAD_OPERATION_VALIDATION_SCHEMA: open_object_schema(
        THREAD_OPERATION_VALIDATION_SCHEMA,
        required=[
            "schemaVersion",
            "status",
            "operationId",
            "checks",
            "blockers",
            "productionPromotionClaimed",
            "validationDigest",
        ],
        properties={
            "status": {"enum": ["PASS", "FAIL"]},
            "operationId": {"type": ["string", "null"]},
            "checks": {"type": "array", "items": {"type": "object"}},
            "blockers": _BLOCKERS,
            "productionPromotionClaimed": {"const": False},
            "validationDigest": _DIGEST,
        },
    ),
}


def build_thread_capability(
    *,
    adapter_id: str,
    host: str,
    support: str = "unknown",
    operations: list[str] | list[dict[str, Any]] | None = None,
    qualification_receipt_digest: str | None = None,
) -> dict[str, Any]:
    """Build a descriptive capability declaration without calling a host."""

    _required_text(adapter_id, "adapterId")
    _required_text(host, "host")
    if support not in THREAD_SUPPORT_VALUES:
        raise LifecycleError("thread-capability-support-invalid", "unsupported thread capability status")
    selected = operations or list(THREAD_OPERATIONS)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected:
        if isinstance(item, str):
            name, item_support = item, support
        elif isinstance(item, dict):
            name, item_support = item.get("name"), item.get("support", support)
        else:
            raise LifecycleError("thread-capability-operation-invalid", "thread capability operation must be a string or object")
        if name not in THREAD_OPERATIONS or name in seen:
            raise LifecycleError("thread-capability-operation-invalid", "thread capability operation is unsupported", {"operation": name})
        if item_support not in THREAD_SUPPORT_VALUES:
            raise LifecycleError("thread-capability-support-invalid", "thread operation support is unsupported", {"operation": name})
        seen.add(name)
        entries.append(
            {
                "name": name,
                "support": item_support,
                "readOnly": name in THREAD_READ_OPERATIONS,
                "approval": "none" if name in THREAD_READ_OPERATIONS else "operator",
                "execution": "adapter-owned",
            }
        )
    body = {
        "schemaVersion": THREAD_CAPABILITY_SCHEMA,
        "capabilityId": "thread-bridge",
        "adapterId": adapter_id,
        "host": host,
        "support": support,
        "operations": entries,
        "transport": "adapter-owned",
        "evidencePolicy": "qualification-required" if support == "supported" else "not-claimed",
        "providerIdentityUsed": False,
        "hostExecutionOwned": True,
        "qualificationReceiptDigest": qualification_receipt_digest,
        "productionPromotionClaimed": False,
    }
    return {**body, "capabilityDigest": canonical_digest(body)}


def build_thread_operation_request(
    *,
    operation: str,
    operation_id: str,
    target: dict[str, Any],
    payload: dict[str, Any] | None = None,
    approval: str | None = None,
    idempotency_key: str | None = None,
    limits: dict[str, int] | None = None,
    phase: str | None = None,
    plan_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded request that an adapter may execute later."""

    _validate_operation(operation)
    _required_text(operation_id, "operationId")
    normalized_target = _normalize_target(target)
    expected_approval = "none" if operation in THREAD_READ_OPERATIONS else "operator"
    if approval is None:
        approval = expected_approval
    if approval != expected_approval:
        raise LifecycleError("thread-operation-approval-invalid", "operation approval does not match the operation")
    if operation in THREAD_MUTATING_OPERATIONS and not _required_text(idempotency_key, "idempotencyKey"):
        raise LifecycleError("thread-operation-idempotency-required", "send and create require an idempotency key")
    if operation in THREAD_READ_OPERATIONS and idempotency_key is not None:
        raise LifecycleError("thread-operation-idempotency-unexpected", "read and list must not carry an idempotency key")
    normalized_limits = _normalize_limits(limits)
    normalized_payload, _ = redact_value(payload or {})
    body = {
        "schemaVersion": THREAD_OPERATION_REQUEST_SCHEMA,
        "operationId": operation_id,
        "operation": operation,
        "target": normalized_target,
        "payload": normalized_payload,
        "authorization": {
            "approval": approval,
            "approvalRequired": expected_approval == "operator",
            "operatorApproved": approval == "operator",
            "idempotencyKey": idempotency_key,
        },
        "limits": normalized_limits,
        "phase": phase,
        "planBinding": deepcopy(plan_binding) if isinstance(plan_binding, dict) else None,
        "hostExecutionAllowed": False,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "requestDigest": canonical_digest(body)}


def build_thread_operation_receipt(
    *,
    request: dict[str, Any],
    status: str,
    result: dict[str, Any] | None = None,
    capability_digest: str | None = None,
    adapter_id: str | None = None,
    host: str | None = None,
    host_execution_started: bool = False,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a redacted host response receipt without granting authority."""

    require_thread_operation_request_pass(validate_thread_operation_request(request))
    if status not in THREAD_OPERATION_STATUSES:
        raise LifecycleError("thread-receipt-status-invalid", "unsupported thread operation receipt status")
    safe_result, changed = redact_value(result or {})
    body = {
        "schemaVersion": THREAD_OPERATION_RECEIPT_SCHEMA,
        "status": status,
        "operationId": request["operationId"],
        "operation": request["operation"],
        "target": dict(request["target"]),
        "requestDigest": request["requestDigest"],
        "capabilityDigest": capability_digest,
        "adapterId": adapter_id,
        "host": host,
        "result": safe_result,
        "redactionStatus": {
            "status": "REDACTED" if changed else "PASS",
            "secretValuesStored": False,
            "privatePathsStored": False,
            "rawContentStored": False,
        },
        "sourceOfTruth": False,
        "proof": False,
        "rawContentStored": False,
        "nativeTargetIdStored": False,
        "hostExecutionStarted": bool(host_execution_started),
        "modelCallsStarted": False,
        "blockers": list(blockers or []),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def build_thread_context_import(
    *,
    operation_id: str,
    source_receipt_digest: str,
    content: dict[str, Any] | str,
    source: dict[str, Any] | None = None,
    max_imported_bytes: int = 32768,
    max_imported_tokens: int = 2048,
) -> dict[str, Any]:
    """Create bounded, redacted, non-authoritative imported thread context."""

    _required_text(operation_id, "operationId")
    _require_digest(source_receipt_digest, "sourceReceiptDigest")
    if max_imported_bytes < 1 or max_imported_tokens < 1:
        raise LifecycleError("thread-context-limit-invalid", "context limits must be positive")
    if _contains_authority(content):
        raise LifecycleError("thread-context-authority", "thread content cannot grant prompt, tool or lifecycle authority")
    safe_content, changed = redact_value(content if isinstance(content, dict) else {"text": content})
    serialized = json.dumps(safe_content, ensure_ascii=False, sort_keys=True)
    estimated_tokens = max(1, (len(serialized.encode("utf-8")) + 3) // 4)
    blockers: list[dict[str, Any]] = []
    if len(serialized.encode("utf-8")) > max_imported_bytes:
        blockers.append({"code": "thread-context-bytes-exceeded", "maxImportedBytes": max_imported_bytes})
    if estimated_tokens > max_imported_tokens:
        blockers.append({"code": "thread-context-tokens-exceeded", "maxImportedTokens": max_imported_tokens})
    source_payload = dict(source or {"kind": "host-thread", "sourceId": "redacted"})
    source_status = source_payload.get("status")
    if source_status in THREAD_OPERATION_STATUSES and source_status != "PASS":
        blockers.append({"code": "thread-source-status", "status": source_status})
    body = {
        "schemaVersion": THREAD_CONTEXT_IMPORT_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "operationId": operation_id,
        "sourceReceiptDigest": source_receipt_digest,
        "source": source_payload,
        "content": safe_content,
        "resourceCaps": {
            "maxImportedBytes": max_imported_bytes,
            "maxImportedTokens": max_imported_tokens,
            "actualBytes": len(serialized.encode("utf-8")),
            "estimatedTokens": estimated_tokens,
        },
        "redactionStatus": {
            "status": "REDACTED" if changed else "PASS",
            "secretValuesStored": False,
            "privatePathsStored": False,
            "rawContentStored": False,
        },
        "sourceOfTruth": False,
        "proof": False,
        "rawContentStored": False,
        "authority": {
            "promptAuthority": False,
            "toolApproval": False,
            "planFreeze": False,
            "taskAcceptance": False,
            "lifecycleTransition": False,
        },
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "importDigest": canonical_digest(body)}


def build_thread_operation_validation(
    request: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Validate request/receipt lineage without contacting an adapter."""

    blockers: list[dict[str, Any]] = []
    request_validation = validate_thread_operation_request(request)
    receipt_validation = validate_thread_operation_receipt(receipt)
    if request_validation["status"] != "PASS":
        blockers.append({"code": "thread-request-invalid", "validation": request_validation})
    if receipt_validation["status"] != "PASS":
        blockers.append({"code": "thread-receipt-invalid", "validation": receipt_validation})
    if request.get("operationId") != receipt.get("operationId"):
        blockers.append({"code": "thread-operation-id-mismatch"})
    if request.get("requestDigest") != receipt.get("requestDigest"):
        blockers.append({"code": "thread-request-digest-mismatch"})
    if request.get("operation") != receipt.get("operation"):
        blockers.append({"code": "thread-operation-mismatch"})
    body = {
        "schemaVersion": THREAD_OPERATION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "operationId": request.get("operationId") if isinstance(request, dict) else None,
        "checks": [
            {"name": "request", "status": request_validation["status"]},
            {"name": "receipt", "status": receipt_validation["status"]},
            {"name": "lineage", "status": "PASS" if not blockers else "FAIL"},
        ],
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def validate_thread_capability(capability: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if capability.get("schemaVersion") != THREAD_CAPABILITY_SCHEMA:
        blockers.append({"code": "thread-capability-schema-invalid"})
    for key in ("adapterId", "host", "capabilityId", "transport", "support", "operations"):
        if key not in capability:
            blockers.append({"code": "thread-capability-field-missing", "field": key})
    if capability.get("capabilityId") != "thread-bridge":
        blockers.append({"code": "thread-capability-id-invalid"})
    if capability.get("support") not in THREAD_SUPPORT_VALUES:
        blockers.append({"code": "thread-capability-support-invalid"})
    if capability.get("transport") != "adapter-owned":
        blockers.append({"code": "thread-capability-transport-invalid"})
    if capability.get("providerIdentityUsed") is not False:
        blockers.append({"code": "thread-capability-provider-identity"})
    if capability.get("hostExecutionOwned") is not True:
        blockers.append({"code": "thread-capability-execution-boundary"})
    _validate_capability_operations(capability.get("operations"), blockers)
    if capability.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "thread-capability-production-claim"})
    _check_digest(capability, "capabilityDigest", blockers)
    return _validation(THREAD_CAPABILITY_SCHEMA, blockers, capability.get("capabilityDigest"), "capability")


def validate_thread_operation_request(request: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if request.get("schemaVersion") != THREAD_OPERATION_REQUEST_SCHEMA:
        blockers.append({"code": "thread-request-schema-invalid"})
    operation = request.get("operation")
    if operation not in THREAD_OPERATIONS:
        blockers.append({"code": "thread-request-operation-invalid"})
    if not isinstance(request.get("operationId"), str) or not request["operationId"]:
        blockers.append({"code": "thread-request-operation-id-missing"})
    _validate_target(request.get("target"), blockers)
    authorization = request.get("authorization")
    if not isinstance(authorization, dict):
        blockers.append({"code": "thread-request-authorization-invalid"})
    else:
        expected = "none" if operation in THREAD_READ_OPERATIONS else "operator"
        if authorization.get("approval") != expected:
            blockers.append({"code": "thread-request-approval-invalid"})
        if authorization.get("approvalRequired") is not (expected == "operator"):
            blockers.append({"code": "thread-request-approval-required-invalid"})
        if operation in THREAD_MUTATING_OPERATIONS and not isinstance(authorization.get("idempotencyKey"), str):
            blockers.append({"code": "thread-request-idempotency-missing"})
        if operation in THREAD_READ_OPERATIONS and authorization.get("idempotencyKey") is not None:
            blockers.append({"code": "thread-request-idempotency-unexpected"})
    _validate_limits(request.get("limits"), blockers)
    if request.get("hostExecutionAllowed") is not False:
        blockers.append({"code": "thread-request-host-execution"})
    if request.get("modelCallsStarted") is not False or request.get("networkCallsStarted") is not False:
        blockers.append({"code": "thread-request-live-call-claim"})
    if request.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "thread-request-production-claim"})
    _check_digest(request, "requestDigest", blockers)
    return _validation(THREAD_OPERATION_REQUEST_SCHEMA, blockers, request.get("requestDigest"), "request")


def validate_thread_operation_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if receipt.get("schemaVersion") != THREAD_OPERATION_RECEIPT_SCHEMA:
        blockers.append({"code": "thread-receipt-schema-invalid"})
    if receipt.get("status") not in THREAD_OPERATION_STATUSES:
        blockers.append({"code": "thread-receipt-status-invalid"})
    if receipt.get("operation") not in THREAD_OPERATIONS:
        blockers.append({"code": "thread-receipt-operation-invalid"})
    _validate_target(receipt.get("target"), blockers)
    for key in ("sourceOfTruth", "proof", "rawContentStored", "nativeTargetIdStored", "modelCallsStarted", "productionPromotionClaimed"):
        if receipt.get(key) is not False:
            blockers.append({"code": "thread-receipt-authority-claim", "field": key})
    if not isinstance(receipt.get("redactionStatus"), dict):
        blockers.append({"code": "thread-receipt-redaction-invalid"})
    if not isinstance(receipt.get("result"), dict):
        blockers.append({"code": "thread-receipt-result-invalid"})
    _require_digest_field(receipt, "requestDigest", blockers)
    _check_digest(receipt, "receiptDigest", blockers)
    return _validation(THREAD_OPERATION_RECEIPT_SCHEMA, blockers, receipt.get("receiptDigest"), "receipt")


def validate_thread_context_import(imported: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if imported.get("schemaVersion") != THREAD_CONTEXT_IMPORT_SCHEMA:
        blockers.append({"code": "thread-context-schema-invalid"})
    if imported.get("status") not in {"PASS", "FAIL"}:
        blockers.append({"code": "thread-context-status-invalid"})
    for key in ("sourceOfTruth", "proof", "rawContentStored", "productionPromotionClaimed"):
        if imported.get(key) is not False:
            blockers.append({"code": "thread-context-authority-claim", "field": key})
    authority = imported.get("authority")
    if not isinstance(authority, dict) or any(authority.get(key) is not False for key in ("promptAuthority", "toolApproval", "planFreeze", "taskAcceptance", "lifecycleTransition")):
        blockers.append({"code": "thread-context-authority-invalid"})
    _validate_limits(imported.get("resourceCaps"), blockers, context=True)
    if not isinstance(imported.get("redactionStatus"), dict):
        blockers.append({"code": "thread-context-redaction-invalid"})
    if _contains_authority(imported.get("content")):
        blockers.append({"code": "thread-context-authority-marker"})
    _require_digest_field(imported, "sourceReceiptDigest", blockers)
    _check_digest(imported, "importDigest", blockers)
    return _validation(THREAD_CONTEXT_IMPORT_SCHEMA, blockers, imported.get("importDigest"), "context")


def require_thread_operation_request_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("thread-request-invalid", "thread operation request validation failed", {"validation": validation})
    return validation


def require_thread_operation_receipt_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("thread-receipt-invalid", "thread operation receipt validation failed", {"validation": validation})
    return validation


def require_thread_context_import_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("thread-context-invalid", "thread context import validation failed", {"validation": validation})
    return validation


# Short aliases keep the CLI and adapter boundary readable.
build_thread_request = build_thread_operation_request
build_thread_receipt = build_thread_operation_receipt
validate_thread_request = validate_thread_operation_request
validate_thread_receipt = validate_thread_operation_receipt


def _normalize_target(target: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(target, dict):
        raise LifecycleError("thread-target-invalid", "thread target must be an object")
    result = dict(target)
    scope = result.get("scope")
    if scope not in THREAD_SCOPES:
        raise LifecycleError("thread-target-scope-invalid", "thread target scope is unsupported")
    if scope == "explicit-target" and not isinstance(result.get("targetHash"), str):
        raise LifecycleError("thread-target-hash-required", "explicit-target operations require targetHash")
    if any(not isinstance(key, str) for key in result):
        raise LifecycleError("thread-target-key-invalid", "thread target keys must be strings")
    safe, _ = redact_value(result)
    return safe


def _validate_target(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "thread-target-invalid"})
        return
    scope = value.get("scope")
    if scope not in THREAD_SCOPES:
        blockers.append({"code": "thread-target-scope-invalid"})
    if scope == "explicit-target" and not isinstance(value.get("targetHash"), str):
        blockers.append({"code": "thread-target-hash-required"})


def _normalize_limits(limits: dict[str, int] | None) -> dict[str, int]:
    value = dict(limits or {})
    defaults = {"maxImportedBytes": 32768, "maxImportedTokens": 2048, "maxResults": 32}
    result = {**defaults, **value}
    blockers: list[dict[str, Any]] = []
    _validate_limits(result, blockers)
    if blockers:
        raise LifecycleError(
            "thread-limits-invalid",
            "thread operation limits are outside the supported bounds",
            {"blockers": blockers},
        )
    return result


def _validate_limits(value: Any, blockers: list[dict[str, Any]], *, context: bool = False) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "thread-limits-invalid"})
        return
    allowed = {"maxImportedBytes", "maxImportedTokens", "maxResults", "actualBytes", "estimatedTokens"}
    for key, item in value.items():
        if key not in allowed:
            blockers.append({"code": "thread-limit-field-invalid", "field": key})
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            blockers.append({"code": "thread-limit-value-invalid", "field": key})
    if value.get("maxImportedBytes", 1) > 32768:
        blockers.append({"code": "thread-limit-bytes-too-large"})
    if value.get("maxImportedTokens", 1) > 4096:
        blockers.append({"code": "thread-limit-tokens-too-large"})
    if context and value.get("actualBytes", 0) > value.get("maxImportedBytes", 0):
        blockers.append({"code": "thread-context-actual-bytes-exceeded"})
    if context and value.get("estimatedTokens", 0) > value.get("maxImportedTokens", 0):
        blockers.append({"code": "thread-context-actual-tokens-exceeded"})


def _validate_capability_operations(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value:
        blockers.append({"code": "thread-capability-operations-invalid"})
        return
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or item.get("name") not in THREAD_OPERATIONS:
            blockers.append({"code": "thread-capability-operation-invalid"})
            continue
        name = item["name"]
        if name in seen:
            blockers.append({"code": "thread-capability-operation-duplicate", "operation": name})
        seen.add(name)
        if item.get("readOnly") is not (name in THREAD_READ_OPERATIONS):
            blockers.append({"code": "thread-capability-read-only-mismatch", "operation": name})
        expected_approval = "none" if name in THREAD_READ_OPERATIONS else "operator"
        if item.get("approval") != expected_approval:
            blockers.append({"code": "thread-capability-approval-mismatch", "operation": name})


def _contains_authority(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _AUTHORITY_KEYS or (isinstance(key, str) and key.replace("_", "").lower() in {item.lower().replace("_", "") for item in _AUTHORITY_KEYS}):
                return True
            if _contains_authority(item):
                return True
    if isinstance(value, list):
        return any(_contains_authority(item) for item in value)
    if isinstance(value, str):
        return bool(_AUTHORITY_MARKERS.search(value))
    return False


def _validate_operation(operation: str) -> None:
    if operation not in THREAD_OPERATIONS:
        raise LifecycleError("thread-operation-invalid", "thread operation is unsupported", {"operation": operation})


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError("thread-field-invalid", f"{label} must be a non-empty string")
    return value


def _require_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleError("thread-digest-invalid", f"{label} must be a SHA-256 digest")
    return value


def _check_digest(payload: dict[str, Any], field: str, blockers: list[dict[str, Any]]) -> None:
    value = payload.get(field)
    if not isinstance(value, str) or len(value) != 64:
        blockers.append({"code": "thread-digest-invalid", "field": field})
        return
    expected = canonical_digest({key: value for key, value in payload.items() if key != field})
    if value != expected:
        blockers.append({"code": "thread-digest-mismatch", "field": field})


def _require_digest_field(payload: dict[str, Any], field: str, blockers: list[dict[str, Any]]) -> None:
    value = payload.get(field)
    if not isinstance(value, str) or len(value) != 64:
        blockers.append({"code": "thread-digest-invalid", "field": field})


def _validation(schema: str, blockers: list[dict[str, Any]], digest: Any, label: str) -> dict[str, Any]:
    body = {
        "schemaVersion": THREAD_OPERATION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "checkedSchema": schema,
        "label": label,
        "blockers": blockers,
        "productionPromotionClaimed": False,
        "checkedDigest": digest,
    }
    return {**body, "validationDigest": canonical_digest(body)}
