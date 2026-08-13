"""The single lifecycle seam for optional milestone context checkpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.context.checkpoint_store import write_context_checkpoint
from agent_lifecycle.context.checkpoints import build_context_checkpoint
from agent_lifecycle.host_protocol.context_events import build_context_checkpoint_event

MAX_CHECKPOINTS_PER_RUN = 64
DEFAULT_CHECKPOINT_POLICY: dict[str, Any] = {
    "enabled": False,
    "required": False,
    "milestoneEvents": [],
    "maxCheckpointsPerRun": MAX_CHECKPOINTS_PER_RUN,
    "retentionPolicy": "retain-latest-with-explicit-delete",
    "checkpointRoot": ".alk/context/checkpoints",
    "targetContinuationTokens": 2048,
}


def normalize_context_checkpoint_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize the reviewed plan's checkpoint policy into runtime state."""

    if policy is None:
        return dict(DEFAULT_CHECKPOINT_POLICY)
    if not isinstance(policy, dict):
        raise LifecycleError("context-checkpoint-policy-invalid", "contextCheckpointPolicy must be an object")
    events = policy.get("milestoneEvents", policy.get("events", []))
    if not isinstance(events, list) or len(events) > 16 or any(not isinstance(item, str) or not item for item in events):
        raise LifecycleError("context-checkpoint-policy-events-invalid", "milestoneEvents must be a bounded string array")
    root = policy.get("checkpointRoot", DEFAULT_CHECKPOINT_POLICY["checkpointRoot"])
    try:
        root = normalize_repo_path(root, label="contextCheckpointPolicy.checkpointRoot")
    except LifecycleError:
        raise
    if not root.startswith(".alk/"):
        raise LifecycleError("context-checkpoint-policy-root-invalid", "checkpointRoot must remain under .alk")
    limit = policy.get("maxCheckpointsPerRun", MAX_CHECKPOINTS_PER_RUN)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_CHECKPOINTS_PER_RUN:
        raise LifecycleError("context-checkpoint-policy-retention-invalid", "maxCheckpointsPerRun must be between 1 and 64")
    target = policy.get("targetContinuationTokens", 2048)
    if not isinstance(target, int) or isinstance(target, bool) or target < 1 or target > 8192:
        raise LifecycleError("context-checkpoint-policy-budget-invalid", "targetContinuationTokens is outside the supported range")
    enabled = policy.get("enabled", bool(events))
    required = policy.get("required", False)
    if not isinstance(enabled, bool) or not isinstance(required, bool):
        raise LifecycleError("context-checkpoint-policy-flags-invalid", "enabled and required must be booleans")
    if required and not enabled:
        raise LifecycleError("context-checkpoint-policy-required-disabled", "required checkpoint capture needs an enabled policy")
    retention = policy.get("retentionPolicy", DEFAULT_CHECKPOINT_POLICY["retentionPolicy"])
    if retention != DEFAULT_CHECKPOINT_POLICY["retentionPolicy"]:
        raise LifecycleError("context-checkpoint-policy-retention-policy-invalid", "unsupported checkpoint retention policy")
    return {
        "enabled": enabled,
        "required": required,
        "milestoneEvents": sorted(set(events)),
        "maxCheckpointsPerRun": limit,
        "retentionPolicy": retention,
        "checkpointRoot": root,
        "targetContinuationTokens": target,
    }


def invoke_checkpoint_gate(
    *,
    state_path: Path,
    state: dict[str, Any],
    operation_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Capture one declared milestone before the state commit.

    Required capture raises before the caller mutates or persists workflow
    state. Optional capture returns a non-blocking receipt.
    """

    policy = normalize_context_checkpoint_policy(state.get("contextCheckpointPolicy"))
    base = {
        "schemaVersion": "agent-context-checkpoint-gate-receipt.v1",
        "eventType": event_type,
        "operationId": operation_id,
        "required": policy["required"],
        "attempted": False,
        "status": "SKIPPED",
        "idempotencyKey": canonical_digest(
            {"operationId": operation_id, "stateRevision": state.get("stateRevision"), "eventType": event_type}
        ),
        "checkpointPath": None,
        "checkpointDigest": None,
        "checkpointEvent": None,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    if not policy["enabled"] or event_type not in policy["milestoneEvents"]:
        return base
    base["attempted"] = True
    next_revision = int(state.get("stateRevision", 0)) + 1
    checkpoint_id = f"ctx-{base['idempotencyKey'][:24]}"
    summary = _summary_from_transition(state, event_type=event_type, payload=payload)
    try:
        checkpoint = build_context_checkpoint(
            session_id=str(state.get("sessionId") or state.get("runId") or "workflow-session"),
            run_id=str(state["runId"]),
            adapter_id=str(state.get("adapterId") or "alk-managed"),
            package_id=str(state["packageId"]),
            plan_revision=int(state["planRevision"]),
            plan_digest=str(state["planDigest"]),
            state_revision=next_revision,
            source_revision=str(state["sourceRevision"]),
            capture_mode="MILESTONE",
            reason=f"lifecycle milestone: {event_type}",
            summary=summary,
            referenced_artifacts=_referenced_artifacts(state),
            created_at=str(state.get("updatedAt") or "1970-01-01T00:00:00Z"),
            checkpoint_id=checkpoint_id,
            target_tokens=policy["targetContinuationTokens"],
        )
        root = _checkpoint_root(state_path, policy["checkpointRoot"])
        stored = write_context_checkpoint(
            checkpoint,
            root=root,
            max_checkpoints_per_run=policy["maxCheckpointsPerRun"],
        )
        event = build_context_checkpoint_event(
            event_type="context.checkpoint.created",
            session_id=checkpoint["sessionId"],
            run_id=checkpoint["runId"],
            operation_id=operation_id,
            state_revision=next_revision,
            capture_mode="MILESTONE",
            checkpoint_digest=checkpoint["checkpointDigest"],
            payload={"eventType": event_type, "idempotencyKey": base["idempotencyKey"]},
            recorded_at=checkpoint["createdAt"],
        )
        return {
            **base,
            "status": "PASS",
            "checkpointPath": stored["path"],
            "checkpointDigest": checkpoint["checkpointDigest"],
            "checkpointEvent": event,
        }
    except (LifecycleError, OSError) as exc:
        blocker = {"code": getattr(exc, "code", "context-checkpoint-write-failed"), "message": str(exc)}
        result = {**base, "status": "BLOCKED" if policy["required"] else "OPTIONAL_FAILURE", "blockers": [blocker]}
        if policy["required"]:
            raise LifecycleError(
                "required-context-checkpoint-failed",
                "required context checkpoint failed before workflow commit",
                {"gate": result},
            ) from exc
        return result


def _checkpoint_root(state_path: Path, relative_root: str) -> Path:
    resolved_state = state_path.resolve()
    project_root = None
    for candidate in (resolved_state.parent, *resolved_state.parents):
        if candidate.name == "work":
            project_root = candidate.parent
            break
    if project_root is None:
        project_root = resolved_state.parent
    root = (project_root / relative_root).resolve()
    if not root.is_relative_to(project_root / ".alk"):
        raise LifecycleError("context-checkpoint-root-escape", "checkpoint root escapes the project .alk directory")
    return root


def _summary_from_transition(state: dict[str, Any], *, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "latestUserIntent": state.get("latestUserIntent") or f"Continue lifecycle after {event_type}.",
        "activeDecisions": state.get("activeDecisions", []),
        "openBlockers": [state["blocker"]] if isinstance(state.get("blocker"), dict) else [],
        "changedFiles": state.get("changedFiles", []),
        "nextRequiredAction": state.get("nextRequiredAction") or event_type,
        "doNotDo": state.get("doNotDo", []),
        "milestone": {"eventType": event_type, "payloadDigest": canonical_digest(payload)},
    }
    return summary


def _referenced_artifacts(state: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in ("planDigest", "packetSet", "lastPlanReview"):
        value = state.get(key)
        if key == "planDigest" and isinstance(value, str):
            result.append({"kind": "plan", "digest": value})
        elif isinstance(value, dict) and isinstance(value.get("sha256"), str):
            result.append({"kind": key, "digest": value["sha256"]})
    return result
