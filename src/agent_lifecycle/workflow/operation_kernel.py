"""Shared workflow operation commit kernel."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_io import authority_location, open_authority_read, read_authority_bytes
from agent_lifecycle.contracts.canonical import prepare_json_object
from agent_lifecycle.contracts.workflow_state_authority import (
    require_storage_root,
    validate_recovery_state,
    workflow_package_root,
)
from agent_lifecycle.contracts.workflow_state_schemas import validate_workflow_state
from agent_lifecycle.contracts.workflow_storage import (
    PreparedStorage,
    persist_storage,
    preflight_storage,
    prepare_storage,
)
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation
from agent_lifecycle.workflow.checkpoint_gate import (
    PreparedCheckpoint,
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
    artifact_writes: dict[Path, bytes] | None = None,
) -> None:
    selected = _WRITE_OBSERVER.get()
    if selected is None or selected[0] != state_path.resolve():
        return
    values = {path.resolve(): data for path, data in (artifact_writes or {}).items()}
    values[state_path.resolve()] = state_bytes
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
    prepared_writes: dict[Path, bytes] | None = None,
) -> None:
    current = load_state(state_path)
    _require_no_split_brain(state_path, current)
    require_expected_revision(current, state["stateRevision"])
    require_operation_unused(current, operation_id)
    operation = StorageOperation.current()
    if operation is None:
        raise LifecycleError("workflow-storage-context-required", "Native commit requires its transaction context")
    prepare_json_object(payload, label="workflow event input")
    prospective, prepared_storage = _prepare_mutation(state_path, state, operation_id, event_type, operation)
    payload = deepcopy(payload)
    prepared_checkpoint = prepare_checkpoint_gate(
        state_path=state_path,
        state={
            **prospective,
            "stateRevision": state["stateRevision"],
            "updatedAt": state.get("updatedAt") or "1970-01-01T00:00:00Z",
        },
        operation_id=operation_id,
        event_type=event_type,
        payload=payload,
    )
    success_payload, success_event = _prepare_commit_event(
        prospective, payload, prepared_checkpoint.receipt, operation_id, event_type
    )
    failure = None
    if prepared_checkpoint.checkpoint is not None and not prepared_checkpoint.receipt["required"]:
        failure = _prepare_commit_event(
            prospective, payload, optional_checkpoint_failure(prepared_checkpoint), operation_id, event_type
        )
    outputs = dict(prepared_writes or {})
    if prepared_checkpoint.checkpoint is not None:
        outputs[Path(prepared_checkpoint.receipt["checkpointPath"])] = prepare_json_object(
            prepared_checkpoint.checkpoint, label="prospective context checkpoint"
        )
    root = workflow_package_root(state_path, prospective)
    _preflight_outputs(root, state_path, prospective, outputs, prepared_checkpoint)
    checked = None
    if prepared_storage is not None:
        checked = preflight_storage(root, prepared_storage, operation=operation)
        outputs.update(prepared_storage.writes(root, operation=operation))
    record_prepared_workflow_writes(
        state_path,
        prepare_json_object(prospective, label="prospective workflow state"),
        event_path=event_log_path(state_path, prospective),
        event_bytes=prepare_json_object(success_event, label="prospective workflow event"),
        artifact_writes=outputs,
    )
    operation.check()
    if prepared_storage is not None:
        persist_storage(root, prepared_storage, operation=operation, checked=checked)
    for persist in persist_artifacts:
        operation.check()
        persist()
        operation.check()
    operation.check()
    try:
        checkpoint_receipt = persist_checkpoint_gate(prepared_checkpoint)
    finally:
        _observe_checkpoint(prepared_checkpoint, outputs, operation)
    operation.check()
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
    operation.check()
    append_event(
        state_path=state_path,
        state=prospective,
        operation_id=operation_id,
        event_type=event_type,
        payload=final_payload,
        prepared_event=final_event,
    )
    operation._published(event_log_path(state_path, prospective), prepare_json_object(final_event), "APPENDED")
    operation.check()
    if _WRITE_OBSERVER.get() is not None:
        record_prepared_workflow_writes(
            state_path, prepare_json_object(prospective, label="prospective workflow state")
        )
    operation.check()
    write_state_replace(state_path, prospective)
    operation._published(state_path, prepare_json_object(prospective), "REPLACED")
    state.clear()
    state.update(prospective)
    operation.check()


def _prepare_mutation(
    path: Path,
    state: dict[str, Any],
    operation_id: str,
    event_type: str,
    operation: StorageOperation,
) -> tuple[dict[str, Any], PreparedStorage | None]:
    prospective = deepcopy(state)
    prospective["stateRevision"] += 1
    prospective["updatedAt"] = now_iso()
    record_operation(prospective, operation_id=operation_id, event_type=event_type)
    prepared = None
    if prospective.get("schemaVersion") == "agent-workflow-state.v5":
        require_storage_root(path, prospective)
        prepared = prepare_storage(prospective, operation=operation)
        prospective = prepared.state
    validate_workflow_state(prospective)
    if prospective.get("schemaVersion") != "agent-workflow-state.v3":
        validate_recovery_state(prospective)
    prepare_json_object(prospective, label="prospective workflow state")
    return prospective, prepared


def _preflight_outputs(
    root: Path,
    path: Path,
    state: dict[str, Any],
    outputs: dict[Path, bytes],
    checkpoint: PreparedCheckpoint,
) -> None:
    operation = StorageOperation.current()
    assert operation is not None
    event_path = event_log_path(path, state)
    root, _ = authority_location(root / ".storage-anchor", root=root)
    authority = {_canonical_authority_path(path), _canonical_authority_path(event_path)}
    if len(authority) != 2:
        raise LifecycleError("workflow-storage-invalid", "State and event destinations must differ")
    for target in (path, event_path, *outputs):
        operation.check()
        canonical_target = _canonical_authority_path(target)
        selected_root = root
        if checkpoint.checkpoint is not None and target == Path(checkpoint.receipt["checkpointPath"]):
            if checkpoint.root is None:
                raise LifecycleError("workflow-storage-invalid", "Checkpoint output requires its prepared root")
            selected_root = checkpoint.root
        authority_location(canonical_target, root=selected_root)
        if target in outputs:
            if canonical_target in authority:
                raise LifecycleError("workflow-storage-invalid", "Immutable output aliases authority")
            try:
                data = read_authority_bytes(canonical_target, root=selected_root, max_bytes=1_048_576)
            except FileNotFoundError:
                operation.check()
                continue
            operation.check()
            if data != outputs[target]:
                raise LifecycleError("workflow-storage-invalid", "Immutable output collision")
        else:
            try:
                with open_authority_read(canonical_target, root=root):
                    pass
            except FileNotFoundError:
                pass
            operation.check()


def _canonical_authority_path(path: Path) -> Path:
    root, name = authority_location(path)
    return root / name


def _observe_checkpoint(prepared: PreparedCheckpoint, outputs: dict[Path, bytes], operation: StorageOperation) -> None:
    name = prepared.receipt.get("checkpointPath")
    if name is None:
        return
    path = Path(name)
    try:
        actual = read_authority_bytes(path, root=prepared.root or operation.root, max_bytes=1_048_576)
    except FileNotFoundError:
        return
    if actual == outputs.get(path):
        operation._published(path, actual, "CHECKPOINT_OBSERVED")


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
