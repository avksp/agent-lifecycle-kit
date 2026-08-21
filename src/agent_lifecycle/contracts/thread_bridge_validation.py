"""Validation helpers for the optional thread bridge contracts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.redaction import redact_value
from agent_lifecycle.contracts.thread_bridge_schema_definitions import (
    THREAD_ADAPTER_STATUS_VALUES,
    THREAD_BRIDGE_PROFILE_SCHEMA,
    THREAD_BRIDGE_PROFILE_VALIDATION_SCHEMA,
    THREAD_BRIDGE_POLICY_VERSION,
    THREAD_BRIDGE_QUALIFICATION_RECEIPT_SCHEMA,
    THREAD_CAPABILITY_SCHEMA,
    THREAD_CONTEXT_IMPORT_SCHEMA,
    THREAD_EFFECTIVE_STATUS_VALUES,
    THREAD_OPERATION_STATUSES,
    THREAD_OPERATION_VALIDATION_SCHEMA,
    THREAD_OPERATIONS,
    THREAD_QUALIFICATION_STATUS_VALUES,
    THREAD_READ_OPERATIONS,
    THREAD_SCOPES,
    _AUTHORITY_KEYS,
    _AUTHORITY_MARKERS,
)

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
        if "declaredStatus" in item and item.get("declaredStatus") not in THREAD_ADAPTER_STATUS_VALUES:
            blockers.append({"code": "thread-capability-declared-status-invalid", "operation": name})
        if "qualificationStatus" in item and item.get("qualificationStatus") not in THREAD_QUALIFICATION_STATUS_VALUES:
            blockers.append({"code": "thread-capability-qualification-status-invalid", "operation": name})
        if "effectiveStatus" in item and item.get("effectiveStatus") not in THREAD_EFFECTIVE_STATUS_VALUES:
            blockers.append({"code": "thread-capability-effective-status-invalid", "operation": name})
        if "capabilitySupport" in item and item.get("capabilitySupport") != item.get("support"):
            blockers.append({"code": "thread-capability-support-projection-mismatch", "operation": name})


def _normalize_adapter_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(operations, list) or not operations:
        raise LifecycleError("thread-profile-operations-invalid", "thread profile operations must be a non-empty list")
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in operations:
        if not isinstance(item, dict):
            raise LifecycleError("thread-profile-operation-invalid", "thread profile operation must be an object")
        name = item.get("name")
        status = item.get("declaredStatus", item.get("status"))
        if name not in THREAD_OPERATIONS or name in seen:
            raise LifecycleError("thread-profile-operation-invalid", "thread profile operation is unsupported", {"operation": name})
        if status not in THREAD_ADAPTER_STATUS_VALUES:
            raise LifecycleError("thread-profile-status-invalid", "thread profile status is unsupported", {"operation": name})
        seen.add(name)
        entries.append(
            {
                "name": name,
                "declaredStatus": status,
                "readOnly": name in THREAD_READ_OPERATIONS,
                "approval": "none" if name in THREAD_READ_OPERATIONS else "operator",
                "execution": "adapter-owned",
                "qualificationRequired": True,
            }
        )
    return sorted(entries, key=lambda item: item["name"])


def _normalize_operation_set(operation_set: list[str]) -> list[str]:
    if not isinstance(operation_set, list) or not operation_set:
        raise LifecycleError("thread-qualification-operations-invalid", "qualification operationSet must be a non-empty list")
    if any(item not in THREAD_OPERATIONS for item in operation_set) or len(set(operation_set)) != len(operation_set):
        raise LifecycleError("thread-qualification-operations-invalid", "qualification operationSet contains an unsupported or duplicate operation")
    return sorted(operation_set)


def _validate_adapter_profile_operations(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value or len(value) > len(THREAD_OPERATIONS):
        blockers.append({"code": "thread-profile-operations-invalid"})
        return
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            blockers.append({"code": "thread-profile-operation-invalid"})
            continue
        name = item.get("name")
        if name not in THREAD_OPERATIONS or name in seen:
            blockers.append({"code": "thread-profile-operation-invalid", "operation": name})
            continue
        seen.add(name)
        if item.get("declaredStatus") not in THREAD_ADAPTER_STATUS_VALUES:
            blockers.append({"code": "thread-profile-status-invalid", "operation": name})
        if item.get("readOnly") is not (name in THREAD_READ_OPERATIONS):
            blockers.append({"code": "thread-profile-read-only-mismatch", "operation": name})
        expected_approval = "none" if name in THREAD_READ_OPERATIONS else "operator"
        if item.get("approval") != expected_approval:
            blockers.append({"code": "thread-profile-approval-mismatch", "operation": name})
        if item.get("execution") != "adapter-owned":
            blockers.append({"code": "thread-profile-execution-invalid", "operation": name})
        if item.get("qualificationRequired") is not True:
            blockers.append({"code": "thread-profile-qualification-invalid", "operation": name})


def _validate_operation_set(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value or len(value) > len(THREAD_OPERATIONS):
        blockers.append({"code": "thread-qualification-operations-invalid"})
        return
    if any(item not in THREAD_OPERATIONS for item in value):
        blockers.append({"code": "thread-qualification-operation-unsupported"})
    if len(set(value)) != len(value):
        blockers.append({"code": "thread-qualification-operation-duplicate"})


def _qualification_matches(profile: dict[str, Any], receipt: dict[str, Any], operation: str) -> bool:
    return (
        receipt.get("adapterId") == profile.get("adapterId")
        and receipt.get("host") == profile.get("host")
        and receipt.get("descriptorDigest") == profile.get("descriptorDigest")
        and receipt.get("capabilityManifestDigest") == profile.get("capabilityManifestDigest")
        and receipt.get("hostRange") == profile.get("hostRange")
        and receipt.get("policyVersion") == profile.get("policyVersion")
        and operation in receipt.get("operationSet", [])
    )


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


def _profile_validation(
    payload: dict[str, Any],
    blockers: list[dict[str, Any]],
    *,
    receipt_schema: str = THREAD_BRIDGE_PROFILE_SCHEMA,
) -> dict[str, Any]:
    body = {
        "schemaVersion": THREAD_BRIDGE_PROFILE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "adapterId": payload.get("adapterId"),
        "checkedSchema": receipt_schema,
        "checks": [
            {"name": "shape", "status": "PASS" if not blockers else "FAIL"},
            {"name": "digest", "status": "PASS" if not any(item.get("code") == "thread-digest-mismatch" for item in blockers) else "FAIL"},
        ],
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


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
