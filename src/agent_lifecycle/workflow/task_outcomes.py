"""Canonical task review outcome service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_state_schemas import WORKFLOW_STATE_V4
from agent_lifecycle.workflow.artifacts import artifact_identity, artifact_path, package_root
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.reviews import (
    _read_committed_result,
    open_finding_ids,
    task_result_freshness_required,
    validate_task_outcome_review,
    validate_task_result,
)
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import validate_typed_blocker
from agent_lifecycle.workflow.task_transitions import accept_task, rework_task


def apply_task_review_outcome(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    review_path: str,
    finding_ids: list[str] | None = None,
    implementation_audit_path: str | None = None,
    reason: str,
) -> dict[str, Any]:
    """Apply exactly one independently reviewed task outcome."""

    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("granted") is not True:
        raise LifecycleError("authorization-required", "task outcome requires execution authorization")
    task = find_task(state, task_id)
    if task.get("status") != "VERIFYING":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not VERIFYING")
    root = package_root(state_path, state)
    expected_review_path = artifact_path(task, "review", int(task["attempt"]))
    if normalize_repo_path(review_path) != expected_review_path:
        raise LifecycleError("artifact-path-mismatch", "task review path does not match frozen template")
    review = read_json_object(root / expected_review_path, label="task review")
    result = _read_committed_result(root, task)
    validate_task_result(
        state,
        task,
        result,
        task["result"],
        repository_root=root,
        require_freshness=task_result_freshness_required(state),
        allow_non_accepting_outcome=True,
    )
    verdict = validate_task_outcome_review(state, task, review, result=result)
    if verdict == "ACCEPTED":
        return accept_task(
            state_path,
            task_id=task_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            review_path=review_path,
            implementation_audit_path=implementation_audit_path,
            reason=reason,
        )
    if verdict == "REWORK":
        return rework_task(
            state_path,
            task_id=task_id,
            operation_id=operation_id,
            expected_revision=expected_revision,
            source_revision=source_revision,
            review_path=review_path,
            finding_ids=finding_ids or [],
            implementation_audit_path=implementation_audit_path,
            reason=reason,
        )
    expected_phase = "RUNNING" if state.get("schemaVersion") == WORKFLOW_STATE_V4 else "STEP_REVIEW"
    if state.get("phase") != expected_phase:
        raise LifecycleError("invalid-phase", "task outcome requires a reviewable workflow phase")
    review_identity = artifact_identity(root, expected_review_path, review)
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        raise LifecycleError("task-review-invalid", "task review reviewer identity is required")
    task["review"] = {
        **review_identity,
        "reviewId": review.get("reviewId"),
        "reviewer": reviewer.get("id"),
        "reviewerRunId": reviewer.get("runId"),
        "surface": reviewer.get("surface"),
        "verdict": verdict,
    }
    task["lastReason"] = reason
    task["outcome"] = {
        "verdict": verdict,
        "attempt": task.get("attempt"),
        "findingIds": sorted(open_finding_ids(review)),
    }
    if verdict == "CONTRACT_CHANGE":
        task["contractChangeRequest"] = {
            **dict(review["contractChangeRequest"]),
            "scope": "plan",
            "recoveryRoute": "adopt-plan",
            "taskId": task_id,
        }
    else:
        blocker = {
            **dict(review["blocker"]),
            "scope": dict(review["blocker"]).get("scope", "task"),
            "recoveryRoute": dict(review["blocker"]).get("recoveryRoute", "task-review"),
            "taskId": task_id,
            "attempt": task.get("attempt"),
        }
        validate_typed_blocker(blocker, expected_task_id=task_id)
        task["blocker"] = blocker
    task["status"] = verdict
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-outcome-applied",
        payload={
            "taskId": task_id,
            "attempt": task.get("attempt"),
            "verdict": verdict,
            "review": review_identity,
            "reason": reason,
        },
    )
    return status(state_path)
