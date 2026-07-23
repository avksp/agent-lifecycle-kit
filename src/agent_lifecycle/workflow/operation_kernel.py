"""Shared workflow operation commit kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.workflow.events import append_event
from agent_lifecycle.workflow.state import (
    load_state,
    now_iso,
    record_operation,
    require_expected_revision,
    require_operation_unused,
    write_state_replace,
)


def load_for_update(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    state = load_state(state_path)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    return state


def commit_state(
    state_path: Path,
    state: dict[str, Any],
    *,
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    state["stateRevision"] += 1
    state["updatedAt"] = now_iso()
    record_operation(state, operation_id=operation_id, event_type=event_type)
    append_event(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type=event_type,
        payload=payload,
    )
    write_state_replace(state_path, state)
