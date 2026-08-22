"""Task-level workflow transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.ownership_paths import is_under_authority_path, normalize_authority_path
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import (
    artifact_identity,
    artifact_path,
    next_available_attempt,
    package_root,
)
from agent_lifecycle.workflow.gates import record_gate_receipts, validate_controller_gates
from agent_lifecycle.workflow.implementation_audit_gate import (
    task_implementation_audit_required,
    validate_task_implementation_audit_artifact,
)
from agent_lifecycle.workflow.model_usage import (
    model_usage_receipt_required,
    validate_attempt_model_route,
    validate_task_model_usage_receipt,
)
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.reviews import validate_task_result, validate_task_review
from agent_lifecycle.workflow.risk_execution_gate import (
    apply_task_risk_profile,
    clear_task_risk_profile,
    load_task_risk_profile,
    validate_attempt_risk_usage,
)
from agent_lifecycle.workflow.selectors import find_task, ready_tasks, unlock_ready_tasks
from agent_lifecycle.workflow.state import (
    deadline_after,
    now_iso,
)


def start_task(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    risk_profile_path: str | None = None,
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
    _validate_task_authority_paths(state, task)
    if risk_profile_path is not None:
        profile, profile_identity = load_task_risk_profile(
            state_path,
            state,
            task,
            risk_profile_path,
            operation_id=operation_id,
            source_revision=source_revision,
        )
        apply_task_risk_profile(task, profile, profile_identity)
    else:
        clear_task_risk_profile(task)
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
    commit_state(
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
    model_usage_receipt_path: str | None = None,
    budget_targets_path: str | None = None,
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
    model_usage_identity = None
    if model_usage_receipt_required(task):
        if model_usage_receipt_path is None:
            raise LifecycleError(
                "model-usage-receipt-required",
                "task result requires a model usage receipt for the attempt model route",
            )
        usage_path = normalize_repo_path(model_usage_receipt_path, label="model usage receipt")
        receipt = read_json_object(root / usage_path, label="model usage receipt")
        model_usage_identity = artifact_identity(root, usage_path, receipt)
        validation = validate_task_model_usage_receipt(
            state,
            task,
            receipt,
            budget_targets=_read_budget_targets(root, budget_targets_path),
        )
        risk_validation = validate_attempt_risk_usage(task, receipt)
        task["modelUsageReceipt"] = {
            **model_usage_identity,
            "operationId": receipt["operationId"],
            "host": receipt["host"],
            "modelClass": receipt["modelClass"],
            "usage": dict(receipt["usage"]),
            "validation": {
                "status": validation["status"],
                "receiptDigest": validation["receiptDigest"],
                "routeDecisionDigest": validation.get("routeDecisionDigest"),
            },
            "riskValidation": risk_validation,
        }
    elif model_usage_receipt_path is not None:
        raise LifecycleError(
            "unexpected-model-usage-receipt",
            "task attempt does not require a model usage receipt",
        )
    task["result"] = identity
    task["status"] = "VERIFYING"
    task["lastReason"] = reason
    record_gate_receipts(task, gate_receipts)
    state["phase"] = "STEP_REVIEW"
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-result-committed",
        payload={
            "taskId": task_id,
            "attempt": task["attempt"],
            "result": identity,
            "modelUsageReceipt": model_usage_identity,
            "reason": reason,
        },
    )
    return status(state_path)


def accept_task(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    review_path: str,
    implementation_audit_path: str | None = None,
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
    result = _read_committed_result(root, task)
    ownership_receipt = _validate_task_write_scope(state, task, result)
    implementation_audit = _validate_implementation_audit(
        state_path,
        state,
        task,
        implementation_audit_path=implementation_audit_path,
    )
    record_gate_receipts(task, gate_receipts)
    task["ownershipReceipt"] = ownership_receipt
    if implementation_audit is not None:
        task["implementationAuditReport"] = implementation_audit
    _mark_task_accepted(state, task, review, identity, reason)
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-accepted",
        payload={"taskId": task_id, "attempt": task["attempt"], "review": task["review"], "reason": reason},
    )
    return status(state_path)


def _validate_implementation_audit(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    *,
    implementation_audit_path: str | None,
) -> dict[str, Any] | None:
    required = task_implementation_audit_required(state_path, state, task)
    if implementation_audit_path is None:
        if required:
            raise LifecycleError(
                "implementation-audit-required",
                "task acceptance requires an accepted implementation audit report",
                {"taskId": task.get("id")},
            )
        return None
    return validate_task_implementation_audit_artifact(state_path, state, task, implementation_audit_path)


def _mutable_state(
    state_path: Path,
    operation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    return load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)


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
    running = sum(1 for item in state["tasks"] if item.get("status") in {"RUNNING", "VALIDATING", "VERIFYING"})
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
    task.pop("modelUsageReceipt", None)
    task.pop("attemptModelRoute", None)
    task.pop("attemptRiskExecutionProfile", None)
    task["attemptStartedAt"] = now_iso()
    task["attemptBaseRevision"] = state.get("sourceRevision")
    task["attemptDeadlineAt"] = deadline_after(
        task["attemptStartedAt"],
        int(state.get("budgets", {}).get("maxTaskWallSeconds", 3600)),
    )
    task["lastReason"] = reason
    if isinstance(task.get("modelRoute"), dict) and task["modelRoute"]:
        validate_attempt_model_route(task)
        task["attemptModelRoute"] = {
            **task["modelRoute"],
            "attempt": attempt,
        }
    if isinstance(task.get("riskExecutionProfile"), dict) and task["riskExecutionProfile"]:
        task["attemptRiskExecutionProfile"] = {
            **task["riskExecutionProfile"],
            "attempt": attempt,
        }
        wall_cap = task["attemptRiskExecutionProfile"].get("resourceCaps", {}).get("maxWallSeconds")
        if isinstance(wall_cap, int) and wall_cap > 0:
            task["attemptDeadlineAt"] = deadline_after(
                task["attemptStartedAt"],
                min(wall_cap, int(state.get("budgets", {}).get("maxTaskWallSeconds", 3600))),
            )
    state["phase"] = "RUNNING"


def _read_budget_targets(root: Path, budget_targets_path: str | None) -> dict[str, Any] | None:
    if budget_targets_path is None:
        return None
    return read_json_object(
        root / normalize_repo_path(budget_targets_path, label="budget targets"),
        label="budget targets",
    )


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


def _read_committed_result(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    result_identity = task.get("result")
    if not isinstance(result_identity, dict) or not isinstance(result_identity.get("path"), str):
        raise LifecycleError("missing-task-result", "task acceptance requires committed result")
    return read_json_object(root / normalize_repo_path(result_identity["path"]), label="task result")


def _validate_task_write_scope(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    changed_files = result.get("changedFiles")
    if not isinstance(changed_files, list) or not all(isinstance(path, str) for path in changed_files):
        raise LifecycleError("task-result-invalid", "task result changedFiles must be a list of strings")
    writes = [
        normalize_authority_path(path, label="task write path")
        for path in task.get("writes", [])
        if isinstance(path, str)
    ]
    if not writes:
        if changed_files and (state.get("manifestPath") or state.get("packetSet")):
            raise LifecycleError(
                "task-write-scope-missing",
                "adopted task state has changed files but no write scope",
                {"taskId": task.get("id"), "changedFiles": changed_files},
            )
        return {
            "schemaVersion": "agent-task-ownership-receipt.v1",
            "status": "SKIPPED_NO_WRITE_SCOPE",
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "taskId": task.get("id"),
            "attempt": task.get("attempt"),
            "planDigest": state.get("planDigest"),
            "sourceRevision": state.get("sourceRevision"),
            "changedFileCount": len(changed_files),
            "entries": [],
            "blockers": [],
        }
    policy = state.get("writePolicy", {}) if isinstance(state.get("writePolicy"), dict) else {}
    forbidden_roots = [
        normalize_authority_path(path, label="forbidden write path")
        for path in policy.get("forbiddenWrites", [])
        if isinstance(path, str)
    ]
    read_only_roots = [
        normalize_authority_path(path, label="read-only path")
        for path in policy.get("readOnly", [])
        if isinstance(path, str)
    ]
    entries: list[dict[str, Any]] = []
    for raw_path in sorted(set(changed_files)):
        path = normalize_authority_path(raw_path, label="changed file path")
        forbidden = [root for root in forbidden_roots if is_under_authority_path(path, root)]
        read_only = [root for root in read_only_roots if is_under_authority_path(path, root)]
        owned = [root for root in writes if is_under_authority_path(path, root)]
        if forbidden:
            entries.append({"path": path, "category": "forbidden", "matched": forbidden})
        elif read_only:
            entries.append({"path": path, "category": "read-only", "matched": read_only})
        elif owned:
            entries.append({"path": path, "category": "task-owned", "matched": owned})
        else:
            entries.append({"path": path, "category": "unowned"})
    blockers = [entry for entry in entries if entry["category"] in {"forbidden", "read-only", "unowned"}]
    receipt = {
        "schemaVersion": "agent-task-ownership-receipt.v1",
        "status": "PASS" if not blockers else "FAIL",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "changedFileCount": len(entries),
        "entries": entries,
        "blockers": blockers,
    }
    if blockers:
        raise LifecycleError(
            "task-ownership-violation", "task result changed files are outside task write scope", {"ownership": receipt}
        )
    return receipt


def _validate_task_authority_paths(state: dict[str, Any], task: dict[str, Any]) -> None:
    """Reject pseudo-glob task authority before a task state mutation."""

    for path in task.get("writes", []):
        if isinstance(path, str):
            normalize_authority_path(path, label="task write path")
    policy = state.get("writePolicy", {}) if isinstance(state.get("writePolicy"), dict) else {}
    for field in ("readOnly", "forbiddenWrites"):
        for path in policy.get(field, []):
            if isinstance(path, str):
                normalize_authority_path(path, label=f"{field} path")
