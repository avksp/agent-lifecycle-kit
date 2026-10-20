"""Shared workflow operation commit kernel."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.canonical import prepare_json_object
from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state
from agent_lifecycle.workflow.checkpoint_gate import (
    optional_checkpoint_failure,
    persist_checkpoint_gate,
    prepare_checkpoint_gate,
)
from agent_lifecycle.workflow.events import append_event, event_log_path, prepare_event, read_events
from agent_lifecycle.workflow.state import (
    load_state,
    now_iso,
    record_operation,
    require_current_authorization,
    require_expected_revision,
    require_operation_unused,
    write_state_replace,
)
from agent_lifecycle.workflow.transactions import workflow_transaction

_WRITE_OBSERVER: ContextVar[tuple[Path, Callable[[dict[Path, bytes]], None]] | None] = ContextVar(
    "alk_prepared_workflow_writes", default=None
)


@contextmanager
def observe_workflow_writes(state_path: Path, observer: Callable[[dict[Path, bytes]], None]) -> Iterator[None]:
    """Observe immutable prepared bytes for one bounded, serialized composition."""
    if _WRITE_OBSERVER.get() is not None:
        raise LifecycleError("workflow-observer-conflict", "A workflow write observer is already active")
    token = _WRITE_OBSERVER.set((state_path.resolve(), observer))
    try:
        yield
    finally:
        _WRITE_OBSERVER.reset(token)


def record_prepared_workflow_writes(
    state_path: Path,
    state_bytes: bytes,
    *,
    event_path: Path | None = None,
    event_bytes: bytes | None = None,
) -> None:
    selected = _WRITE_OBSERVER.get()
    if selected is None or selected[0] != state_path.resolve():
        return
    values = {state_path.resolve(): state_bytes}
    if event_path is not None and event_bytes is not None:
        values[event_path.resolve()] = event_bytes
    selected[1](values)


def load_for_update(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    authorization_required: bool = True,
) -> dict[str, Any]:
    state = load_state(state_path)
    _require_no_split_brain(state_path, state)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    if authorization_required:
        require_current_authorization(state)
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


@workflow_transaction
def commit_state(
    state_path: Path,
    state: dict[str, Any],
    *,
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
    persist_artifacts: tuple[Callable[[], None], ...] = (),
) -> None:
    current = load_state(state_path)
    _require_no_split_brain(state_path, current)
    require_expected_revision(current, state["stateRevision"])
    require_operation_unused(current, operation_id)
    validate_workflow_state(state)
    prepare_json_object(state, label="workflow mutation input")
    prepare_json_object(payload, label="workflow event input")
    prospective = deepcopy(state)
    payload = deepcopy(payload)
    prepared_checkpoint = prepare_checkpoint_gate(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type=event_type,
        payload=payload,
    )
    prospective["stateRevision"] += 1
    prospective["updatedAt"] = now_iso()
    record_operation(prospective, operation_id=operation_id, event_type=event_type)
    validate_workflow_state(prospective)
    prepare_json_object(prospective, label="prospective workflow state")
    success_payload, success_event = _prepare_commit_event(
        prospective, payload, prepared_checkpoint.receipt, operation_id, event_type
    )
    failure = None
    if prepared_checkpoint.checkpoint is not None and not prepared_checkpoint.receipt["required"]:
        failure = _prepare_commit_event(
            prospective, payload, optional_checkpoint_failure(prepared_checkpoint), operation_id, event_type
        )
    for persist in persist_artifacts:
        persist()
    checkpoint_receipt = persist_checkpoint_gate(prepared_checkpoint)
    if checkpoint_receipt == prepared_checkpoint.receipt:
        final_payload, final_event = success_payload, success_event
    elif failure is not None and checkpoint_receipt == optional_checkpoint_failure(prepared_checkpoint):
        final_payload, final_event = failure
    else:
        raise LifecycleError("context-checkpoint-receipt-mismatch", "checkpoint receipt changed after preparation")
    if _WRITE_OBSERVER.get() is not None:
        record_prepared_workflow_writes(
            state_path,
            prepare_json_object(prospective, label="prospective workflow state"),
            event_path=event_log_path(state_path, prospective),
            event_bytes=prepare_json_object(final_event, label="prospective workflow event"),
        )
    append_event(
        state_path=state_path,
        state=prospective,
        operation_id=operation_id,
        event_type=event_type,
        payload=final_payload,
        prepared_event=final_event,
    )
    if _WRITE_OBSERVER.get() is not None:
        record_prepared_workflow_writes(
            state_path, prepare_json_object(prospective, label="prospective workflow state")
        )
    write_state_replace(state_path, prospective)
    state.clear()
    state.update(prospective)


def _prepare_commit_event(
    state: dict[str, Any],
    payload: dict[str, Any],
    checkpoint_receipt: dict[str, Any],
    operation_id: str,
    event_type: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    complete_payload = {**payload, "contextCheckpoint": checkpoint_receipt}
    event = prepare_event(
        state=state,
        operation_id=operation_id,
        event_type=event_type,
        payload=complete_payload,
        recorded_at=state["operationLedger"][operation_id]["recordedAt"],
    )
    prepare_json_object(event, label="prospective workflow event")
    return complete_payload, event
