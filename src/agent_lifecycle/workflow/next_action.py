"""Typed next-action projection for the managed lifecycle runner."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.workflow.query import next_action as workflow_next_action
from agent_lifecycle.workflow.transition_contract import action_requires_host, action_requires_state_mutation

MODEL_CALLS_STARTED = False

_INPUT_OPTIONS = {
    "taskId": "--task",
    "findingIds": "--finding-id",
    "taskIds": "--task-id",
    "reviewMeshQuorum": "--review-mesh-quorum",
    "executionStrategy": "--strategy",
    "strategyRequestedRisk": "--strategy-risk",
    "strategyRiskPolicy": "--strategy-risk-policy",
    "strategyRoutingProfile": "--strategy-routing-profile",
    "strategyBaselineProfile": "--strategy-baseline-profile",
    "strategyHostProfile": "--strategy-host-model-profile",
    "strategyDescriptor": "--strategy-descriptor",
    "strategyCapabilityManifest": "--strategy-capability-manifest",
    "strategyProjectProfile": "--strategy-project-profile",
}


def build_local_next_action(
    managed: dict[str, Any],
    action: dict[str, Any],
    *,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path | None,
    reason: str,
    required_inputs: list[dict[str, Any]],
    status: str,
) -> dict[str, Any]:
    """Build argument tokens for the existing guarded local continuation route."""
    argv: list[str] | None = None
    if status == "READY" and not required_inputs:
        argv = [
            "agent-lifecycle",
            "workflow",
            "continue",
            "--state",
            str(state_path),
            "--manifest",
            str(manifest_path),
            "--operation-id",
            action["operationId"],
            "--expected-revision",
            str(action["stateRevision"]),
            "--source-revision",
            action["sourceRevision"],
            "--reason",
            reason,
            "--apply",
            "--projected-state-revision",
            str(action["stateRevision"]),
            "--projected-action-digest",
            action["actionDigest"],
        ]
        if lock_path is not None:
            argv.extend(["--lock", str(lock_path)])
        inputs = dict(action["suppliedInputs"])
        for name, value in sorted(inputs.items()):
            option = _INPUT_OPTIONS.get(name) or "--" + re.sub(r"([A-Z])", r"-\1", name).lower()
            for item in value if isinstance(value, list) else [value]:
                argv.extend([option, item])
    body = {
        **{key: value for key, value in managed.items() if key != "actionDigest"},
        "schemaVersion": "agent-workflow-local-next-action.v1",
        "status": status,
        "argv": argv,
        "shell": False,
        "requiredInputs": required_inputs,
        "parentActionDigest": managed["actionDigest"],
        "continuationActionDigest": action["actionDigest"],
        "productionPromotionClaimed": False,
    }
    return {**body, "actionDigest": canonical_digest(body)}


def build_managed_next_action(state: dict[str, Any]) -> dict[str, Any]:
    """Return a host-owned next action without mutating workflow state."""

    projected = workflow_next_action(state)
    blockers = _blockers_for_projected_action(projected)
    action = {
        "schemaVersion": "agent-managed-lifecycle-next-action.v1",
        "type": projected.get("type", "continue-phase"),
        "status": "BLOCKED" if blockers else "READY",
        "hostActionRequired": action_requires_host(projected.get("type")),
        "modelCallsStarted": MODEL_CALLS_STARTED,
        "stateMutationRequired": action_requires_state_mutation(projected.get("type")),
        "projectedAction": projected,
        "taskIds": list(projected.get("taskIds", [])) if isinstance(projected.get("taskIds"), list) else [],
        "blockers": blockers,
    }
    return {**action, "actionDigest": canonical_digest(action)}


def _blockers_for_projected_action(projected: dict[str, Any]) -> list[dict[str, Any]]:
    action_type = projected.get("type")
    if action_type == "request-human-decision":
        blocker = projected.get("blocker")
        if isinstance(blocker, dict):
            return [
                {
                    "code": str(blocker.get("code") or "workflow-blocked"),
                    "message": str(blocker.get("reason") or "workflow is blocked"),
                }
            ]
        return [{"code": "workflow-blocked", "message": "workflow is blocked"}]
    if action_type == "record-budget-decision":
        blocker = projected.get("blocker")
        if isinstance(blocker, dict):
            return [
                {
                    "code": str(blocker.get("code") or "budget-decision-required"),
                    "message": str(blocker.get("reason") or "budget decision is required"),
                }
            ]
        return [{"code": "budget-decision-required", "message": "budget decision is required"}]
    if action_type == "record-external-action-receipt":
        external_action = projected.get("externalAction")
        action_id = external_action.get("actionId") if isinstance(external_action, dict) else None
        return [
            {
                "code": "external-action-receipt-required",
                "message": "external action receipt is required",
                "actionId": action_id,
            }
        ]
    if action_type == "request-execution-authorization":
        return [{"code": "execution-authorization-required", "message": "execution authorization is required"}]
    return []
