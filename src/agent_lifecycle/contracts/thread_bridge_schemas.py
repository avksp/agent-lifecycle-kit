"""Portable contracts for the optional host-thread bridge."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.contracts.thread_bridge_schema_definitions import (
    THREAD_APPROVALS,
    THREAD_ADAPTER_STATUS_VALUES,
    THREAD_BRIDGE_MODES,
    THREAD_BRIDGE_PROFILE_SCHEMA,
    THREAD_BRIDGE_PROFILE_VALIDATION_SCHEMA,
    THREAD_BRIDGE_POLICY_VERSION,
    THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA,
    THREAD_CAPABILITY_SCHEMA,
    THREAD_CONTEXT_IMPORT_SCHEMA,
    THREAD_EFFECTIVE_STATUS_VALUES,
    THREAD_MUTATING_OPERATIONS,
    THREAD_OPERATION_RECEIPT_SCHEMA,
    THREAD_OPERATION_REQUEST_SCHEMA,
    THREAD_OPERATION_STATUSES,
    THREAD_OPERATION_VALIDATION_SCHEMA,
    THREAD_OPERATIONS,
    THREAD_QUALIFICATION_STATUS_VALUES,
    THREAD_READ_OPERATIONS,
    THREAD_SCOPES,
    THREAD_SUPPORT_VALUES,
    THREAD_BRIDGE_SCHEMAS,
    _AUTHORITY_KEYS,
    _AUTHORITY_MARKERS,
)
from agent_lifecycle.contracts.thread_bridge_validation import (
    _check_digest,
    _contains_authority,
    _normalize_adapter_operations,
    _normalize_limits,
    _normalize_operation_set,
    _normalize_target,
    _profile_validation,
    _qualification_matches,
    _required_text,
    _require_digest,
    _require_digest_field,
    _validate_adapter_profile_operations,
    _validate_capability_operations,
    _validate_limits,
    _validate_operation,
    _validate_operation_set,
    _validate_target,
    _validation,
)

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
            metadata: dict[str, Any] = {}
        elif isinstance(item, dict):
            name, item_support = item.get("name"), item.get("support", support)
            metadata = {
                key: item[key]
                for key in ("declaredStatus", "qualificationStatus", "effectiveStatus", "capabilitySupport")
                if key in item
            }
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
                **metadata,
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


def build_thread_bridge_profile(
    *,
    adapter_id: str,
    host: str,
    operations: list[dict[str, Any]],
    descriptor_digest: str | None = None,
    capability_manifest_digest: str | None = None,
    host_range: dict[str, Any] | None = None,
    policy_version: str = THREAD_BRIDGE_POLICY_VERSION,
) -> dict[str, Any]:
    """Build an adapter-owned thread profile without contacting a host."""

    _required_text(adapter_id, "adapterId")
    _required_text(host, "host")
    if policy_version != THREAD_BRIDGE_POLICY_VERSION:
        raise LifecycleError("thread-profile-policy-invalid", "unsupported thread bridge policy version")
    normalized_operations = _normalize_adapter_operations(operations)
    for digest, label in (
        (descriptor_digest, "descriptorDigest"),
        (capability_manifest_digest, "capabilityManifestDigest"),
    ):
        if digest is not None:
            _require_digest(digest, label)
    body = {
        "schemaVersion": THREAD_BRIDGE_PROFILE_SCHEMA,
        "profileId": "thread-bridge",
        "adapterId": adapter_id,
        "host": host,
        "descriptorDigest": descriptor_digest,
        "capabilityManifestDigest": capability_manifest_digest,
        "hostRange": deepcopy(host_range) if isinstance(host_range, dict) else {},
        "policyVersion": policy_version,
        "operations": normalized_operations,
        "transport": "adapter-owned",
        "evidencePolicy": "qualification-required"
        if any(item["declaredStatus"] != "UNSUPPORTED" for item in normalized_operations)
        else "not-claimed",
        "providerIdentityUsed": False,
        "hostExecutionOwned": True,
        "qualificationRequired": True,
        "productionPromotionClaimed": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


def build_thread_bridge_qualification_receipt(
    *,
    receipt_id: str,
    adapter_id: str,
    host: str,
    descriptor_digest: str,
    capability_manifest_digest: str,
    host_range: dict[str, Any],
    operation_set: list[str],
    route: str = "wrapper",
    evidence_refs: list[str] | None = None,
    expires_at: str | None = None,
    policy_version: str = THREAD_BRIDGE_POLICY_VERSION,
) -> dict[str, Any]:
    """Build a qualification receipt supplied by an adapter owner."""

    _required_text(receipt_id, "receiptId")
    _required_text(adapter_id, "adapterId")
    _required_text(host, "host")
    _require_digest(descriptor_digest, "descriptorDigest")
    _require_digest(capability_manifest_digest, "capabilityManifestDigest")
    if not isinstance(host_range, dict):
        raise LifecycleError("thread-qualification-host-range-invalid", "hostRange must be an object")
    if route not in {"native", "wrapper"}:
        raise LifecycleError("thread-qualification-route-invalid", "qualification route must be native or wrapper")
    if policy_version != THREAD_BRIDGE_POLICY_VERSION:
        raise LifecycleError("thread-qualification-policy-invalid", "unsupported thread bridge policy version")
    normalized_operations = _normalize_operation_set(operation_set)
    refs = [item for item in (evidence_refs or []) if isinstance(item, str) and item]
    if not refs:
        raise LifecycleError("thread-qualification-evidence-missing", "qualification requires evidence references")
    body = {
        "schemaVersion": THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA,
        "receiptId": receipt_id,
        "adapterId": adapter_id,
        "host": host,
        "descriptorDigest": descriptor_digest,
        "capabilityManifestDigest": capability_manifest_digest,
        "hostRange": deepcopy(host_range),
        "policyVersion": policy_version,
        "operationSet": normalized_operations,
        "route": route,
        "qualificationStatus": "QUALIFIED",
        "evidenceRefs": refs,
        "expiresAt": expires_at,
        "hostExecutionStarted": True,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "rawContentStored": False,
        "sourceOfTruth": False,
        "proof": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


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


def validate_thread_bridge_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate an adapter declaration without treating it as live evidence."""

    blockers: list[dict[str, Any]] = []
    if profile.get("schemaVersion") != THREAD_BRIDGE_PROFILE_SCHEMA:
        blockers.append({"code": "thread-profile-schema-invalid"})
    if profile.get("profileId") != "thread-bridge":
        blockers.append({"code": "thread-profile-id-invalid"})
    for key in ("adapterId", "host"):
        if not isinstance(profile.get(key), str) or not profile[key]:
            blockers.append({"code": "thread-profile-field-invalid", "field": key})
    if profile.get("policyVersion") != THREAD_BRIDGE_POLICY_VERSION:
        blockers.append({"code": "thread-profile-policy-invalid"})
    if profile.get("transport") != "adapter-owned":
        blockers.append({"code": "thread-profile-transport-invalid"})
    if profile.get("providerIdentityUsed") is not False:
        blockers.append({"code": "thread-profile-provider-identity"})
    if profile.get("hostExecutionOwned") is not True:
        blockers.append({"code": "thread-profile-execution-boundary"})
    if profile.get("qualificationRequired") is not True:
        blockers.append({"code": "thread-profile-qualification-required"})
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "thread-profile-production-claim"})
    for field in ("descriptorDigest", "capabilityManifestDigest"):
        value = profile.get(field)
        if value is not None and (not isinstance(value, str) or len(value) != 64):
            blockers.append({"code": "thread-profile-digest-invalid", "field": field})
    if not isinstance(profile.get("hostRange"), dict):
        blockers.append({"code": "thread-profile-host-range-invalid"})
    _validate_adapter_profile_operations(profile.get("operations"), blockers)
    _check_digest(profile, "profileDigest", blockers)
    return _profile_validation(profile, blockers)


def validate_thread_bridge_qualification_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate an adapter-owned qualification receipt without executing it."""

    blockers: list[dict[str, Any]] = []
    if receipt.get("schemaVersion") != THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA:
        blockers.append({"code": "thread-qualification-schema-invalid"})
    for key in ("receiptId", "adapterId", "host"):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            blockers.append({"code": "thread-qualification-field-invalid", "field": key})
    for field in ("descriptorDigest", "capabilityManifestDigest"):
        _require_digest_field(receipt, field, blockers)
    if receipt.get("policyVersion") != THREAD_BRIDGE_POLICY_VERSION:
        blockers.append({"code": "thread-qualification-policy-invalid"})
    if not isinstance(receipt.get("hostRange"), dict):
        blockers.append({"code": "thread-qualification-host-range-invalid"})
    if receipt.get("route") not in {"native", "wrapper"}:
        blockers.append({"code": "thread-qualification-route-invalid"})
    if receipt.get("qualificationStatus") != "QUALIFIED":
        blockers.append({"code": "thread-qualification-status-invalid"})
    _validate_operation_set(receipt.get("operationSet"), blockers)
    refs = receipt.get("evidenceRefs")
    if not isinstance(refs, list) or not refs or not all(isinstance(item, str) and item for item in refs):
        blockers.append({"code": "thread-qualification-evidence-invalid"})
    for field in ("hostExecutionStarted", "modelCallsStarted", "networkCallsStarted", "rawContentStored", "sourceOfTruth", "proof", "productionPromotionClaimed"):
        expected = field == "hostExecutionStarted"
        if receipt.get(field) is not expected:
            blockers.append({"code": "thread-qualification-boundary-claim", "field": field})
    _check_digest(receipt, "receiptDigest", blockers)
    return _profile_validation(receipt, blockers, receipt_schema=THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA)


def resolve_thread_operation_status(
    profile: dict[str, Any],
    operation: str,
    *,
    qualification_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project adapter status into the existing capability-support enum."""

    profile_validation = validate_thread_bridge_profile(profile)
    blockers = list(profile_validation.get("blockers", []))
    operation_entry = next(
        (item for item in profile.get("operations", []) if isinstance(item, dict) and item.get("name") == operation),
        None,
    )
    if operation_entry is None:
        return {
            "status": "FAIL",
            "operation": operation,
            "declaredStatus": "UNSUPPORTED",
            "qualificationStatus": "INVALID",
            "effectiveStatus": "UNSUPPORTED",
            "capabilitySupport": "unsupported",
            "blockers": blockers + [{"code": "thread-profile-operation-missing", "operation": operation}],
        }
    declared = operation_entry["declaredStatus"]
    effective = declared
    qualification_status = "UNQUALIFIED"
    capability_support = "unsupported" if declared == "UNSUPPORTED" else "unknown"
    if declared == "SUPPORTED":
        effective = "WRAPPER_ONLY"
    if qualification_receipt is not None:
        receipt_validation = validate_thread_bridge_qualification_receipt(qualification_receipt)
        if receipt_validation["status"] != "PASS":
            qualification_status = "INVALID"
            blockers.extend(receipt_validation.get("blockers", []))
        elif declared == "UNSUPPORTED":
            qualification_status = "INVALID"
            blockers.append({"code": "thread-qualification-unsupported-declaration", "operation": operation})
        elif not _qualification_matches(profile, qualification_receipt, operation):
            qualification_status = "STALE"
            blockers.append({"code": "thread-qualification-binding-mismatch", "operation": operation})
        elif operation not in qualification_receipt.get("operationSet", []):
            qualification_status = "STALE"
            blockers.append({"code": "thread-qualification-operation-missing", "operation": operation})
        else:
            qualification_status = "QUALIFIED"
            effective = "SUPPORTED"
            capability_support = "supported"
    return {
        "status": "FAIL" if blockers else "PASS",
        "operation": operation,
        "declaredStatus": declared,
        "qualificationStatus": qualification_status,
        "effectiveStatus": effective,
        "capabilitySupport": capability_support,
        "blockers": blockers,
    }


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
