"""Terminal workflow finalization."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.goal_validation import validate_goal_record
from agent_lifecycle.contracts.implementation_audit_validation import (
    validate_final_audit_outcome_report,
    validate_final_implementation_audit,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.followup import validate_followup_register
from agent_lifecycle.host_protocol.lifecycle_gate import (
    evaluate_stop_gate,
    lifecycle_control_selection,
    require_lifecycle_gate_pass,
)
from agent_lifecycle.specification import (
    require_completion_gate_finalization,
    validate_completion_check,
    validate_completion_check_receipt,
    validate_completion_signal,
)
from agent_lifecycle.workflow.artifacts import (
    artifact_identity,
    next_available_attempt,
    package_root,
    validate_attempt_history,
)
from agent_lifecycle.workflow.final_proof_integrity import validate_final_proof_integrity
from agent_lifecycle.workflow.gates import record_gate_receipts, validate_controller_gates
from agent_lifecycle.workflow.implementation_audit_gate import (
    final_implementation_audit_required,
    missing_required_implementation_audits,
    require_final_implementation_audit_pass,
)
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.review_mesh_gate import (
    require_review_mesh_quorum_gate_pass,
    validate_review_mesh_quorum_path,
)
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import now_iso, validate_typed_blocker
from agent_lifecycle.workflow.task_transitions import _clear_active_attempt_references


def apply_final_audit_outcome(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    final_audit_path: str,
    verdict: str,
    task_ids: list[str] | None = None,
    finding_ids: list[str] | None = None,
    reason: str,
) -> dict[str, Any]:
    """Apply one independent final-audit verdict without changing plan authority."""

    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state.get("phase") != "FINAL_AUDIT":
        raise LifecycleError("invalid-phase", "final-audit outcome requires FINAL_AUDIT phase")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    root = package_root(state_path, state)
    audit_rel = normalize_repo_path(final_audit_path, label="final audit")
    audit = read_json_object(root / audit_rel, label="final audit")
    audit_identity = artifact_identity(root, audit_rel, audit)
    selected_tasks = _sorted_unique(task_ids or [])
    selected_findings = _sorted_unique(finding_ids or [])
    validation = validate_final_audit_outcome_report(
        audit,
        state=state,
        verdict=verdict,
        task_ids=selected_tasks,
        finding_ids=selected_findings,
    )
    if validation["status"] != "PASS":
        raise LifecycleError(
            "final-audit-outcome-invalid",
            "final audit outcome failed validation",
            {"validation": validation},
        )
    blocker: dict[str, Any] | None = None
    if verdict == "REWORK":
        _apply_final_audit_rework(
            state_path,
            state,
            audit,
            task_ids=selected_tasks,
            finding_ids=selected_findings,
            reason=reason,
        )
    elif verdict == "CONTRACT_CHANGE":
        blocker = {
            "code": "FINAL_AUDIT_CONTRACT_CHANGE",
            "reason": reason,
            "scope": "plan",
            "recoveryRoute": "adopt-plan",
        }
        validate_typed_blocker(blocker)
        state["phase"] = "BLOCKED"
        state["blocker"] = blocker
    elif verdict == "BLOCKED":
        external_action = _final_audit_external_action(audit)
        blocker = {
            "code": "FINAL_AUDIT_BLOCKED",
            "reason": reason,
            "scope": "external",
            "recoveryRoute": "external-action",
            "externalAction": external_action,
        }
        validate_typed_blocker(blocker)
        state["phase"] = "WAITING_FOR_EXTERNAL_ACTION"
        state["blocker"] = blocker
        state["externalAction"] = external_action
    outcome_body = {
        "schemaVersion": "agent-final-audit-outcome.v1",
        "status": "PASS",
        "verdict": verdict,
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "finalAudit": audit_identity,
        "taskIds": selected_tasks,
        "findingIds": selected_findings,
        "validation": validation,
        "blocker": state.get("blocker") if verdict in {"CONTRACT_CHANGE", "BLOCKED"} else None,
        "contractChangeRequest": audit.get("contractChangeRequest") if verdict == "CONTRACT_CHANGE" else None,
        "productionPromotionClaimed": False,
        "reason": reason,
        "appliedAt": now_iso(),
    }
    outcome = {**outcome_body, "outcomeDigest": canonical_digest(outcome_body)}
    state["finalAuditOutcome"] = outcome
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="final-audit-outcome-applied",
        payload={
            "verdict": verdict,
            "finalAudit": audit_identity,
            "taskIds": selected_tasks,
            "findingIds": selected_findings,
            "reason": reason,
        },
    )
    return status(state_path)


def _apply_final_audit_rework(
    state_path: Path,
    state: dict[str, Any],
    audit: dict[str, Any],
    *,
    task_ids: list[str],
    finding_ids: list[str],
    reason: str,
) -> None:
    findings_by_task: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    for finding in audit.get("findings", []):
        if not isinstance(finding, dict) or finding.get("status") != "open":
            continue
        finding_id = finding.get("id")
        if finding_id not in finding_ids:
            continue
        raw_task_ids = finding.get("taskIds")
        mapped = list(raw_task_ids) if isinstance(raw_task_ids, list) else [finding.get("taskId")]
        mapped = [item for item in mapped if isinstance(item, str)]
        if not mapped or not set(mapped).issubset(task_ids):
            raise LifecycleError(
                "final-audit-outcome-task-mapping",
                "every rework finding must map to a named task",
                {"findingId": finding_id, "taskIds": mapped},
            )
        for task_id in mapped:
            findings_by_task[task_id].append(str(finding_id))
    if any(not values for values in findings_by_task.values()):
        raise LifecycleError(
            "final-audit-outcome-task-mapping",
            "every named rework task must have an open final-audit finding",
            {"tasks": [task_id for task_id, values in findings_by_task.items() if not values]},
        )
    planned: list[tuple[dict[str, Any], int]] = []
    for task_id in task_ids:
        task = find_task(state, task_id)
        if task.get("status") != "ACCEPTED":
            raise LifecycleError("final-audit-outcome-task-status", f"task {task_id} is not ACCEPTED")
        validate_attempt_history(state_path, state, task)
        next_attempt = next_available_attempt(state_path, state, task)
        for key in ("result", "review"):
            if not isinstance(task.get(key), dict):
                raise LifecycleError("final-audit-outcome-artifact-missing", f"accepted task {task_id} has no {key}")
        planned.append((task, next_attempt))
    for task, _next_attempt in planned:
        task.setdefault("attemptHistory", []).append(
            {
                "schemaVersion": "agent-task-attempt-history-entry.v1",
                "runId": state.get("runId"),
                "packageId": state.get("packageId"),
                "taskId": task.get("id"),
                "attempt": task.get("attempt"),
                "planRevision": state.get("planRevision"),
                "planDigest": state.get("planDigest"),
                "sourceRevision": state.get("sourceRevision"),
                "result": dict(task["result"]),
                "review": dict(task["review"]),
                "implementationAuditReport": dict(task["implementationAuditReport"])
                if isinstance(task.get("implementationAuditReport"), dict)
                else None,
                "findingIds": sorted(findings_by_task[str(task["id"])]),
                "archivedAt": now_iso(),
            }
        )
        _clear_active_attempt_references(task)
        task.pop("blocker", None)
        task.pop("contractChangeRequest", None)
        task["remediationFindingIds"] = sorted(findings_by_task[str(task["id"])])
        task["status"] = "REWORK"
        task["lastReason"] = reason
    state["phase"] = "REMEDIATING" if state.get("schemaVersion") == "agent-workflow-state.v3" else "RUNNING"
    state["blocker"] = None


def _final_audit_external_action(audit: dict[str, Any]) -> dict[str, Any]:
    value = audit.get("externalAction")
    if not isinstance(value, dict):
        blocker = audit.get("blocker")
        value = blocker.get("externalAction") if isinstance(blocker, dict) else None
    if not isinstance(value, dict):
        raise LifecycleError(
            "final-audit-external-action-required",
            "BLOCKED final audit requires external action metadata",
        )
    action_id = value.get("actionId")
    receipt_path = value.get("expectedReceiptPath")
    if not isinstance(action_id, str) or not action_id or not isinstance(receipt_path, str) or not receipt_path:
        raise LifecycleError(
            "final-audit-external-action-invalid",
            "final audit external action metadata is incomplete",
        )
    return {
        "actionId": action_id,
        "reason": str(value.get("reason") or "final audit requires external action"),
        "resumePhase": str(value.get("resumePhase") or "FINAL_AUDIT"),
        "expectedReceiptPath": normalize_repo_path(receipt_path, label="external action receipt"),
    }


def _sorted_unique(values: list[str]) -> list[str]:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise LifecycleError("invalid-final-audit-outcome", "task and finding IDs must be non-empty strings")
    result = sorted(set(value.strip() for value in values))
    if len(result) != len(values):
        raise LifecycleError("invalid-final-audit-outcome", "task and finding IDs must not repeat")
    return result


def finalize_run(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    final_audit_path: str,
    proof_path: str,
    proof_integrity_path: str | None = None,
    goal_record_path: str | None = None,
    follow_up_register_path: str | None = None,
    completion_gate_receipt_path: str | None = None,
    final_implementation_audit_path: str | None = None,
    review_mesh_quorum_paths: list[str] | None = None,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state.get("phase") != "FINAL_AUDIT":
        raise LifecycleError("invalid-phase", "run finalization requires FINAL_AUDIT phase")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    outcome = state.get("finalAuditOutcome")
    if state.get("schemaVersion") == "agent-workflow-state.v4" and not isinstance(outcome, dict):
        raise LifecycleError("final-audit-outcome-required", "v4 finalization requires an applied final-audit outcome")
    if isinstance(outcome, dict) and outcome.get("verdict") not in {None, "ACCEPTED"}:
        raise LifecycleError("final-audit-outcome-not-accepted", "final audit outcome does not permit finalization")
    missing = _missing_required_acceptance(state)
    if missing:
        raise LifecycleError("finalization-precondition-failed", "required tasks are not accepted", {"tasks": missing})
    missing_implementation_audits = missing_required_implementation_audits(state_path, state)
    if missing_implementation_audits:
        raise LifecycleError(
            "implementation-audit-required",
            "required implementation audit reports are missing",
            {"tasks": missing_implementation_audits},
        )
    root = package_root(state_path, state)
    final_audit_rel = normalize_repo_path(final_audit_path)
    final_audit = read_json_object(root / final_audit_rel, label="final audit")
    raw_final_audit = deepcopy(final_audit)
    final_audit_identity = artifact_identity(root, final_audit_rel, final_audit)
    _validate_final_audit(state, final_audit)
    completion_check_receipt = _validate_completion_check(state, root)
    goal_record = _validate_goal_record(state, root, goal_record_path)
    follow_up_register = _validate_follow_up_register(state, root, follow_up_register_path)
    completion_gate = _validate_completion_gate(
        state,
        root,
        raw_final_audit,
        completion_gate_receipt_path=completion_gate_receipt_path,
        follow_up_register_path=follow_up_register_path,
    )
    proof_integrity = _validate_proof_integrity(state, root, final_audit, proof_integrity_path)
    final_implementation_audit = _validate_final_implementation_audit(
        state_path,
        state,
        root,
        final_implementation_audit_path=final_implementation_audit_path,
    )
    finalization_gate_receipts = _validate_finalization_gates(
        state_path,
        state,
        operation_id=operation_id,
    )
    review_mesh_quorum = _validate_review_mesh_final_quorum(
        root,
        state,
        review_mesh_quorum_paths or [],
    )
    proof_rel = normalize_repo_path(proof_path)
    lifecycle_control_stop = _evaluate_lifecycle_control_stop(
        state,
        final_audit=final_audit,
        final_proof=_proof_body(
            state,
            operation_id=operation_id,
            final_audit=final_audit_identity,
            completion_check_receipt=completion_check_receipt,
            completion_gate=completion_gate,
            goal_record=goal_record,
            follow_up_register=follow_up_register,
            proof_integrity=proof_integrity,
            final_implementation_audit=final_implementation_audit,
            finalization_gate_receipts=finalization_gate_receipts,
            review_mesh_quorum=review_mesh_quorum,
            lifecycle_control_stop=None,
            reason=reason,
        ),
    )
    proof = _proof_body(
        state,
        operation_id=operation_id,
        final_audit=final_audit_identity,
        completion_check_receipt=completion_check_receipt,
        completion_gate=completion_gate,
        goal_record=goal_record,
        follow_up_register=follow_up_register,
        proof_integrity=proof_integrity,
        final_implementation_audit=final_implementation_audit,
        finalization_gate_receipts=finalization_gate_receipts,
        review_mesh_quorum=review_mesh_quorum,
        lifecycle_control_stop=lifecycle_control_stop,
        reason=reason,
    )
    write_json_create(root / proof_rel, proof)
    identity = artifact_identity(root, proof_rel, proof)
    state["finalProof"] = {**identity, "semanticStatus": proof["semanticStatus"]}
    state["finalAudit"] = final_audit_identity
    if completion_check_receipt is not None:
        state["completionCheckReceipt"] = completion_check_receipt["receipt"]
    if completion_gate is not None:
        state["completionGateReceipt"] = completion_gate["receipt"]
    if goal_record is not None:
        state["goalRecord"] = goal_record["record"]
    if follow_up_register is not None:
        state["followUpRegister"] = follow_up_register["register"]
    if proof_integrity is not None:
        state["proofIntegrityReceipt"] = proof_integrity["receipt"]
    if final_implementation_audit is not None:
        state["finalImplementationAudit"] = final_implementation_audit["audit"]
    if review_mesh_quorum is not None:
        state["reviewMeshFinalQuorum"] = review_mesh_quorum
    if lifecycle_control_stop is not None:
        state["lifecycleControlStop"] = lifecycle_control_stop
    state["phase"] = "COMPLETE"
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="run-finalized",
        payload={
            "finalAudit": final_audit_identity,
            "completionCheckReceipt": completion_check_receipt,
            "completionGate": completion_gate,
            "goalRecord": goal_record,
            "followUpRegister": follow_up_register,
            "proofIntegrity": proof_integrity,
            "finalImplementationAudit": final_implementation_audit,
            "finalizationGateReceipts": finalization_gate_receipts,
            "reviewMeshQuorum": review_mesh_quorum,
            "lifecycleControlStop": lifecycle_control_stop,
            "proof": state["finalProof"],
            "reason": reason,
        },
    )
    return status(state_path)


def _missing_required_acceptance(state: dict[str, Any]) -> list[str]:
    return [
        str(task.get("id"))
        for task in state.get("tasks", [])
        if task.get("required", True) and task.get("status") != "ACCEPTED"
    ]


def _validate_final_audit(state: dict[str, Any], final_audit: dict[str, Any]) -> None:
    if final_audit.get("schemaVersion") not in {"agent-final-candidate-audit.v1", "agent-run-final-audit.v1"}:
        raise LifecycleError("invalid-final-audit", "final audit schemaVersion is unsupported")
    expected = {
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
    }
    for key, value in expected.items():
        if final_audit.get(key) != value:
            raise LifecycleError("final-audit-lineage-mismatch", f"final audit {key} mismatch")
    if final_audit.get("status") != "PASS" or final_audit.get("semanticStatus") != "READY_FOR_FINALIZATION":
        raise LifecycleError("final-audit-not-ready", "final audit is not ready for finalization")
    completion_signal = final_audit.get("completionSignal")
    if completion_signal is None:
        raise LifecycleError("completion-signal-required", "final audit completionSignal is required")
    if not isinstance(completion_signal, dict):
        raise LifecycleError("invalid-final-audit", "final audit completionSignal must be an object")
    completion_signal_validation = validate_completion_signal(completion_signal, state=state)
    final_audit["completionSignalValidation"] = completion_signal_validation
    if final_audit.get("productionPromotionClaimed") is not False:
        raise LifecycleError("final-audit-production-claim", "final audit must not claim production promotion")
    if final_audit.get("notAcceptedTasks"):
        raise LifecycleError("final-audit-open-tasks", "final audit reports non-accepted tasks")
    if final_audit.get("missingReleaseEvidence"):
        raise LifecycleError("final-audit-missing-evidence", "final audit reports missing release evidence")
    findings = final_audit.get("findings", [])
    if not isinstance(findings, list):
        raise LifecycleError("invalid-final-audit", "final audit findings must be an array")
    open_blocking = [
        item.get("id")
        for item in findings
        if isinstance(item, dict)
        and item.get("status") == "open"
        and item.get("severity") in {"BLOCKER", "HIGH", "MEDIUM"}
    ]
    if open_blocking:
        raise LifecycleError(
            "final-audit-open-findings",
            "final audit has unresolved MEDIUM+ findings",
            {"findings": open_blocking},
        )


def _validate_finalization_gates(
    state_path: Path,
    state: dict[str, Any],
    *,
    operation_id: str,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for task in state.get("tasks", []):
        if task.get("status") != "ACCEPTED":
            continue
        task_receipts = validate_controller_gates(
            state_path,
            state,
            task,
            phase="finalization",
            operation_id=operation_id,
            attempt=int(task.get("attempt", 0)),
        )
        record_gate_receipts(task, task_receipts)
        receipts.extend(task_receipts)
    return receipts


def _evaluate_lifecycle_control_stop(
    state: dict[str, Any],
    *,
    final_audit: dict[str, Any],
    final_proof: dict[str, Any],
) -> dict[str, Any] | None:
    level, policy, evidence = lifecycle_control_selection(state)
    if level == "OFF":
        return None
    pre_action = evidence.get("finalizePreAction") if isinstance(evidence.get("finalizePreAction"), dict) else None
    post_action = evidence.get("finalizePostAction") if isinstance(evidence.get("finalizePostAction"), dict) else None
    gate = evaluate_stop_gate(
        state=state,
        final_audit=final_audit,
        final_proof=final_proof,
        pre_action=pre_action,
        post_action=post_action,
        requested_level=level,
        policy=policy,
    )
    require_lifecycle_gate_pass(gate, gate_type="stop")
    return gate


def _validate_review_mesh_final_quorum(
    root: Path, state: dict[str, Any], quorum_receipt_paths: list[str]
) -> dict[str, Any] | None:
    config = state.get("reviewMesh") if isinstance(state.get("reviewMesh"), dict) else None
    receipt_path = quorum_receipt_paths[0] if quorum_receipt_paths else None
    gate = validate_review_mesh_quorum_path(
        root=root,
        phase="final-audit",
        config=config,
        receipt_path=receipt_path,
    )
    require_review_mesh_quorum_gate_pass(gate)
    return gate if gate.get("required") or receipt_path else None


def _validate_completion_check(state: dict[str, Any], root: Path) -> dict[str, Any] | None:
    check = state.get("completionCheck")
    if check is None:
        return None
    if not isinstance(check, dict):
        raise LifecycleError("invalid-workflow-state", "completionCheck in workflow state must be an object")
    check_validation = validate_completion_check(check)
    receipt_rel = check_validation["receiptPath"]
    receipt_path = root / receipt_rel
    if not receipt_path.is_file():
        raise LifecycleError(
            "completion-check-receipt-missing",
            "declared completion check requires a receipt before finalization",
            {"path": receipt_rel},
        )
    receipt = read_json_object(receipt_path, label="completion check receipt")
    validation = validate_completion_check_receipt(receipt, check=check, state=state)
    identity = artifact_identity(root, receipt_rel, receipt)
    return {"check": check_validation, "receipt": identity, "validation": validation}


def _validate_goal_record(state: dict[str, Any], root: Path, goal_record_path: str | None) -> dict[str, Any] | None:
    if goal_record_path is None:
        return None
    goal_record_rel = normalize_repo_path(goal_record_path, label="goal record")
    record = read_json_object(root / goal_record_rel, label="goal record")
    validation = validate_goal_record(record, state=state, require_current=True)
    identity = artifact_identity(root, goal_record_rel, record)
    return {"record": identity, "validation": validation}


def _validate_follow_up_register(
    state: dict[str, Any], root: Path, follow_up_register_path: str | None
) -> dict[str, Any] | None:
    path = follow_up_register_path
    existing = state.get("followUpRegister")
    if path is None and isinstance(existing, dict) and existing.get("path"):
        path = existing["path"]
    if path is None:
        return None
    register_rel = normalize_repo_path(path, label="follow-up register")
    register = read_json_object(root / register_rel, label="follow-up register")
    validation = validate_followup_register(register, state=state, root=root)
    if validation["finalizationBlockers"]:
        raise LifecycleError(
            "follow-up-finalization-blocked",
            "open follow-up items contradict current finalization",
            {"items": validation["finalizationBlockers"]},
        )
    identity = artifact_identity(root, register_rel, register)
    return {"register": identity, "validation": validation}


def _validate_completion_gate(
    state: dict[str, Any],
    root: Path,
    final_audit: dict[str, Any],
    *,
    completion_gate_receipt_path: str | None,
    follow_up_register_path: str | None,
) -> dict[str, Any] | None:
    path = completion_gate_receipt_path
    existing = state.get("completionGate")
    if path is None and isinstance(existing, dict) and existing.get("receiptPath"):
        path = existing["receiptPath"]
    if path is None:
        return None
    receipt_rel = normalize_repo_path(path, label="completion gate receipt")
    receipt = read_json_object(root / receipt_rel, label="completion gate receipt")
    follow_up_register = _read_follow_up_register_payload(state, root, follow_up_register_path)
    validation = require_completion_gate_finalization(
        receipt,
        state=state,
        final_audit=final_audit,
        follow_up_register=follow_up_register,
    )
    identity = artifact_identity(root, receipt_rel, receipt)
    return {"receipt": identity, "validation": validation}


def _read_follow_up_register_payload(
    state: dict[str, Any],
    root: Path,
    follow_up_register_path: str | None,
) -> dict[str, Any] | None:
    path = follow_up_register_path
    existing = state.get("followUpRegister")
    if path is None and isinstance(existing, dict) and existing.get("path"):
        path = existing["path"]
    if path is None:
        return None
    register_rel = normalize_repo_path(path, label="follow-up register")
    return read_json_object(root / register_rel, label="follow-up register")


def _validate_proof_integrity(
    state: dict[str, Any],
    root: Path,
    final_audit: dict[str, Any],
    proof_integrity_path: str | None,
) -> dict[str, Any] | None:
    if proof_integrity_path is None:
        validate_final_proof_integrity(state=state, final_audit=final_audit, receipt=None)
        return None
    receipt_rel = normalize_repo_path(proof_integrity_path, label="proof integrity receipt")
    receipt = read_json_object(root / receipt_rel, label="proof integrity receipt")
    validation = validate_final_proof_integrity(state=state, final_audit=final_audit, receipt=receipt)
    identity = artifact_identity(root, receipt_rel, receipt)
    return {"receipt": identity, "validation": validation}


def _validate_final_implementation_audit(
    state_path: Path,
    state: dict[str, Any],
    root: Path,
    *,
    final_implementation_audit_path: str | None,
) -> dict[str, Any] | None:
    if final_implementation_audit_path is None:
        if final_implementation_audit_required(state_path, state):
            raise LifecycleError(
                "final-implementation-audit-required",
                "final implementation audit is required before workflow finalization",
            )
        return None
    rel = normalize_repo_path(final_implementation_audit_path, label="final implementation audit")
    audit = read_json_object(root / rel, label="final implementation audit")
    validation = validate_final_implementation_audit(audit, state=state)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "final-implementation-audit-invalid",
            "final implementation audit validation failed",
            {"validation": validation},
        )
    require_final_implementation_audit_pass(audit)
    identity = artifact_identity(root, rel, audit)
    return {"audit": identity, "validation": validation}


def _proof_body(
    state: dict[str, Any],
    *,
    operation_id: str,
    final_audit: dict[str, Any],
    completion_check_receipt: dict[str, Any] | None,
    completion_gate: dict[str, Any] | None,
    goal_record: dict[str, Any] | None,
    follow_up_register: dict[str, Any] | None,
    proof_integrity: dict[str, Any] | None,
    final_implementation_audit: dict[str, Any] | None,
    finalization_gate_receipts: list[dict[str, Any]],
    review_mesh_quorum: dict[str, Any] | None,
    lifecycle_control_stop: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    accepted = [
        {
            "id": task.get("id"),
            "attempt": task.get("attempt"),
            "review": task.get("review"),
        }
        for task in state.get("tasks", [])
        if task.get("status") == "ACCEPTED"
    ]
    body = {
        "schemaVersion": "agent-run-final-proof.v1",
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "operationId": operation_id,
        "stateRevisionBeforeFinalization": state.get("stateRevision"),
        "semanticStatus": "READY_FOR_FINALIZATION",
        "productionPromotionClaimed": False,
        "acceptedTasks": accepted,
        "finalAudit": final_audit,
        "completionCheck": completion_check_receipt,
        "completionGate": completion_gate,
        "goalRecord": goal_record,
        "followUpRegister": follow_up_register,
        "proofIntegrity": proof_integrity,
        "finalImplementationAudit": final_implementation_audit,
        "finalizationGateReceipts": finalization_gate_receipts,
        "reviewMeshQuorum": review_mesh_quorum,
        "lifecycleControlStop": lifecycle_control_stop,
        "reason": reason,
        "createdAt": now_iso(),
    }
    return {**body, "bodyDigest": canonical_digest(body)}
