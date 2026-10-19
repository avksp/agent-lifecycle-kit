"""Append-only workflow event log."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import append_authority_bytes, open_authority_read, resolve_authority_anchor
from agent_lifecycle.contracts.canonical import (
    MAX_JSON_INPUT_BYTES,
    DuplicateJsonMemberError,
    load_json_object,
    prepare_json_object,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.state import now_iso


def event_log_path(state_path: Path, state: dict[str, Any]) -> Path:
    raw = state.get("eventLog")
    if not isinstance(raw, str) or not raw:
        raise LifecycleError("invalid-workflow-state", "eventLog is required")
    relative_name = normalize_repo_path(raw, label="eventLog")
    root = resolve_authority_anchor(state_path, state.get("packageRoot", "."))
    return root / relative_name


def read_events(path: Path) -> Iterator[dict[str, Any]]:
    """Replay a stable journal; consume fully before acting on its records."""

    try:
        with open_authority_read(path) as handle:
            line_number = 0
            last_revision: int | None = None
            operations: set[str] = set()
            while line := handle.readline(MAX_JSON_INPUT_BYTES + 1):
                line_number += 1
                if len(line) > MAX_JSON_INPUT_BYTES:
                    raise LifecycleError("json-input-too-large", "JSON input exceeds the configured byte limit")
                if not line.strip():
                    continue
                try:
                    event = load_json_object(line)
                    revision = event.get("stateRevision")
                    operation = event.get("operationId")
                    legacy_without_id = "schemaVersion" not in event and "operationId" not in event
                    if (
                        type(revision) is not int
                        or revision < 1
                        or (last_revision is not None and revision <= last_revision)
                        or (not legacy_without_id and (not isinstance(operation, str) or not operation))
                        or (isinstance(operation, str) and operation in operations)
                    ):
                        raise LifecycleError(
                            "invalid-workflow-event-log",
                            "workflow event revisions and operation IDs must be unique and ordered",
                            {"line": line_number},
                        )
                    last_revision = revision
                    if isinstance(operation, str):
                        operations.add(operation)
                    yield event
                except DuplicateJsonMemberError:
                    raise
                except LifecycleError as exc:
                    if exc.code not in {"invalid-json", "invalid-json-object"}:
                        raise
                    raise LifecycleError(
                        "invalid-workflow-event-log", "workflow event log contains invalid JSON", {"line": line_number}
                    ) from None
    except FileNotFoundError:
        return
    except LifecycleError as exc:
        if exc.code == "authority-input-unavailable":
            raise LifecycleError("invalid-workflow-event-log", "event log is unavailable") from None
        raise


def prepare_event(
    *,
    state: dict[str, Any],
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
    recorded_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "agent-workflow-event.v1",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "stateRevision": state["stateRevision"],
        "operationId": operation_id,
        "eventType": event_type,
        "payload": payload,
        "recordedAt": recorded_at or now_iso(),
    }


def append_event(
    *,
    state_path: Path,
    state: dict[str, Any],
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
    prepared_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = prepared_event or prepare_event(
        state=state, operation_id=operation_id, event_type=event_type, payload=payload
    )
    expected = prepare_event(
        state=state,
        operation_id=operation_id,
        event_type=event_type,
        payload=payload,
        recorded_at=event.get("recordedAt"),
    )
    if event != expected:
        raise LifecycleError("workflow-event-subject-mismatch", "prepared event does not match the commit")
    data = prepare_json_object(event, label="prospective workflow event")
    path = event_log_path(state_path, state)
    root = resolve_authority_anchor(state_path, state.get("packageRoot", "."))
    append_authority_bytes(path, data, root=root)
    return event
