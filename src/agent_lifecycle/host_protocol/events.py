"""Validate neutral adapter event streams."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.host_protocol.contracts import HostAdapterEvent

TERMINAL_EVENTS = {"task.blocked", "task.completed"}
REQUIRED_COMMON_EVENTS = {"session.started", "task.launched"}
REQUIRED_COMPLETED_EVENTS = {"command.completed", "writes.summarized", "task.completed"}


def validate_adapter_event_stream(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate one host adapter stream without executing host-specific code."""

    blockers: list[dict[str, Any]] = []
    parsed: list[HostAdapterEvent] = []
    if not events:
        blockers.append({"code": "adapter-event-stream-empty", "message": "adapter event stream is empty"})
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            blockers.append({"code": "invalid-adapter-event", "index": index, "message": "event must be an object"})
            continue
        try:
            parsed.append(HostAdapterEvent.from_json(event))
        except LifecycleError as error:
            blockers.append({"code": error.code, "index": index, "message": error.message})
    if parsed:
        _validate_sequence(parsed, blockers)
        _validate_lineage(parsed, blockers)
        _validate_required_events(parsed, blockers)
        _validate_event_statuses(parsed, blockers)
    status = "PASS" if not blockers else "FAIL"
    return {
        "schemaVersion": "agent-adapter-event-stream-validation.v1",
        "status": status,
        "host": parsed[0].host if parsed else None,
        "adapterId": parsed[0].adapter_id if parsed else None,
        "runId": parsed[0].run_id if parsed else None,
        "taskId": parsed[0].task_id if parsed else None,
        "eventCount": len(parsed),
        "eventTypes": [event.event_type for event in parsed],
        "terminalEvent": _terminal_event_type(parsed),
        "blockers": blockers,
    }


def require_adapter_event_stream_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("adapter-event-validation-failed", "adapter event stream validation failed", {"validation": payload})
    return payload


def _validate_sequence(events: list[HostAdapterEvent], blockers: list[dict[str, Any]]) -> None:
    expected = list(range(1, len(events) + 1))
    actual = [event.sequence for event in events]
    if actual != expected:
        blockers.append({"code": "adapter-event-sequence-gap", "expected": expected, "actual": actual})
    event_ids = [event.event_id for event in events]
    duplicates = sorted({event_id for event_id in event_ids if event_ids.count(event_id) > 1})
    if duplicates:
        blockers.append({"code": "adapter-event-duplicate-id", "eventIds": duplicates})


def _validate_lineage(events: list[HostAdapterEvent], blockers: list[dict[str, Any]]) -> None:
    first = events[0]
    for event in events[1:]:
        drift = {
            key: (expected, actual)
            for key, expected, actual in [
                ("host", first.host, event.host),
                ("adapterId", first.adapter_id, event.adapter_id),
                ("runId", first.run_id, event.run_id),
                ("taskId", first.task_id, event.task_id),
            ]
            if expected != actual
        }
        if drift:
            blockers.append({"code": "adapter-event-lineage-mismatch", "eventId": event.event_id, "drift": drift})


def _validate_required_events(events: list[HostAdapterEvent], blockers: list[dict[str, Any]]) -> None:
    event_types = [event.event_type for event in events]
    provided = set(event_types)
    missing_common = sorted(REQUIRED_COMMON_EVENTS - provided)
    if missing_common:
        blockers.append({"code": "adapter-event-required-missing", "eventTypes": missing_common})
    terminals = [event.event_type for event in events if event.event_type in TERMINAL_EVENTS]
    if len(terminals) != 1:
        blockers.append({"code": "adapter-event-terminal-count", "terminalEvents": terminals})
        return
    if terminals[0] == "task.completed":
        missing_completed = sorted(REQUIRED_COMPLETED_EVENTS - provided)
        if missing_completed:
            blockers.append({"code": "adapter-event-required-missing", "eventTypes": missing_completed})
    terminal_index = event_types.index(terminals[0])
    if terminal_index != len(event_types) - 1:
        blockers.append({"code": "adapter-event-after-terminal", "terminalEvent": terminals[0]})


def _validate_event_statuses(events: list[HostAdapterEvent], blockers: list[dict[str, Any]]) -> None:
    expected_by_type = {
        "session.started": {"INFO"},
        "task.launched": {"INFO", "PASS"},
        "usage.reported": {"INFO", "PASS"},
        "writes.summarized": {"INFO", "PASS"},
        "task.blocked": {"BLOCKED"},
        "task.completed": {"PASS"},
    }
    for event in events:
        expected = expected_by_type.get(event.event_type)
        if expected is not None and event.status not in expected:
            blockers.append(
                {
                    "code": "adapter-event-status-mismatch",
                    "eventId": event.event_id,
                    "eventType": event.event_type,
                    "expected": sorted(expected),
                    "actual": event.status,
                }
            )
        if event.event_type == "command.completed" and event.status not in {"PASS", "FAIL"}:
            blockers.append(
                {
                    "code": "adapter-event-status-mismatch",
                    "eventId": event.event_id,
                    "eventType": event.event_type,
                    "expected": ["FAIL", "PASS"],
                    "actual": event.status,
                }
            )


def _terminal_event_type(events: list[HostAdapterEvent]) -> str | None:
    terminals = [event.event_type for event in events if event.event_type in TERMINAL_EVENTS]
    return terminals[0] if len(terminals) == 1 else None
