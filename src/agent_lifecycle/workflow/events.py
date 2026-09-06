"""Append-only workflow event log."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.authority_io import append_authority_bytes, open_authority_read, resolve_authority_anchor
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES, DuplicateJsonMemberError, load_json_object
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
            while line := handle.readline(MAX_JSON_INPUT_BYTES + 1):
                line_number += 1
                if len(line) > MAX_JSON_INPUT_BYTES:
                    raise LifecycleError("json-input-too-large", "JSON input exceeds the configured byte limit")
                if not line.strip():
                    continue
                try:
                    yield load_json_object(line)
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


def append_event(
    *,
    state_path: Path,
    state: dict[str, Any],
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    event = {
        "schemaVersion": "agent-workflow-event.v1",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "stateRevision": state["stateRevision"],
        "operationId": operation_id,
        "eventType": event_type,
        "payload": payload,
        "recordedAt": now_iso(),
    }
    path = event_log_path(state_path, state)
    root = resolve_authority_anchor(state_path, state.get("packageRoot", "."))
    append_authority_bytes(path, canonical_bytes(event) + b"\n", root=root)
    return event
