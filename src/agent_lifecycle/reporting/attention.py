"""Attention and overlap projections for the read-only multi-run view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from agent_lifecycle.contracts import canonical_digest

ATTENTION_REASONS = {
    "BLOCKER_PRESENT",
    "USER_ACTION_REQUIRED",
    "PENDING_REVIEW",
    "STALE_ATTEMPT",
    "FAILED_EVIDENCE",
    "TERMINAL_RUN",
    "SOURCE_UNAVAILABLE",
}

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "INFO": 3}
_REVIEW_PHASES = {"STEP_REVIEW", "FINAL_AUDIT"}
_USER_ACTION_PHASES = {
    "AWAITING_AUTHORIZATION": "authorization required",
    "WAITING_FOR_BUDGET_DECISION": "budget decision required",
    "WAITING_FOR_EXTERNAL_ACTION": "external action required",
}
_TERMINAL_PHASES = {"COMPLETE", "FAILED", "CANCELLED"}


def build_attention_projection(
    sources: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    stale_after_seconds: int = 86_400,
) -> list[dict[str, Any]]:
    """Derive stable attention items without changing any source run."""

    evaluated_at = _utc(now)
    items: list[dict[str, Any]] = []
    for source in sources:
        if source.get("status") != "PASS":
            items.append(_source_unavailable(source))
            continue
        summary_value = source.get("summary")
        summary: dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
        base = _base_item(source, summary)
        blocker = summary.get("blocker")
        if isinstance(blocker, dict):
            items.append(
                _item(
                    base,
                    reason_code="BLOCKER_PRESENT",
                    severity="HIGH",
                    message=str(blocker.get("reason") or blocker.get("message") or "workflow blocker present"),
                    blocker_code=_optional_string(blocker.get("code")),
                )
            )

        phase = _optional_string(summary.get("phase"))
        if phase in _USER_ACTION_PHASES:
            items.append(
                _item(
                    base,
                    reason_code="USER_ACTION_REQUIRED",
                    severity="MEDIUM",
                    message=_USER_ACTION_PHASES[phase],
                )
            )
        if phase in _REVIEW_PHASES:
            items.append(
                _item(
                    base,
                    reason_code="PENDING_REVIEW",
                    severity="MEDIUM",
                    message="workflow review is pending",
                )
            )

        tasks_value = summary.get("tasks")
        tasks: list[Any] = tasks_value if isinstance(tasks_value, list) else []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_base = {**base, "taskId": _optional_string(task.get("taskId"))}
            task_status = _optional_string(task.get("status"))
            if task_status == "VERIFYING":
                items.append(
                    _item(
                        task_base,
                        reason_code="PENDING_REVIEW",
                        severity="MEDIUM",
                        message="task result is awaiting review",
                    )
                )
            deadline = _parse_timestamp(task.get("attemptDeadlineAt"))
            if deadline is None:
                started = _parse_timestamp(task.get("attemptStartedAt"))
                if started is not None:
                    deadline = started + timedelta(seconds=max(0, stale_after_seconds))
            if deadline is not None and deadline < evaluated_at and task_status in {"RUNNING", "VERIFYING", "REWORK"}:
                items.append(
                    _item(
                        task_base,
                        reason_code="STALE_ATTEMPT",
                        severity="HIGH",
                        message="task attempt deadline has elapsed",
                    )
                )
            if task.get("evidenceStatus") == "FAIL":
                items.append(
                    _item(
                        task_base,
                        reason_code="FAILED_EVIDENCE",
                        severity="HIGH",
                        message="task evidence validation failed",
                    )
                )

        if phase in _TERMINAL_PHASES:
            items.append(
                _item(
                    base,
                    reason_code="TERMINAL_RUN",
                    severity="INFO",
                    message=f"run is {phase.lower()}",
                )
            )

    return sorted(items, key=_sort_key)


def build_multi_run_overlap(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Report declared path overlaps without selecting an owner or resolving them."""

    paths: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        if source.get("status") != "PASS":
            continue
        source_paths = source.get("ownershipPaths")
        if not isinstance(source_paths, list):
            continue
        for path in source_paths:
            if isinstance(path, str) and path:
                paths.setdefault(path, []).append(source)

    overlaps: list[dict[str, Any]] = []
    for path, owners in sorted(paths.items()):
        unique = _unique_sources(owners)
        if len(unique) < 2:
            continue
        run_ids = [str(source.get("runId")) for source in unique]
        package_ids = [str(_summary(source).get("packageId")) for source in unique if _summary(source).get("packageId")]
        revisions = [_summary(source).get("planRevision") for source in unique]
        body = {
            "schemaVersion": "agent-multi-run-overlap.v1",
            "path": path,
            "runIds": run_ids,
            "packageIds": package_ids,
            "planRevisions": revisions,
            "authorityRetained": True,
            "reasonCode": "DECLARED_PATH_OVERLAP",
        }
        overlaps.append(
            {
                **body,
                "overlapId": f"overlap-{canonical_digest(body)[:24]}",
            }
        )
    return overlaps


def _source_unavailable(source: dict[str, Any]) -> dict[str, Any]:
    summary_value = source.get("summary")
    summary: dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
    base = _base_item(source, summary)
    blockers = source.get("blockers") if isinstance(source.get("blockers"), list) else []
    first = blockers[0] if blockers and isinstance(blockers[0], dict) else {}
    return _item(
        base,
        reason_code="SOURCE_UNAVAILABLE",
        severity="HIGH",
        message=str(first.get("message") or "selected run could not be safely read"),
        blocker_code=_optional_string(first.get("code")),
    )


def _summary(source: dict[str, Any]) -> dict[str, Any]:
    value = source.get("summary")
    return value if isinstance(value, dict) else {}


def _base_item(source: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": str(source.get("runId") or source.get("sourceId") or "unknown-run"),
        "packageId": summary.get("packageId"),
        "planRevision": summary.get("planRevision"),
        "planDigest": summary.get("planDigest"),
        "sourceRevision": summary.get("sourceRevision"),
        "stateRevision": summary.get("stateRevision"),
        "phase": summary.get("phase"),
        "sourcePath": source.get("rootPath"),
    }


def _item(
    base: dict[str, Any],
    *,
    reason_code: str,
    severity: str,
    message: str,
    blocker_code: str | None = None,
) -> dict[str, Any]:
    if reason_code not in ATTENTION_REASONS:
        raise ValueError(f"unsupported attention reason: {reason_code}")
    body = {
        "schemaVersion": "agent-multi-run-attention-item.v1",
        **base,
        "reasonCode": reason_code,
        "severity": severity,
        "message": message[:512],
        "blockerCode": blocker_code,
    }
    return {**body, "itemId": f"attention-{canonical_digest(body)[:24]}"}


def _sort_key(item: dict[str, Any]) -> tuple[int, str, str, str]:
    return (
        _SEVERITY_ORDER.get(str(item.get("severity")), 9),
        str(item.get("runId", "")),
        str(item.get("taskId") or ""),
        str(item.get("reasonCode", "")),
    )


def _unique_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        key = str(source.get("runId") or source.get("sourceId") or source.get("rootPath"))
        if key not in seen:
            seen.add(key)
            result.append(source)
    return sorted(result, key=lambda value: str(value.get("runId") or value.get("sourceId") or ""))


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc(parsed)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["ATTENTION_REASONS", "build_attention_projection", "build_multi_run_overlap"]
