"""Worker lease and heartbeat receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

WORKER_LEASE_RECEIPT_SCHEMA = "agent-worker-lease-receipt.v1"
WORKER_LEASE_RECEIPT_VALIDATION_SCHEMA = "agent-worker-lease-receipt-validation.v1"

LEASE_STATUSES = {"active", "expired", "completed"}
RECEIPT_STATUSES = {"PASS", "FAIL"}
LINEAGE_KEYS = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")


def build_worker_lease_receipt(
    *,
    lineage: dict[str, Any],
    worker_id: str,
    lease_id: str,
    task_id: str,
    acquired_at: str,
    expires_at: str,
    observed_at: str | None = None,
    heartbeat_at: str | None = None,
    completed_at: str | None = None,
    evidence_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a lease receipt with active/expired/completed classification."""

    observed = observed_at or _now_iso()
    lease_status = classify_lease_status(expires_at=expires_at, observed_at=observed, completed_at=completed_at)
    body = {
        "schemaVersion": WORKER_LEASE_RECEIPT_SCHEMA,
        "status": "FAIL" if blockers else "PASS",
        "lineage": _lineage(lineage, code="invalid-worker-lease-receipt"),
        "workerId": _required_string(worker_id, label="workerId", code="invalid-worker-lease-receipt"),
        "leaseId": _required_string(lease_id, label="leaseId", code="invalid-worker-lease-receipt"),
        "taskId": _required_string(task_id, label="taskId", code="invalid-worker-lease-receipt"),
        "leaseStatus": lease_status,
        "acquiredAt": _iso(acquired_at, label="acquiredAt", code="invalid-worker-lease-receipt"),
        "expiresAt": _iso(expires_at, label="expiresAt", code="invalid-worker-lease-receipt"),
        "observedAt": _iso(observed, label="observedAt", code="invalid-worker-lease-receipt"),
        "heartbeatAt": _optional_iso(heartbeat_at, label="heartbeatAt", code="invalid-worker-lease-receipt"),
        "completedAt": _optional_iso(completed_at, label="completedAt", code="invalid-worker-lease-receipt"),
        "evidenceIds": _string_list(evidence_ids or [], label="evidenceIds", code="invalid-worker-lease-receipt", allow_empty=True),
        "metadata": dict(metadata or {}),
        "blockers": list(blockers or []),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def classify_lease_status(*, expires_at: str, observed_at: str, completed_at: str | None = None) -> str:
    """Classify a lease from deterministic timestamps."""

    if completed_at:
        return "completed"
    expires = _parse_iso(expires_at, label="expiresAt", code="invalid-worker-lease-receipt")
    observed = _parse_iso(observed_at, label="observedAt", code="invalid-worker-lease-receipt")
    return "expired" if observed > expires else "active"


def validate_worker_lease_receipt(receipt: dict[str, Any], *, expected_lineage: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a worker lease receipt and recompute lease state."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-worker-lease-receipt", "worker lease receipt must be an object")
    if receipt.get("schemaVersion") != WORKER_LEASE_RECEIPT_SCHEMA:
        blockers.append({"code": "worker-lease-schema-invalid"})
    status = receipt.get("status")
    if status not in RECEIPT_STATUSES:
        blockers.append({"code": "worker-lease-status-invalid", "status": status})
    lineage = _checked_lineage(receipt.get("lineage"), blockers)
    if expected_lineage is not None and lineage is not None:
        _compare_lineage(lineage, expected_lineage, blockers)
    for key in ("workerId", "leaseId", "taskId"):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            blockers.append({"code": "worker-lease-field-missing", "field": key})
    lease_status = receipt.get("leaseStatus")
    if lease_status not in LEASE_STATUSES:
        blockers.append({"code": "worker-lease-status-class-invalid", "leaseStatus": lease_status})
    acquired = _checked_iso(receipt.get("acquiredAt"), "worker-lease-acquired-invalid", blockers)
    expires = _checked_iso(receipt.get("expiresAt"), "worker-lease-expires-invalid", blockers)
    observed = _checked_iso(receipt.get("observedAt"), "worker-lease-observed-invalid", blockers)
    heartbeat = _checked_optional_iso(receipt.get("heartbeatAt"), "worker-lease-heartbeat-invalid", blockers)
    completed = _checked_optional_iso(receipt.get("completedAt"), "worker-lease-completed-invalid", blockers)
    if acquired and expires and acquired > expires:
        blockers.append({"code": "worker-lease-window-invalid"})
    if heartbeat and acquired and heartbeat < acquired:
        blockers.append({"code": "worker-lease-heartbeat-before-acquire"})
    if completed and acquired and completed < acquired:
        blockers.append({"code": "worker-lease-completed-before-acquire"})
    if expires and observed:
        expected_status = "completed" if completed else "expired" if observed > expires else "active"
        if lease_status != expected_status:
            blockers.append({"code": "worker-lease-status-mismatch", "expected": expected_status, "actual": lease_status})
    _check_string_list(receipt.get("evidenceIds", []), "worker-lease-evidence-ids", blockers, allow_empty=True)
    if not isinstance(receipt.get("metadata", {}), dict):
        blockers.append({"code": "worker-lease-metadata-invalid"})
    _check_object_list(receipt.get("blockers", []), "worker-lease-blockers-invalid", blockers)
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "worker-lease-production-claim"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "worker-lease-receipt-digest-mismatch"})
    body = {
        "schemaVersion": WORKER_LEASE_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": status if isinstance(status, str) else None,
        "workerId": receipt.get("workerId") if isinstance(receipt.get("workerId"), str) else None,
        "leaseId": receipt.get("leaseId") if isinstance(receipt.get("leaseId"), str) else None,
        "taskId": receipt.get("taskId") if isinstance(receipt.get("taskId"), str) else None,
        "leaseStatus": lease_status if isinstance(lease_status, str) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_worker_lease_receipt_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
        raise LifecycleError("worker-lease-validation-failed", "worker lease receipt did not pass", {"validation": validation})
    return validation


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str, *, label: str, code: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} must be an ISO timestamp")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise LifecycleError(code, f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: str, *, label: str, code: str) -> str:
    _parse_iso(value, label=label, code=code)
    return value


def _optional_iso(value: str | None, *, label: str, code: str) -> str | None:
    if value is None:
        return None
    return _iso(value, label=label, code=code)


def _checked_iso(value: Any, code: str, blockers: list[dict[str, Any]]) -> datetime | None:
    if not isinstance(value, str) or not value:
        blockers.append({"code": code})
        return None
    try:
        return _parse_iso(value, label=code, code=code)
    except LifecycleError:
        blockers.append({"code": code})
        return None


def _checked_optional_iso(value: Any, code: str, blockers: list[dict[str, Any]]) -> datetime | None:
    if value is None:
        return None
    return _checked_iso(value, code, blockers)


def _lineage(value: dict[str, Any], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "lineage must be an object")
    return {key: value[key] for key in LINEAGE_KEYS if key in value}


def _checked_lineage(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        blockers.append({"code": "worker-lease-lineage-missing"})
        return None
    for key in ("runId", "packageId", "planDigest", "sourceRevision"):
        if not isinstance(value.get(key), str) or not value[key]:
            blockers.append({"code": "worker-lease-lineage-field-missing", "field": key})
    if not isinstance(value.get("planRevision"), int) or isinstance(value.get("planRevision"), bool) or value.get("planRevision") < 1:
        blockers.append({"code": "worker-lease-lineage-plan-revision-invalid"})
    return value


def _compare_lineage(actual: dict[str, Any], expected: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    for key in LINEAGE_KEYS:
        if key in expected and actual.get(key) != expected.get(key):
            blockers.append({"code": "worker-lease-lineage-mismatch", "field": key})


def _required_string(value: Any, *, label: str, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} is required")
    return value


def _string_list(value: Any, *, label: str, code: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(code, f"{label} must be a list of strings")
    return list(value)


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value) or not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": code})


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})
