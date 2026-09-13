"""Shared workflow operation commit kernel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state
from agent_lifecycle.workflow.checkpoint_gate import invoke_checkpoint_gate
from agent_lifecycle.workflow.events import append_event, event_log_path, read_events
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
    _require_no_split_brain(state_path, state)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    return state


def _require_no_split_brain(state_path: Path, state: dict[str, Any]) -> None:
    path = event_log_path(state_path, state)
    last_event = _last_event(path)
    if last_event is None:
        return
    event_revision = last_event.get("stateRevision")
    if not isinstance(event_revision, int):
        raise LifecycleError("invalid-workflow-event-log", "workflow event stateRevision is invalid")
    if event_revision > state["stateRevision"]:
        raise LifecycleError(
            "workflow-split-brain",
            "workflow event log is ahead of state",
            {
                "stateRevision": state["stateRevision"],
                "eventRevision": event_revision,
                "operationId": last_event.get("operationId"),
                "eventType": last_event.get("eventType"),
            },
        )


def _last_event(path: Path) -> dict[str, Any] | None:
    last: dict[str, Any] | None = None
    for event in read_events(path):
        last = event
    return last


def commit_state(
    state_path: Path,
    state: dict[str, Any],
    *,
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    validate_workflow_state(state)
    checkpoint_receipt = invoke_checkpoint_gate(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type=event_type,
        payload=payload,
    )
    payload = {**payload, "contextCheckpoint": checkpoint_receipt}
    state["stateRevision"] += 1
    state["updatedAt"] = now_iso()
    record_operation(state, operation_id=operation_id, event_type=event_type)
    validate_workflow_state(state)
    append_event(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type=event_type,
        payload=payload,
    )
    write_state_replace(state_path, state)
