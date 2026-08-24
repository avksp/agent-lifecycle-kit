"""Execution authorization transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_authorization_schemas import (
    validate_workflow_authorization_receipt,
)
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import now_iso


def authorize_execution(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    receipt_path: str,
    reason: str,
) -> dict[str, Any]:
    """Consume one unexpired authorization receipt and move a run to READY."""

    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state.get("phase") != "AWAITING_AUTHORIZATION":
        raise LifecycleError("invalid-phase", "execution authorization requires AWAITING_AUTHORIZATION phase")
    if state.get("startMode") == "plan-only":
        raise LifecycleError("plan-only-not-executable", "plan-only workflow cannot receive execution authorization")
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    authorization = state.get("authorization")
    if not isinstance(authorization, dict) or authorization.get("required") is not True:
        raise LifecycleError("authorization-not-required", "workflow does not require execution authorization")
    root = package_root(state_path, state)
    receipt_rel = normalize_repo_path(receipt_path, label="authorization receipt")
    receipt = read_json_object(root / receipt_rel, label="authorization receipt")
    validation = validate_workflow_authorization_receipt(receipt, state=state)
    identity = artifact_identity(root, receipt_rel, receipt)
    state["authorization"] = {
        "required": False,
        "granted": True,
        "grantedBy": validation["authorizedBy"],
        "grantedAt": now_iso(),
        "expiresAt": validation["expiresAt"],
        "authorizationReceipt": identity,
    }
    state["phase"] = "READY"
    state["lastReason"] = reason
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="execution-authorized",
        payload={"authorizationReceipt": identity, "reason": reason},
    )
    return status(state_path)


__all__ = ["authorize_execution"]
