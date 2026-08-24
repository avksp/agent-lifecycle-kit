"""Attempt snapshot, restore, abandon and selection receipts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

ATTEMPT_SNAPSHOT_RECEIPT_SCHEMA = "agent-runner-attempt-snapshot-receipt.v1"
ATTEMPT_SNAPSHOT_RECEIPT_VALIDATION_SCHEMA = "agent-runner-attempt-snapshot-receipt-validation.v1"

ATTEMPT_ACTIONS = {"snapshot", "restore", "abandon", "select"}
ATTEMPT_RECEIPT_STATUSES = {"PASS", "FAIL"}
LINEAGE_KEYS = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")


def build_attempt_snapshot_receipt(
    *,
    lineage: dict[str, Any],
    task_id: str,
    attempt: int,
    action: str,
    snapshot: dict[str, Any] | None = None,
    restore_source_digest: str | None = None,
    abandon_reason: str | None = None,
    selected_attempt: int | None = None,
    selected_attempt_digest: str | None = None,
    evidence_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
    blockers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a receipt for one deterministic attempt recovery operation."""

    normalized_action = _enum(action, ATTEMPT_ACTIONS, label="action", code="invalid-attempt-snapshot-receipt")
    snapshot_digest = canonical_digest(snapshot) if snapshot is not None else None
    receipt_metadata = dict(metadata or {})
    receipt_metadata.setdefault("authority", "workflow-state-only")
    body = {
        "schemaVersion": ATTEMPT_SNAPSHOT_RECEIPT_SCHEMA,
        "status": _enum(
            status or ("FAIL" if blockers else "PASS"),
            ATTEMPT_RECEIPT_STATUSES,
            label="status",
            code="invalid-attempt-snapshot-receipt",
        ),
        "lineage": _lineage(lineage, code="invalid-attempt-snapshot-receipt"),
        "taskId": _required_string(task_id, label="taskId", code="invalid-attempt-snapshot-receipt"),
        "attempt": _positive_int(attempt, label="attempt", code="invalid-attempt-snapshot-receipt"),
        "action": normalized_action,
        "snapshot": dict(snapshot or {}),
        "snapshotDigest": snapshot_digest,
        "restoreSourceDigest": _optional_digest(
            restore_source_digest, label="restoreSourceDigest", code="invalid-attempt-snapshot-receipt"
        ),
        "abandonReason": _optional_string(abandon_reason),
        "selectedAttempt": _optional_positive_int(
            selected_attempt, label="selectedAttempt", code="invalid-attempt-snapshot-receipt"
        ),
        "selectedAttemptDigest": _optional_digest(
            selected_attempt_digest, label="selectedAttemptDigest", code="invalid-attempt-snapshot-receipt"
        ),
        "evidenceIds": _string_list(
            evidence_ids or [], label="evidenceIds", code="invalid-attempt-snapshot-receipt", allow_empty=True
        ),
        "metadata": receipt_metadata,
        "blockers": list(blockers or []),
        "createdAt": _now_iso(),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_attempt_snapshot_receipt(
    receipt: dict[str, Any],
    *,
    expected_lineage: dict[str, Any] | None = None,
    task_id: str | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    """Validate an attempt recovery receipt without mutating runner state."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-attempt-snapshot-receipt", "attempt snapshot receipt must be an object")
    if receipt.get("schemaVersion") != ATTEMPT_SNAPSHOT_RECEIPT_SCHEMA:
        blockers.append({"code": "attempt-snapshot-schema-invalid"})
    status = receipt.get("status")
    if status not in ATTEMPT_RECEIPT_STATUSES:
        blockers.append({"code": "attempt-snapshot-status-invalid", "status": status})
    lineage = _checked_lineage(receipt.get("lineage"), blockers)
    if expected_lineage is not None and lineage is not None:
        _compare_lineage(lineage, expected_lineage, blockers)
    actual_task_id = _checked_required_string(
        receipt.get("taskId"), blockers, label="taskId", code="attempt-snapshot-task-id-missing"
    )
    if task_id is not None and actual_task_id != task_id:
        blockers.append({"code": "attempt-snapshot-task-id-mismatch", "expected": task_id, "actual": actual_task_id})
    actual_attempt = _checked_positive_int(
        receipt.get("attempt"), blockers, label="attempt", code="attempt-snapshot-attempt-invalid"
    )
    if attempt is not None and actual_attempt != attempt:
        blockers.append({"code": "attempt-snapshot-attempt-mismatch", "expected": attempt, "actual": actual_attempt})
    action = receipt.get("action")
    if action not in ATTEMPT_ACTIONS:
        blockers.append({"code": "attempt-snapshot-action-invalid", "action": action})
    snapshot = receipt.get("snapshot")
    if not isinstance(snapshot, dict):
        blockers.append({"code": "attempt-snapshot-snapshot-invalid"})
        snapshot = {}
    snapshot_digest = receipt.get("snapshotDigest")
    if action == "snapshot":
        if not snapshot:
            blockers.append({"code": "attempt-snapshot-state-missing"})
        _check_digest(snapshot_digest, "attempt-snapshot-digest-invalid", blockers)
    elif snapshot_digest is not None:
        _check_digest(snapshot_digest, "attempt-snapshot-digest-invalid", blockers)
    if snapshot and snapshot_digest != canonical_digest(snapshot):
        blockers.append({"code": "attempt-snapshot-digest-mismatch"})
    restore_source_digest = receipt.get("restoreSourceDigest")
    if action == "restore":
        _check_digest(restore_source_digest, "attempt-restore-source-digest-missing", blockers)
    elif restore_source_digest is not None:
        _check_digest(restore_source_digest, "attempt-restore-source-digest-invalid", blockers)
    abandon_reason = receipt.get("abandonReason")
    if action == "abandon" and not (isinstance(abandon_reason, str) and abandon_reason):
        blockers.append({"code": "attempt-abandon-reason-missing"})
    selected_attempt = receipt.get("selectedAttempt")
    selected_attempt_digest = receipt.get("selectedAttemptDigest")
    if action == "select":
        _checked_positive_int(
            selected_attempt, blockers, label="selectedAttempt", code="attempt-selected-attempt-invalid"
        )
        _check_digest(selected_attempt_digest, "attempt-selected-digest-missing", blockers)
    else:
        if selected_attempt is not None:
            _checked_positive_int(
                selected_attempt, blockers, label="selectedAttempt", code="attempt-selected-attempt-invalid"
            )
        if selected_attempt_digest is not None:
            _check_digest(selected_attempt_digest, "attempt-selected-digest-invalid", blockers)
    _check_string_list(receipt.get("evidenceIds", []), "attempt-snapshot-evidence-ids", blockers, allow_empty=True)
    if not isinstance(receipt.get("metadata", {}), dict):
        blockers.append({"code": "attempt-snapshot-metadata-invalid"})
    elif receipt["metadata"].get("authority") not in {None, "workflow-state-only"}:
        blockers.append({"code": "attempt-snapshot-authority-invalid"})
    _check_object_list(receipt.get("blockers", []), "attempt-snapshot-blockers-invalid", blockers)
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "attempt-snapshot-production-claim"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "attempt-snapshot-receipt-digest-mismatch"})
    body = {
        "schemaVersion": ATTEMPT_SNAPSHOT_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": status if isinstance(status, str) else None,
        "taskId": actual_task_id,
        "attempt": actual_attempt,
        "action": action if isinstance(action, str) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_attempt_snapshot_receipt_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
        raise LifecycleError(
            "attempt-snapshot-validation-failed", "attempt snapshot receipt did not pass", {"validation": validation}
        )
    return validation


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _lineage(value: dict[str, Any], *, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "lineage must be an object")
    return {key: value[key] for key in LINEAGE_KEYS if key in value}


def _checked_lineage(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        blockers.append({"code": "attempt-snapshot-lineage-missing"})
        return None
    for key in ("runId", "packageId", "planDigest", "sourceRevision"):
        if not isinstance(value.get(key), str) or not value[key]:
            blockers.append({"code": "attempt-snapshot-lineage-field-missing", "field": key})
    plan_revision = value.get("planRevision")
    if not isinstance(plan_revision, int) or isinstance(plan_revision, bool) or plan_revision < 1:
        blockers.append({"code": "attempt-snapshot-lineage-plan-revision-invalid"})
    return value


def _compare_lineage(actual: dict[str, Any], expected: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    for key in LINEAGE_KEYS:
        if key in expected and actual.get(key) != expected.get(key):
            blockers.append({"code": "attempt-snapshot-lineage-mismatch", "field": key})


def _required_string(value: Any, *, label: str, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} is required")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _checked_required_string(value: Any, blockers: list[dict[str, Any]], *, label: str, code: str) -> str | None:
    if not isinstance(value, str) or not value:
        blockers.append({"code": code, "field": label})
        return None
    return value


def _positive_int(value: Any, *, label: str, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise LifecycleError(code, f"{label} must be a positive integer")
    return value


def _optional_positive_int(value: Any, *, label: str, code: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, label=label, code=code)


def _checked_positive_int(value: Any, blockers: list[dict[str, Any]], *, label: str, code: str) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        blockers.append({"code": code, "field": label})
        return None
    return value


def _enum(value: Any, allowed: set[str], *, label: str, code: str) -> str:
    if value not in allowed:
        raise LifecycleError(code, f"{label} is unsupported", {label: value})
    return str(value)


def _optional_digest(value: Any, *, label: str, code: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleError(code, f"{label} must be a 64-character digest")
    return value


def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or len(value) != 64:
        blockers.append({"code": code})


def _string_list(value: Any, *, label: str, code: str, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise LifecycleError(code, f"{label} must be a list of strings")
    return list(value)


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        blockers.append({"code": code})


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})
