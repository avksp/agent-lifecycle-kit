"""Task-level workflow transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.ownership_paths import is_under_authority_path, normalize_authority_path
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_state_schemas import WORKFLOW_STATE_V4
from agent_lifecycle.freeze import verify_plan_lock_envelope
from agent_lifecycle.host_protocol.lifecycle_gate import (
    evaluate_post_action_gate,
    lifecycle_control_selection,
    lifecycle_control_selection_blockers,
    require_lifecycle_gate_pass,
)
from agent_lifecycle.quality.security_analysis import security_analysis_acceptance_blocker
from agent_lifecycle.workflow.artifacts import (
    artifact_identity,
    artifact_path,
    package_root,
    validate_attempt_history,
)
from agent_lifecycle.workflow.gates import record_gate_receipts, validate_controller_gates
from agent_lifecycle.workflow.implementation_audit_gate import (
    task_implementation_audit_required,
    validate_task_implementation_audit_artifact,
    validate_task_implementation_audit_for_rework,
)
from agent_lifecycle.workflow.model_usage import (
    model_usage_receipt_required,
    validate_task_model_usage_receipt,
)
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.reviews import (
    _read_committed_result,
    open_finding_ids,
    task_result_freshness_required,
    validate_task_result,
    validate_task_review,
    validate_task_rework_review,
)
from agent_lifecycle.workflow.risk_execution_gate import validate_attempt_risk_usage
from agent_lifecycle.workflow.selectors import find_task, ready_tasks, unlock_ready_tasks
from agent_lifecycle.workflow.state import now_iso
from agent_lifecycle.workflow.task_start import (
    clear_active_attempt_references,
    require_source_and_authorization,
)
from agent_lifecycle.workflow.task_start import (
    start_task as start_task,
)

# Compatibility export for the existing finalization boundary.
_clear_active_attempt_references = clear_active_attempt_references

MAX_REMEDIATION_FINDINGS = 128
MAX_REMEDIATION_FINDING_ID_LENGTH = 256


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
    validate_attempt_history(state_path, state, task)
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
    freshness = validate_task_result(
        state,
        task,
        result,
        identity,
        repository_root=root,
        require_freshness=task_result_freshness_required(state),
        allow_non_accepting_outcome=state.get("schemaVersion") == WORKFLOW_STATE_V4,
    )
    control_post_action = _validate_control_post_action(state, task, result, root)
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
    if freshness is not None:
        task["resultChangeSetEvidence"] = freshness
    if control_post_action is not None:
        task["lifecycleControlPostAction"] = control_post_action
    task["status"] = "VERIFYING"
    task["lastReason"] = reason
    record_gate_receipts(task, gate_receipts)
    if state.get("schemaVersion") != WORKFLOW_STATE_V4:
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
    expected_phase = "RUNNING" if state.get("schemaVersion") == WORKFLOW_STATE_V4 else "STEP_REVIEW"
    if state["phase"] != expected_phase:
        raise LifecycleError("invalid-phase", "task acceptance requires STEP_REVIEW phase")
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("granted") is not True:
        raise LifecycleError("authorization-required", "task acceptance requires execution authorization")
    task = find_task(state, task_id)
    if task.get("status") != "VERIFYING":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not VERIFYING")
    validate_attempt_history(state_path, state, task)
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
    result = _read_committed_result(root, task)
    validate_task_review(state, task, review, result=result)
    freshness = validate_task_result(
        state,
        task,
        result,
        task["result"],
        repository_root=root,
        require_freshness=task_result_freshness_required(state),
    )
    ownership_paths = freshness["allChangedFiles"] if freshness is not None else result.get("changedFiles", [])
    ownership_receipt = _validate_task_write_scope(
        state,
        task,
        result,
        changed_files=ownership_paths,
        include_plan_scope=freshness is not None,
    )
    implementation_audit = _validate_implementation_audit(
        state_path,
        state,
        task,
        implementation_audit_path=implementation_audit_path,
    )
    _require_control_task_acceptance(state, task)
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


def rework_task(
    state_path: Path,
    *,
    task_id: str,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    review_path: str,
    finding_ids: list[str],
    implementation_audit_path: str | None = None,
    reason: str,
) -> dict[str, Any]:
    """Archive a verified attempt and authorize its next remediation attempt."""

    state = _mutable_state(state_path, operation_id, expected_revision)
    expected_phase = "RUNNING" if state.get("schemaVersion") == WORKFLOW_STATE_V4 else "STEP_REVIEW"
    if state.get("phase") != expected_phase:
        raise LifecycleError("invalid-phase", "task rework requires STEP_REVIEW phase")
    require_source_and_authorization(state, source_revision)
    task = find_task(state, task_id)
    if task.get("status") != "VERIFYING":
        raise LifecycleError("invalid-task-status", f"task {task_id} is not VERIFYING")
    _require_rework_budget(state, task)
    if state.get("schemaVersion") != WORKFLOW_STATE_V4:
        _require_no_active_sibling(state, task_id)
    validate_attempt_history(state_path, state, task)
    root = package_root(state_path, state)
    result = _read_committed_result(root, task)
    validate_task_result(
        state,
        task,
        result,
        task["result"],
        repository_root=root,
        require_freshness=task_result_freshness_required(state),
    )
    expected_review_path = artifact_path(task, "review", int(task["attempt"]))
    if normalize_repo_path(review_path) != expected_review_path:
        raise LifecycleError("artifact-path-mismatch", "task review path does not match frozen template")
    review = read_json_object(root / expected_review_path, label="task review")
    review_identity = artifact_identity(root, expected_review_path, review)
    validate_task_rework_review(state, task, review, result=result)
    required_audit = task_implementation_audit_required(state_path, state, task)
    audit_identity: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    if implementation_audit_path is not None:
        audit_identity, audit = validate_task_implementation_audit_for_rework(
            state_path,
            state,
            task,
            implementation_audit_path,
        )
    elif required_audit:
        raise LifecycleError(
            "implementation-audit-required",
            "task rework requires the configured implementation audit report",
            {"taskId": task_id},
        )
    if review.get("verdict") != "REWORK" and (audit is None or audit.get("verdict") != "REWORK"):
        raise LifecycleError(
            "task-rework-verdict-required",
            "review or implementation audit must have a REWORK verdict",
        )
    requested = _normalize_finding_ids(finding_ids)
    available = set()
    if review.get("verdict") == "REWORK":
        available.update(open_finding_ids(review))
    if audit is not None and audit.get("verdict") == "REWORK":
        available.update(open_finding_ids(audit))
    missing = sorted(set(requested).difference(available))
    omitted = sorted(available.difference(requested))
    if missing or omitted:
        raise LifecycleError(
            "task-rework-finding-mismatch",
            "finding IDs must exactly match the open findings in the REWORK evidence",
            {"missing": missing, "omitted": omitted, "available": sorted(available)},
        )
    task.setdefault("attemptHistory", []).append(
        {
            "schemaVersion": "agent-task-attempt-history-entry.v1",
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "taskId": task.get("id"),
            "attempt": task["attempt"],
            "planRevision": state.get("planRevision"),
            "planDigest": state.get("planDigest"),
            "sourceRevision": state.get("sourceRevision"),
            "result": dict(task["result"]),
            "review": review_identity,
            "implementationAuditReport": audit_identity,
            "findingIds": requested,
            "archivedAt": now_iso(),
        }
    )
    task["remediationFindingIds"] = requested
    clear_active_attempt_references(task)
    task["status"] = "REWORK"
    task["lastReason"] = reason
    if state.get("schemaVersion") != WORKFLOW_STATE_V4:
        state["phase"] = "REMEDIATING"
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="task-rework-requested",
        payload={
            "taskId": task_id,
            "attempt": task["attempt"],
            "findingIds": requested,
            "review": review_identity,
            "implementationAuditReport": audit_identity,
            "reason": reason,
        },
    )
    return status(state_path)


def _validate_implementation_audit(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    *,
    implementation_audit_path: str | None,
) -> dict[str, Any] | None:
    if implementation_audit_path is None:
        if task_implementation_audit_required(state_path, state, task):
            code = security_analysis_acceptance_blocker(task)
            raise LifecycleError(
                code,
                "task acceptance requires an accepted implementation audit report",
                {"taskId": task.get("id")},
            )
        return None
    return validate_task_implementation_audit_artifact(state_path, state, task, implementation_audit_path)


def _mutable_state(state_path: Path, operation_id: str, expected_revision: int) -> dict[str, Any]:
    return load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)


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
    task["remediationFindingIds"] = []
    unlock_ready_tasks(state)
    if state.get("schemaVersion") == WORKFLOW_STATE_V4:
        required = [item for item in state.get("tasks", []) if item.get("required", True)]
        state["phase"] = "FINAL_AUDIT" if all(item.get("status") == "ACCEPTED" for item in required) else "RUNNING"
    else:
        state["phase"] = "RUNNING" if ready_tasks(state) else "FINAL_AUDIT"


def _validate_task_write_scope(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    *,
    changed_files: list[str] | None = None,
    include_plan_scope: bool = False,
) -> dict[str, Any]:
    changed_files = result.get("changedFiles") if changed_files is None else changed_files
    if not isinstance(changed_files, list) or not all(isinstance(path, str) for path in changed_files):
        raise LifecycleError("task-result-invalid", "task result changedFiles must be a list of strings")
    writes = [
        normalize_authority_path(path, label="task write path")
        for path in task.get("writes", [])
        if isinstance(path, str)
    ]
    plan_writes = []
    if include_plan_scope:
        plan_writes = [
            normalize_authority_path(path, label="plan write path")
            for planned_task in state.get("tasks", [])
            if isinstance(planned_task, dict) and planned_task.get("id") != task.get("id")
            for path in planned_task.get("writes", [])
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
    lead_owned_roots = [
        normalize_authority_path(item["path"], label="lead-owned path")
        for item in policy.get("leadOwned", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    entries: list[dict[str, Any]] = []
    for raw_path in sorted(set(changed_files)):
        path = normalize_authority_path(raw_path, label="changed file path")
        forbidden = [root for root in forbidden_roots if is_under_authority_path(path, root)]
        read_only = [root for root in read_only_roots if is_under_authority_path(path, root)]
        owned = [root for root in writes if is_under_authority_path(path, root)]
        plan_owned = [root for root in plan_writes if is_under_authority_path(path, root)]
        lead_owned = [root for root in lead_owned_roots if is_under_authority_path(path, root)]
        if forbidden:
            entries.append({"path": path, "category": "forbidden", "matched": forbidden})
        elif read_only:
            entries.append({"path": path, "category": "read-only", "matched": read_only})
        elif owned:
            entries.append({"path": path, "category": "task-owned", "matched": owned})
        elif plan_owned:
            entries.append({"path": path, "category": "plan-owned", "matched": plan_owned})
        elif lead_owned:
            entries.append({"path": path, "category": "lead-owned", "matched": lead_owned})
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


def _require_rework_budget(state: dict[str, Any], task: dict[str, Any]) -> None:
    budgets = state.get("budgets", {}) if isinstance(state.get("budgets"), dict) else {}
    mode = budgets.get("remediationMode", "off")
    max_attempts = budgets.get("maxTaskAttempts", 1)
    if mode not in {"ask", "bounded-auto"}:
        raise LifecycleError("task-remediation-disabled", "the frozen plan does not enable task remediation")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 2 <= max_attempts <= 10:
        raise LifecycleError("task-attempt-budget-invalid", "enabled remediation requires 2-10 task attempts")
    attempt = task.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise LifecycleError("task-attempt-history-invalid", "task attempt number is invalid")
    if attempt >= max_attempts:
        raise LifecycleError(
            "task-attempt-budget-exhausted",
            "task has no remaining remediation attempt",
            {"attempt": task.get("attempt"), "maxTaskAttempts": max_attempts},
        )


def _require_no_active_sibling(state: dict[str, Any], task_id: str) -> None:
    active = [
        task.get("id")
        for task in state.get("tasks", [])
        if task.get("id") != task_id
        and task.get("status") in {"RUNNING", "VALIDATING", "VERIFYING", "ACCEPTANCE_PENDING"}
    ]
    if active:
        raise LifecycleError(
            "task-rework-active-sibling",
            "task rework requires all sibling tasks to be inactive",
            {"taskIds": active},
        )


def _normalize_finding_ids(finding_ids: list[str]) -> list[str]:
    if not finding_ids or any(not isinstance(item, str) or not item.strip() for item in finding_ids):
        raise LifecycleError("task-rework-findings-required", "at least one non-empty finding ID is required")
    values = sorted(set(item.strip() for item in finding_ids))
    if len(values) > MAX_REMEDIATION_FINDINGS or any(len(item) > MAX_REMEDIATION_FINDING_ID_LENGTH for item in values):
        raise LifecycleError(
            "task-rework-findings-limit",
            "remediation finding IDs exceed the fixed contract limit",
            {"maxFindings": MAX_REMEDIATION_FINDINGS, "maxIdLength": MAX_REMEDIATION_FINDING_ID_LENGTH},
        )
    return values


def _validate_control_post_action(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    root: Path,
) -> dict[str, Any] | None:
    level, policy, evidence = lifecycle_control_selection(state)
    selection_blockers = lifecycle_control_selection_blockers(state, requested_level=level)
    if selection_blockers:
        raise LifecycleError(
            "lifecycle-control-selection-invalid",
            "selected lifecycle control is not bound to the frozen plan",
            {"blockers": selection_blockers},
        )
    if level not in {"OBSERVED", "ENFORCED"}:
        return None
    manifest_path = state.get("manifestPath")
    if not isinstance(manifest_path, str):
        raise LifecycleError(
            "lifecycle-control-context-missing",
            "selected lifecycle control requires the adopted manifest path",
        )
    manifest = read_json_object(root / normalize_repo_path(manifest_path), label="frozen plan manifest")
    lock_path = Path(manifest_path).with_name("plan.lock.json")
    lock = read_json_object(root / normalize_repo_path(lock_path.as_posix()), label="plan lock")
    verify_plan_lock_envelope(manifest, lock)
    selection_blockers = lifecycle_control_selection_blockers(
        state,
        manifest=manifest,
        requested_level=level,
    )
    if selection_blockers:
        raise LifecycleError(
            "lifecycle-control-selection-invalid",
            "selected lifecycle control is not bound to the frozen plan",
            {"blockers": selection_blockers},
        )
    pre_action = task.get("lifecycleControlPreAction")
    if not isinstance(pre_action, dict):
        pre_action = evidence.get("preAction") if isinstance(evidence.get("preAction"), dict) else None
    gate = evaluate_post_action_gate(
        pre_action=pre_action or {},
        manifest=manifest,
        actual_changed_paths=result.get("changedFiles", []),
        outcome={
            "status": "PASS",
            "changed": bool(result.get("changedFiles")),
            "taskId": task.get("id"),
        },
        actual_status="PASS",
        event=evidence.get("postEvent") if isinstance(evidence.get("postEvent"), dict) else None,
        policy=policy,
    )
    require_lifecycle_gate_pass(gate, gate_type="post-action")
    return gate


def _require_control_task_acceptance(state: dict[str, Any], task: dict[str, Any]) -> None:
    level, _, evidence = lifecycle_control_selection(state)
    selection_blockers = lifecycle_control_selection_blockers(state, requested_level=level)
    if selection_blockers:
        raise LifecycleError(
            "lifecycle-control-selection-invalid",
            "selected lifecycle control is not bound to the frozen plan",
            {"blockers": selection_blockers},
        )
    if level not in {"OBSERVED", "ENFORCED"}:
        return
    post_action = task.get("lifecycleControlPostAction")
    if not isinstance(post_action, dict):
        post_action = evidence.get("postAction") if isinstance(evidence.get("postAction"), dict) else None
    if (
        not isinstance(post_action, dict)
        or post_action.get("status") != "PASS"
        or post_action.get("gateDigest")
        != canonical_digest({key: value for key, value in post_action.items() if key != "gateDigest"})
    ):
        raise LifecycleError(
            "lifecycle-control-evidence-required",
            "selected lifecycle control requires accepted post-action evidence",
            {"taskId": task.get("id"), "level": level},
        )
