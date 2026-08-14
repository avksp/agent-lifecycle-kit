"""Versioned, redacted receipts for bounded host-process execution."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

PROCESS_EXECUTION_RECEIPT_SCHEMA = "agent-process-execution-receipt.v1"
PROCESS_EXECUTION_VALIDATION_SCHEMA = "agent-process-execution-receipt-validation.v1"

AVAILABILITY_STATES = {"ATTESTED", "ESTIMATED", "UNAVAILABLE"}
_FORBIDDEN_RECEIPT_KEYS = {
    "argv",
    "environment",
    "env",
    "command",
    "stdout",
    "stderr",
    "prompt",
    "transcript",
    "localPath",
    "cwd",
}


def build_process_execution_receipt(
    *,
    status: str,
    operation_id: str | None,
    attempt_id: str | None,
    adapter_id: str | None,
    command_identity_hash: str,
    process_identity_hash: str | None,
    group_identity_hash: str | None,
    elapsed_ms: int,
    cpu_ms: dict[str, Any],
    peak_memory_mb: dict[str, Any],
    process_count: dict[str, Any],
    cleanup: dict[str, Any],
    exit_code: int | None,
    timed_out: bool,
    cancelled: bool,
    retry: dict[str, Any] | None = None,
    limits: dict[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a receipt without retaining command, environment or host output."""

    body = {
        "schemaVersion": PROCESS_EXECUTION_RECEIPT_SCHEMA,
        "status": status,
        "operationId": _safe_id(operation_id, "unbound-operation"),
        "attemptId": _safe_id(attempt_id, "attempt-1"),
        "adapterId": _safe_id(adapter_id, "unknown-adapter"),
        "commandIdentityHash": command_identity_hash,
        "processIdentityHash": process_identity_hash,
        "groupIdentityHash": group_identity_hash,
        "timing": {
            "clock": "monotonic",
            "elapsedMs": _non_negative_int(elapsed_ms, "elapsedMs"),
            "availability": "ATTESTED",
        },
        "resources": {
            "cpuMs": _metric(cpu_ms, "ms"),
            "peakMemoryMb": _metric(peak_memory_mb, "MB"),
            "processCount": _metric(process_count, "processes"),
        },
        "cleanup": _safe_mapping(cleanup),
        "exitCode": exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None,
        "timedOut": bool(timed_out),
        "cancelled": bool(cancelled),
        "retry": _safe_mapping(retry or {"attempted": False, "count": 0, "reason": None}),
        "limits": _safe_mapping(limits or {}),
        "blockers": _safe_blockers(blockers or []),
        "rawOutputStored": False,
        "secretsStored": False,
        "modelCallsStarted": False,
        "networkCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_process_execution_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate structure, availability semantics and immutability digest."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-process-execution-receipt", "receipt must be an object")
    if receipt.get("schemaVersion") != PROCESS_EXECUTION_RECEIPT_SCHEMA:
        blockers.append({"code": "process-execution-schema-invalid"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "process-execution-production-claim"})
    if receipt.get("rawOutputStored") is not False or receipt.get("secretsStored") is not False:
        blockers.append({"code": "process-execution-sensitive-storage"})
    for key in _FORBIDDEN_RECEIPT_KEYS:
        if key in receipt:
            blockers.append({"code": "process-execution-raw-field", "field": key})
    _validate_metric(receipt.get("resources", {}).get("cpuMs"), "cpuMs", blockers)
    _validate_metric(receipt.get("resources", {}).get("peakMemoryMb"), "peakMemoryMb", blockers)
    _validate_metric(receipt.get("resources", {}).get("processCount"), "processCount", blockers)
    timing = receipt.get("timing")
    if not isinstance(timing, dict) or timing.get("clock") != "monotonic":
        blockers.append({"code": "process-execution-clock-invalid"})
    elif not _is_non_negative_int(timing.get("elapsedMs")):
        blockers.append({"code": "process-execution-elapsed-invalid"})
    cleanup = receipt.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup.get("status") not in {"PASS", "BLOCKED", "UNAVAILABLE"}:
        blockers.append({"code": "process-execution-cleanup-invalid"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "process-execution-digest-mismatch"})
    body = {
        "schemaVersion": PROCESS_EXECUTION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": receipt.get("status"),
        "cleanupStatus": cleanup.get("status") if isinstance(cleanup, dict) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_process_execution_receipt_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "process-execution-receipt-invalid",
            "process execution receipt validation failed",
            {"validation": validation},
        )
    return validation


def command_identity_hash(argv: list[str]) -> str:
    """Hash argv without retaining its values in the receipt."""

    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise LifecycleError("invalid-process-argv", "argv must be a list of strings")
    return canonical_digest({"argv": argv})


def process_identity_hash(*, pid: int | None, started_ns: int) -> str:
    return canonical_digest({"pid": pid if isinstance(pid, int) else None, "startedNs": started_ns})


def _metric(value: dict[str, Any], unit: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {"value": None, "availability": "UNAVAILABLE", "source": "none"}
    availability = value.get("availability", "UNAVAILABLE")
    if availability not in AVAILABILITY_STATES:
        availability = "UNAVAILABLE"
    metric_value = value.get("value")
    if not isinstance(metric_value, (int, float)) or isinstance(metric_value, bool) or metric_value < 0:
        metric_value = None
    return {
        "value": metric_value,
        "unit": unit,
        "availability": availability,
        "source": _safe_text(value.get("source"), "none"),
    }


def _validate_metric(value: Any, field: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "process-execution-metric-invalid", "field": field})
        return
    if value.get("availability") not in AVAILABILITY_STATES:
        blockers.append({"code": "process-execution-availability-invalid", "field": field})
    metric_value = value.get("value")
    if metric_value is not None and (not isinstance(metric_value, (int, float)) or isinstance(metric_value, bool) or metric_value < 0):
        blockers.append({"code": "process-execution-metric-value-invalid", "field": field})
    if value.get("availability") == "UNAVAILABLE" and metric_value is not None:
        blockers.append({"code": "process-execution-unavailable-value", "field": field})


def _safe_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _safe_value(item) for key, item in sorted(value.items()) if isinstance(key, str)}


def _safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _safe_mapping(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:32]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_blockers(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_safe_mapping(item) for item in value if isinstance(item, dict)][:32]


def _safe_id(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _safe_text(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _non_negative_int(value: Any, label: str) -> int:
    if not _is_non_negative_int(value):
        raise LifecycleError("invalid-process-execution-value", f"{label} must be a non-negative integer")
    return int(value)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
