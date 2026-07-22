"""Task-level workflow transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import (
    artifact_identity,
    artifact_path,
    next_available_attempt,
    package_root,
)
from agent_lifecycle.workflow.events import append_event
from agent_lifecycle.workflow.gates import record_gate_receipts, validate_controller_gates
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.reviews import validate_task_result, validate_task_review
from agent_lifecycle.workflow.selectors import find_task, ready_tasks, unlock_ready_tasks
from agent_lifecycle.workflow.state import (
    deadline_after,
    load_state,
    now_iso,
    record_operation,
    require_expected_revision,
    require_operation_unused,
    write_state_replace,
)


def start_task(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    reason: str,
) -> dict[str, Any]:
    state = _mutable_state(state_path, operation_id, expected_revision)
    if state["phase"] not in {"RUNNING", "REMEDIATING"}:
        raise LifecycleError("invalid-phase", f"cannot start task from phase {state['phase']}")
    _require_source_and_authorization(state, source_revision)
    task = find_task(state, task_id)
    if task.get("status") not in {"READY", "REWORK"}:
        raise LifecycleError("invalid-task-status", f"task {task_id} is not launchable")
    _require_dependencies_accepted(state, task)
    _require_parallel_capacity(state)
    attempt = next_available_attempt(state_path, state, task)
    gate_receipts = validate_controller_gates(
        state_path,
        state,
        task,
        phase="pre-launch",
        operation_id=operation_id,
        attempt=attempt,
    )
    _mark_task_running(state, task, attempt, reason)
    record_gate_receipts(task, gate_receipts)
    _commit_task_event(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-started",
        payload={"taskId": task_id, "attempt": attempt, "reason": reason},
    )
    return status(state_path)


def commit_task_result(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    result_path: str,
    reason: str,
) -> dict[str, Any]:
    state = _mutable_state(state_path, operation_id, expected_revision)
    if state["phase"] != "RUNNING":
        raise LifecycleError("invalid-phase", "task result requires RUNNING phase")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    task = find_task(state, task_id)
    if task.get("status") != "RUNNING":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not RUNNING")
    gate_receipts = validate_controller_gates(
        state_path,
        state,
        task,
        phase="post-attempt",
        operation_id=operation_id,
        attempt=int(task["attempt"]),
    )
    expected_path = artifact_path(task, "result", int(task["attempt"]))
    if normalize_repo_path(result_path) != expected_path:
        raise LifecycleError("artifact-path-mismatch", "task result path does not match frozen template")
    root = package_root(state_path, state)
    result = read_json_object(root / expected_path, label="task result")
    identity = artifact_identity(root, expected_path, result)
    validate_task_result(state, task, result, identity)
    task["result"] = identity
    task["status"] = "VERIFYING"
    task["lastReason"] = reason
    record_gate_receipts(task, gate_receipts)
    state["phase"] = "STEP_REVIEW"
    _commit_task_event(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-result-committed",
        payload={"taskId": task_id, "attempt": task["attempt"], "result": identity, "reason": reason},
    )
    return status(state_path)


def accept_task(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    review_path: str,
    reason: str,
) -> dict[str, Any]:
    state = _mutable_state(state_path, operation_id, expected_revision)
    if state["phase"] != "STEP_REVIEW":
        raise LifecycleError("invalid-phase", "task acceptance requires STEP_REVIEW phase")
    task = find_task(state, task_id)
    if task.get("status") != "VERIFYING":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not VERIFYING")
    gate_receipts = validate_controller_gates(
        state_path,
        state,
        task,
        phase="pre-acceptance",
        operation_id=operation_id,
        attempt=int(task["attempt"]),
    )
    expected_path = artifact_path(task, "review", int(task["attempt"]))
    if normalize_repo_path(review_path) != expected_path:
        raise LifecycleError("artifact-path-mismatch", "task review path does not match frozen template")
    root = package_root(state_path, state)
    review = read_json_object(root / expected_path, label="task review")
    identity = artifact_identity(root, expected_path, review)
    validate_task_review(state, task, review)
    record_gate_receipts(task, gate_receipts)
    _mark_task_accepted(state, task, review, identity, reason)
    _commit_task_event(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-accepted",
        payload={"taskId": task_id, "attempt": task["attempt"], "review": task["review"], "reason": reason},
    )
    return status(state_path)


def _mutable_state(
    state_path: Path,
    operation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    state = load_state(state_path)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    return state


def _require_source_and_authorization(state: dict[str, Any], source_revision: str) -> None:
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("granted") is not True:
        raise LifecycleError("authorization-required", "execution authorization is required")


def _require_dependencies_accepted(state: dict[str, Any], task: dict[str, Any]) -> None:
    accepted = {item.get("id") for item in state["tasks"] if item.get("status") == "ACCEPTED"}
    missing = sorted(set(task.get("dependsOn", [])).difference(accepted))
    if missing:
        raise LifecycleError(
            "task-dependencies-missing",
            f"task {task.get('id')} dependencies are not accepted",
            {"missing": missing},
        )


def _require_parallel_capacity(state: dict[str, Any]) -> None:
    running = sum(
        1
        for item in state["tasks"]
        if item.get("status") in {"RUNNING", "VALIDATING", "VERIFYING"}
    )
    max_parallel = int(state.get("budgets", {}).get("maxParallelTasks", 1))
    if running >= max_parallel:
        raise LifecycleError("parallelism-budget-exhausted", "maxParallelTasks budget reached")


def _mark_task_running(
    state: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
    reason: str,
) -> None:
    task["attempt"] = attempt
    task["status"] = "RUNNING"
    task["usageIterations"] = []
    task["controllerGateReceipts"] = []
    task.pop("result", None)
    task.pop("review", None)
    task["attemptStartedAt"] = now_iso()
    task["attemptDeadlineAt"] = deadline_after(
        task["attemptStartedAt"],
        int(state.get("budgets", {}).get("maxTaskWallSeconds", 3600)),
    )
    task["lastReason"] = reason
    state["phase"] = "RUNNING"


def _mark_task_accepted(
    state: dict[str, Any],
    task: dict[str, Any],
    review: dict[str, Any],
    identity: dict[str, Any],
    reason: str,
) -> None:
    task["review"] = {
        **identity,
        "reviewId": review["reviewId"],
        "reviewer": review["reviewer"]["id"],
        "reviewerRunId": review["reviewer"]["runId"],
        "surface": review["reviewer"]["surface"],
        "verdict": review["verdict"],
    }
    task["status"] = "ACCEPTED"
    task["lastReason"] = reason
    task.pop("attemptStartedAt", None)
    task.pop("attemptDeadlineAt", None)
    unlock_ready_tasks(state)
    state["phase"] = "RUNNING" if ready_tasks(state) else "FINAL_AUDIT"


def _commit_task_event(
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
