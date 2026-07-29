"""Run-level workflow transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import TERMINAL_PHASES


def block_run(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    blocker_code: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] in TERMINAL_PHASES:
        raise LifecycleError("terminal-run", "terminal workflow state cannot be blocked")
    previous = state["phase"]
    state["phase"] = "BLOCKED"
    state["blocker"] = {"code": blocker_code, "reason": reason, "resumePhase": previous}
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="run-blocked",
        payload={"previousPhase": previous, "blocker": state["blocker"]},
    )
    return status(state_path)


def resolve_blocker(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] != "BLOCKED":
        raise LifecycleError("invalid-phase", "only BLOCKED runs can be resolved")
    blocker = state.get("blocker")
    if not isinstance(blocker, dict):
        raise LifecycleError("invalid-workflow-state", "blocked run has no blocker")
    resume_phase = blocker.get("resumePhase")
    if not isinstance(resume_phase, str) or resume_phase in TERMINAL_PHASES:
        raise LifecycleError("invalid-workflow-state", "blocker resumePhase is invalid")
    previous = state["phase"]
    state["phase"] = resume_phase
    state["blocker"] = None
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="run-resolved",
        payload={"previousPhase": previous, "resumePhase": resume_phase, "reason": reason},
    )
    return status(state_path)


def pause_for_external_action(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    action_id: str,
    receipt_path: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] in TERMINAL_PHASES:
        raise LifecycleError("terminal-run", "terminal workflow state cannot wait for external action")
    if not action_id:
        raise LifecycleError("invalid-external-action", "action_id is required")
    previous = state["phase"]
    expected_receipt = normalize_repo_path(receipt_path, label="external action receipt")
    state["phase"] = "WAITING_FOR_EXTERNAL_ACTION"
    state["externalAction"] = {
        "actionId": action_id,
        "reason": reason,
        "resumePhase": previous,
        "expectedReceiptPath": expected_receipt,
    }
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="external-action-paused",
        payload={"previousPhase": previous, "externalAction": state["externalAction"]},
    )
    return status(state_path)


def resume_external_action(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    receipt_path: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] != "WAITING_FOR_EXTERNAL_ACTION":
        raise LifecycleError("invalid-phase", "external action resume requires WAITING_FOR_EXTERNAL_ACTION phase")
    external_action = state.get("externalAction")
    if not isinstance(external_action, dict):
        raise LifecycleError("invalid-workflow-state", "external action state is missing")
    receipt_rel = normalize_repo_path(receipt_path, label="external action receipt")
    expected_receipt = external_action.get("expectedReceiptPath")
    if isinstance(expected_receipt, str) and receipt_rel != expected_receipt:
        raise LifecycleError("external-action-receipt-mismatch", "external action receipt path mismatch")
    root = package_root(state_path, state)
    if not (root / receipt_rel).is_file():
        raise LifecycleError("external-action-receipt-missing", "external action receipt is missing")
    receipt = read_json_object(root / receipt_rel, label="external action receipt")
    _validate_external_action_receipt(state, external_action, receipt)
    identity = artifact_identity(root, receipt_rel, receipt)
    resume_phase = external_action.get("resumePhase")
    if not isinstance(resume_phase, str) or resume_phase in TERMINAL_PHASES:
        raise LifecycleError("invalid-workflow-state", "external action resumePhase is invalid")
    state["phase"] = resume_phase
    state["externalActionReceipt"] = identity
    state["externalAction"] = None
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="external-action-resumed",
        payload={"resumePhase": resume_phase, "receipt": identity, "reason": reason},
    )
    return status(state_path)


def _validate_external_action_receipt(
    state: dict[str, Any],
    external_action: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if receipt.get("schemaVersion") != "agent-external-action-receipt.v1":
        raise LifecycleError("invalid-external-action-receipt", "external action receipt schemaVersion is unsupported")
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "actionId": external_action.get("actionId"),
        "status": "PASS",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LifecycleError("external-action-receipt-lineage-mismatch", f"external action receipt {key} mismatch")
    evidence_ids = receipt.get("evidenceIds")
    if not isinstance(evidence_ids, list) or not evidence_ids or not all(isinstance(item, str) and item for item in evidence_ids):
        raise LifecycleError("invalid-external-action-receipt", "external action receipt evidenceIds are required")
