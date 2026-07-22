"""Append-only workflow event log."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.workflow.state import now_iso


def event_log_path(state_path: Path, state: dict[str, Any]) -> Path:
    raw = state.get("eventLog")
    if not isinstance(raw, str) or not raw:
        raise LifecycleError("invalid-workflow-state", "eventLog is required")
    raw_path = Path(raw)
    if raw_path.is_absolute():
        raise LifecycleError("invalid-workflow-state", "eventLog must be relative")
    package_root = state.get("packageRoot")
    if isinstance(package_root, str) and package_root:
        return (state_path.parent / package_root / raw_path).resolve()
    return state_path.parent / raw_path


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_bytes(event) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    return event
