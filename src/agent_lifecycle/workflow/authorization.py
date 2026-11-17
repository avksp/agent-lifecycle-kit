"""Execution authorization transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.operator_signature import operator_observed_at, verify_operator_subject
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_authorization_schemas import (
    authorization_renewal_bindings,
    validate_workflow_authorization_receipt,
    validate_workflow_authorization_renewal_receipt,
)
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root
from agent_lifecycle.workflow.events import event_log_path, read_events
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import now_iso
from agent_lifecycle.workflow.transactions import workflow_transaction


@workflow_transaction
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

    state = load_for_update(
        state_path, operation_id=operation_id, expected_revision=expected_revision, authorization_required=False
    )
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
    operator_signature = verify_operator_subject(
        state,
        "authorize",
        root=root,
        signature_path=receipt_rel + ".operator-signature.json",
        observed_at=operator_observed_at(),
        operation_id=operation_id,
        subject=receipt,
    )
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
    if operator_signature is not None:
        state["authorization"]["operatorSignature"] = operator_signature
    state["lastReason"] = reason
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="execution-authorized",
        payload={
            "authorizationReceipt": identity,
            **({"operatorSignature": operator_signature} if operator_signature is not None else {}),
            "reason": reason,
        },
    )
    return status(state_path)


@workflow_transaction
def renew_execution_authorization(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    source_revision: str,
    receipt_path: str,
    reason: str,
) -> dict[str, Any]:
    """Consume a fresh same-run grant; preserve the existing phase and subjects."""
    state = load_for_update(
        state_path, operation_id=operation_id, expected_revision=expected_revision, authorization_required=False
    )
    if state.get("sourceRevision") != source_revision:
        raise LifecycleError("source-revision-mismatch", "source revision mismatch")
    root = package_root(state_path, state)
    authorization = state.get("authorization")
    if not isinstance(authorization, dict):
        raise LifecycleError("invalid-authorization-renewal", "Renewal requires a consumed grant")
    previous_identity = authorization.get("authorizationReceipt")
    if not isinstance(previous_identity, dict) or not isinstance(previous_identity.get("path"), str):
        raise LifecycleError("invalid-authorization-renewal", "Renewal requires an immutable consumed receipt")
    previous_rel = normalize_repo_path(previous_identity["path"], label="previous authorization receipt")
    previous = read_json_object(root / previous_rel, label="previous authorization receipt")
    if artifact_identity(root, previous_rel, previous) != previous_identity:
        raise LifecycleError("invalid-authorization-renewal", "Consumed receipt identity differs")
    receipt_rel = normalize_repo_path(receipt_path, label="authorization renewal receipt")
    if receipt_rel == previous_rel:
        raise LifecycleError("authorization-receipt-replayed", "Renewal must use a new immutable receipt")
    receipt = read_json_object(root / receipt_rel, label="authorization renewal receipt")
    used_ids = {
        event["payload"][name]
        for event in read_events(event_log_path(state_path, state))
        if event.get("eventType") == "execution-authorization-renewed"
        for name in ("previousAuthorizationId", "authorizationId")
        if isinstance(event.get("payload"), dict) and isinstance(event["payload"].get(name), str)
    }
    validation = validate_workflow_authorization_renewal_receipt(
        receipt, state=state, previous_receipt=previous, used_authorization_ids=used_ids
    )
    operator_signature = verify_operator_subject(
        state,
        "authorize",
        root=root,
        signature_path=receipt_rel + ".operator-signature.json",
        observed_at=operator_observed_at(),
        operation_id=operation_id,
        subject=receipt,
    )
    identity = artifact_identity(root, receipt_rel, receipt)
    bindings = authorization_renewal_bindings(state)
    state["authorization"] = {
        **authorization,
        "grantedBy": validation["authorizedBy"],
        "grantedAt": now_iso(),
        "expiresAt": validation["expiresAt"],
        "authorizationReceipt": identity,
    }
    if operator_signature is not None:
        state["authorization"]["operatorSignature"] = operator_signature
    state["lastReason"] = reason
    commit_state(
        state_path,
        state,
        operation_id=operation_id,
        event_type="execution-authorization-renewed",
        payload={
            **bindings,
            "previousAuthorization": authorization,
            **({"operatorSignature": operator_signature} if operator_signature is not None else {}),
            "previousAuthorizationId": previous["authorizationId"],
            "authorizationId": receipt["authorizationId"],
            "authorizationReceipt": identity,
            "expiresAt": validation["expiresAt"],
            "reason": reason,
        },
    )
    return status(state_path)


__all__ = ["authorize_execution", "renew_execution_authorization"]
