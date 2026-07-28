"""Budget decision receipt construction helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest


def build_budget_decision_receipt(
    *,
    state: dict[str, Any],
    task: dict[str, Any],
    route_decision: dict[str, Any],
    usage_receipt: dict[str, Any],
    usage_identity: dict[str, Any],
    policy: dict[str, Any],
    selected_action: str,
    validation: dict[str, Any],
    expected_workflow_revision: int,
    operator_identity_hash: str | None = None,
    prior_route_digest: str | None = None,
    usage_receipt_digest: str | None = None,
    policy_digest: str | None = None,
    overrun_reason: str | None = None,
    next_route_decision: dict[str, Any] | None = None,
    next_route_identity: dict[str, Any] | None = None,
    split_packet_identity: dict[str, Any] | None = None,
    cap_deltas: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt = {
        "schemaVersion": "agent-lifecycle-budget-decision-receipt.v1",
        "runId": state["runId"],
        "packageId": state["packageId"],
        "taskId": task["id"],
        "attemptId": f"{task['id']}:attempt-{task.get('attempt')}",
        "attempt": task.get("attempt"),
        "sourceRevision": state["sourceRevision"],
        "priorRouteDecisionDigest": prior_route_digest or route_digest(route_decision),
        "usageReceiptDigest": usage_receipt_digest or canonical_digest(usage_receipt),
        "usageReceipt": usage_identity,
        "overrunReason": overrun_reason or overrun_reason_from_validation(validation),
        "decisionMode": policy["mode"],
        "selectedAction": selected_action,
        "allowedActions": list(policy["allowedActions"]),
        "operatorIdentityHash": operator_identity_hash,
        "policyDigest": policy_digest or canonical_digest(policy),
        "nextRouteDecisionDigest": route_digest(next_route_decision) if next_route_decision is not None else None,
        "splitPacketIdentity": split_packet_identity,
        "capDeltas": dict(cap_deltas or {}),
        "resumePhase": "RUNNING",
        "expectedWorkflowRevision": expected_workflow_revision,
        "productionPromotionClaimed": False,
    }
    if next_route_identity is not None:
        receipt["nextRouteDecision"] = next_route_identity
    return receipt


def route_digest(route_decision: dict[str, Any]) -> str:
    return str(route_decision.get("decisionDigest") or canonical_digest(route_decision))


def overrun_reason_from_validation(validation: dict[str, Any]) -> str:
    failed = [
        str(check.get("id"))
        for check in validation.get("checks", [])
        if isinstance(check, dict) and check.get("status") == "FAIL"
    ]
    return ",".join(failed) or "budget-overrun"
