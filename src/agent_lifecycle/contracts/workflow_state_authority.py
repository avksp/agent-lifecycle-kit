"""Shared lower authority reader; storage representation grants no authority."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.authority_io import (
    authority_location,
    read_authority_bytes,
    resolve_authority_anchor,
)
from agent_lifecycle.contracts.canonical import MAX_JSON_INPUT_BYTES, canonical_bytes, load_json_object
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_state_schemas import (
    WORKFLOW_STATE_V5,
    has_current_workflow_semantics,
    validate_workflow_state,
)
from agent_lifecycle.contracts.workflow_storage import iter_historical_snapshots, validate_storage
from agent_lifecycle.contracts.workflow_storage_context import StorageOperation, choose_operation
from agent_lifecycle.contracts.workflow_storage_io import check_deadline
from agent_lifecycle.contracts.workflow_storage_schemas import IO_DEADLINE_SECONDS

BLOCKER_RECOVERY_ROUTES = {
    "run": {"resolve-run"},
    "task": {"task-review", "budget-decision", "replan-task", "cancel-run"},
    "plan": {"adopt-plan"},
    "external": {"external-action"},
}


def workflow_package_root(state_path: Path, state: dict[str, Any]) -> Path:
    return resolve_authority_anchor(state_path, state.get("packageRoot", "."))


def storage_root_for_state(path: Path, state: dict[str, Any]) -> str:
    root = workflow_package_root(path, state)
    try:
        relative = path.absolute().relative_to(root)
    except ValueError:
        raise LifecycleError("workflow-storage-invalid", "State must be inside its package root") from None
    return relative.with_name(relative.name + ".storage").as_posix()


def require_storage_root(path: Path, state: dict[str, Any]) -> None:
    if state["storage"]["root"] != storage_root_for_state(path, state):
        raise LifecycleError("workflow-storage-invalid", "Immutable storage root is not pinned")


def validate_workflow_authority(
    state: dict[str, Any],
    *,
    root: Path | None = None,
    state_path: Path | None = None,
    operation: StorageOperation | None = None,
) -> dict[str, Any]:
    """Validate the actual compact object, never a relabelled/hydrated projection."""
    validate_workflow_state(state)
    if has_current_workflow_semantics(state):
        validate_recovery_state(state)
    if state.get("schemaVersion") != WORKFLOW_STATE_V5:
        return state
    if root is None or state_path is None or operation is None:
        raise LifecycleError("workflow-storage-context-required", "V5 authority requires root, path and operation")
    operation.check()
    operation.bind_path(state_path)
    operation.bind(root, state)
    anchor = resolve_authority_anchor(state_path, state.get("packageRoot", "."), root=root)
    if authority_location(anchor / ".storage-anchor", root=anchor)[0] != operation.root:
        raise LifecycleError("workflow-storage-invalid", "Package root differs from selected authority root")
    authority_location(anchor / normalize_repo_path(state["eventLog"]), root=root)
    require_storage_root(state_path, state)
    validate_storage(root, state, operation=operation)
    operation.check()
    return state


def decode_workflow_authority(
    raw: bytes,
    *,
    root: Path | None = None,
    state_path: Path | None = None,
    operation: StorageOperation | None = None,
) -> dict[str, Any]:
    """Compose exact already authority-read bytes without changing their identity."""
    if operation is not None:
        operation.check()
    state = load_json_object(raw, label="workflow state")
    if state.get("schemaVersion") == WORKFLOW_STATE_V5 and canonical_bytes(state) + b"\n" != raw:
        raise LifecycleError("workflow-storage-invalid", "V5 state must be exact canonical JSON plus LF")
    return validate_workflow_authority(state, root=root, state_path=state_path, operation=operation)


@contextmanager
def workflow_authority_operation(
    path: Path, *, allow_missing: bool = False, creation_root: Path | None = None
) -> Iterator[StorageOperation | None]:
    """Start once outside native loads/callbacks; nested operations share lifetime."""
    active = StorageOperation.current()
    if active is not None:
        active.bind_path(path)
        if creation_root is not None:
            choose_operation(creation_root, active)
            selected = authority_location(creation_root / ".storage-anchor", root=creation_root)[0]
            if selected != active.root:
                raise LifecycleError("workflow-storage-invalid", "Creation root differs from active operation")
        yield active
        return
    deadline = time.monotonic() + IO_DEADLINE_SECONDS
    check_deadline(deadline)
    try:
        raw = read_authority_bytes(path, max_bytes=MAX_JSON_INPUT_BYTES)
    except FileNotFoundError:
        if not allow_missing:
            raise
        if creation_root is None:
            yield None
        else:
            with StorageOperation(creation_root, state_path=path, deadline=deadline) as operation:
                yield operation
        return
    check_deadline(deadline)
    state = load_json_object(raw, label="workflow state")
    root = workflow_package_root(path, state)
    with StorageOperation(root, state_path=path, run_id=state.get("runId"), deadline=deadline) as operation:
        yield operation


def read_workflow_authority(
    path: Path, *, root: Path | None = None, operation: StorageOperation | None = None
) -> dict[str, Any]:
    if operation is not None:
        selected, _ = choose_operation(root or operation.root, operation)
        return _read_authority_state(path, root or selected.root, selected)
    with workflow_authority_operation(path) as operation:
        assert operation is not None
        return _read_authority_state(path, root or operation.root, operation)


def _read_authority_state(path: Path, root: Path, operation: StorageOperation) -> dict[str, Any]:
    operation.check()
    anchor, name = authority_location(path)
    canonical_path = anchor / name
    selected_root, _ = authority_location(root / ".storage-anchor", root=root)
    if selected_root != operation.root:
        raise LifecycleError("workflow-storage-invalid", "Selected authority root differs from operation")
    operation.bind_path(canonical_path)
    raw = read_authority_bytes(canonical_path, root=selected_root, max_bytes=MAX_JSON_INPUT_BYTES)
    operation.check()
    return decode_workflow_authority(raw, root=selected_root, state_path=canonical_path, operation=operation)


def historical_snapshots(state: dict[str, Any], *, root: Path | None = None) -> Iterator[dict[str, Any]]:
    if state.get("schemaVersion") != WORKFLOW_STATE_V5:
        yield from state.get("priorSnapshots", [])
        return
    operation = StorageOperation.current()
    root = root or (operation.root if operation is not None else None)
    if root is None:
        raise LifecycleError("workflow-storage-context-required", "V5 history requires its authority root")
    yield from iter_historical_snapshots(root, state, operation=operation)


def validate_typed_blocker(
    blocker: Any,
    *,
    expected_task_id: str | None = None,
) -> dict[str, Any]:
    """Validate the closed recovery vocabulary without resolving the blocker."""

    if not isinstance(blocker, dict):
        raise LifecycleError("invalid-workflow-state", "workflow blocker must be an object")
    if "blocker" in blocker or "blockers" in blocker:
        raise LifecycleError("nested-blocker-forbidden", "workflow blockers cannot contain nested blockers")
    for key in ("code", "reason", "scope", "recoveryRoute"):
        value = blocker.get(key)
        if not isinstance(value, str) or not value:
            raise LifecycleError("invalid-workflow-blocker", f"workflow blocker {key} is required")
    scope = blocker["scope"]
    route = blocker["recoveryRoute"]
    if scope not in BLOCKER_RECOVERY_ROUTES or route not in BLOCKER_RECOVERY_ROUTES[scope]:
        raise LifecycleError(
            "invalid-workflow-blocker",
            "workflow blocker recovery route is not valid for its scope",
            {"scope": scope, "recoveryRoute": route},
        )
    task_id = blocker.get("taskId")
    if scope == "task":
        if not isinstance(task_id, str) or not task_id:
            raise LifecycleError("invalid-workflow-blocker", "task blocker requires taskId")
        if expected_task_id is not None and task_id != expected_task_id:
            raise LifecycleError("workflow-blocker-lineage-mismatch", "task blocker taskId mismatch")
    elif task_id is not None:
        raise LifecycleError("invalid-workflow-blocker", "non-task blocker must not carry taskId")
    if "attempt" in blocker and (
        not isinstance(blocker["attempt"], int) or isinstance(blocker["attempt"], bool) or blocker["attempt"] < 1
    ):
        raise LifecycleError("invalid-workflow-blocker", "blocker attempt must be a positive integer")
    return blocker


def validate_recovery_state(state: dict[str, Any]) -> None:
    phase = state.get("phase")
    if phase == "PLAN_ONLY":
        if state.get("startMode") != "plan-only":
            raise LifecycleError("invalid-workflow-state", "PLAN_ONLY requires plan-only start mode")
        authorization = state.get("authorization")
        if isinstance(authorization, dict) and authorization.get("granted") is True:
            raise LifecycleError("plan-only-authorized", "plan-only workflow cannot be authorized")
    blocker = state.get("blocker")
    if blocker is not None:
        validate_typed_blocker(blocker)
        if blocker.get("scope") == "task":
            task = next((item for item in state.get("tasks", []) if item.get("id") == blocker.get("taskId")), None)
            if not isinstance(task, dict):
                raise LifecycleError("workflow-blocker-lineage-mismatch", "task blocker refers to an unknown task")
            task_blocker = task.get("blocker")
            if task_blocker is not None:
                validate_typed_blocker(task_blocker, expected_task_id=str(task.get("id")))
                if task_blocker != blocker and blocker.get("recoveryRoute") != "budget-decision":
                    raise LifecycleError("workflow-blocker-lineage-mismatch", "run and task blockers differ")
    if phase == "BLOCKED" and blocker is None:
        raise LifecycleError("invalid-workflow-state", "BLOCKED state requires a typed blocker")
    if phase == "WAITING_FOR_BUDGET_DECISION" and (
        not isinstance(blocker, dict)
        or blocker.get("scope") != "task"
        or blocker.get("recoveryRoute") != "budget-decision"
    ):
        raise LifecycleError("invalid-workflow-state", "budget wait requires a task budget blocker")
    if phase == "WAITING_FOR_EXTERNAL_ACTION" and not isinstance(state.get("externalAction"), dict):
        raise LifecycleError("invalid-workflow-state", "external-action wait requires externalAction state")
