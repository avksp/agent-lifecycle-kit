"""Terminal workflow finalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.goal import validate_goal_record
from agent_lifecycle.specification import (
    validate_completion_check,
    validate_completion_check_receipt,
    validate_completion_signal,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.gates import record_gate_receipts, validate_controller_gates
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import now_iso


def finalize_run(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    final_audit_path: str,
    proof_path: str,
    goal_record_path: str | None = None,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state.get("phase") != "FINAL_AUDIT":
        raise LifecycleError("invalid-phase", "run finalization requires FINAL_AUDIT phase")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    missing = _missing_required_acceptance(state)
    if missing:
        raise LifecycleError("finalization-precondition-failed", "required tasks are not accepted", {"tasks": missing})
    root = package_root(state_path, state)
    final_audit_rel = normalize_repo_path(final_audit_path)
    final_audit = read_json_object(root / final_audit_rel, label="final audit")
    final_audit_identity = artifact_identity(root, final_audit_rel, final_audit)
    _validate_final_audit(state, final_audit)
    completion_check_receipt = _validate_completion_check(state, root)
    goal_record = _validate_goal_record(state, root, goal_record_path)
    finalization_gate_receipts = _validate_finalization_gates(
        state_path,
        state,
        operation_id=operation_id,
    )
    proof_rel = normalize_repo_path(proof_path)
    proof = _proof_body(
        state,
        operation_id=operation_id,
        final_audit=final_audit_identity,
        completion_check_receipt=completion_check_receipt,
        goal_record=goal_record,
        finalization_gate_receipts=finalization_gate_receipts,
        reason=reason,
    )
    write_json_create(root / proof_rel, proof)
    identity = artifact_identity(root, proof_rel, proof)
    state["finalProof"] = {**identity, "semanticStatus": proof["semanticStatus"]}
    state["finalAudit"] = final_audit_identity
    if completion_check_receipt is not None:
        state["completionCheckReceipt"] = completion_check_receipt["receipt"]
    if goal_record is not None:
        state["goalRecord"] = goal_record["record"]
    state["phase"] = "COMPLETE"
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="run-finalized",
        payload={
            "finalAudit": final_audit_identity,
            "completionCheckReceipt": completion_check_receipt,
            "goalRecord": goal_record,
            "finalizationGateReceipts": finalization_gate_receipts,
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
    completion_signal_validation = validate_completion_signal(final_audit.get("completionSignal"), state=state)
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


def _proof_body(
    state: dict[str, Any],
    *,
    operation_id: str,
    final_audit: dict[str, Any],
    completion_check_receipt: dict[str, Any] | None,
    goal_record: dict[str, Any] | None,
    finalization_gate_receipts: list[dict[str, Any]],
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
        "goalRecord": goal_record,
        "finalizationGateReceipts": finalization_gate_receipts,
        "reason": reason,
        "createdAt": now_iso(),
    }
    return {**body, "bodyDigest": canonical_digest(body)}
