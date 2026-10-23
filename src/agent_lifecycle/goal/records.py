"""Goal record validation and compact continuation snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.context.profiles import resolve_window, validate_context_profile
from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.goal_validation import (
    GOAL_STATUSES,
)
from agent_lifecycle.contracts.goal_validation import (
    LINEAGE_KEYS as LINEAGE_KEYS,
)
from agent_lifecycle.contracts.goal_validation import (
    validate_goal_record as validate_goal_record,
)


def build_objective_snapshot(
    record: dict[str, Any],
    state: dict[str, Any],
    *,
    profile: dict[str, Any] | None = None,
    window: str | None = None,
) -> dict[str, Any]:
    """Build a compact continuation summary from a current goal record."""

    from agent_lifecycle.workflow.query import next_action

    validation = validate_goal_record(record, state=state, require_current=True)
    body: dict[str, Any] = {
        "schemaVersion": "agent-objective-snapshot.v1",
        "status": "PASS",
        "goal": {
            "goalId": validation["goalId"],
            "goalStatus": validation["goalStatus"],
            "goalDigest": validation["goalDigest"],
            "userIntent": record.get("userIntent"),
            "userIntentDigest": canonical_digest({"userIntent": record.get("userIntent")}),
            "ownerOutcome": record.get("ownerOutcome"),
            "constraints": record.get("constraints", []),
            "constraintsDigest": canonical_digest({"constraints": record.get("constraints", [])}),
            "evidenceIds": validation["evidenceIds"],
        },
        "lifecycle": {
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "planRevision": state.get("planRevision"),
            "planDigest": state.get("planDigest"),
            "sourceRevision": state.get("sourceRevision"),
            "phase": state.get("phase"),
            "stateRevision": state.get("stateRevision"),
            "nextAction": next_action(state),
        },
        "completionCheck": validation["completionCheck"],
    }
    token_estimate = estimate_tokens(body)
    target: dict[str, Any] | None = None
    if profile is not None:
        validate_context_profile(profile)
        selected = resolve_window(profile, window)
        limit = selected["limits"]["maxStateSummaryTokens"]
        target = {"window": selected["name"], "limit": limit}
        if token_estimate > limit:
            raise LifecycleError(
                "goal-summary-overflow",
                "objective snapshot exceeds compact context state-summary limit",
                {"estimatedTokens": token_estimate, "limit": limit, "window": selected["name"]},
            )
    body["estimatedTokens"] = token_estimate
    if target is not None:
        body["target"] = target
    return {**body, "snapshotDigest": canonical_digest(body)}


def update_goal_record(
    record: dict[str, Any],
    state: dict[str, Any],
    *,
    status: str | None = None,
    reason: str,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Return a new goal record bound to the current workflow state."""

    previous = validate_goal_record(record, state=state, require_current=False)
    new_status = status or str(record.get("status"))
    if new_status not in GOAL_STATUSES:
        raise LifecycleError("invalid-goal-record", "goal status is unsupported")
    added_evidence = _string_list(evidence_ids or [], label="evidenceIds", allow_empty=True)
    merged_evidence = sorted(set(previous["evidenceIds"]) | set(added_evidence))
    updated = {
        **record,
        "status": new_status,
        "lineage": _lineage_from_state(state),
        "completionCheck": _state_completion_check(state),
        "evidenceIds": merged_evidence,
        "updatedAt": _now_iso(),
    }
    if updated["completionCheck"] is None:
        updated.pop("completionCheck", None)
    history = list(record.get("history", [])) if isinstance(record.get("history"), list) else []
    history.append(
        {
            "previousGoalDigest": previous["goalDigest"],
            "previousStateRevision": previous["stateRevision"],
            "reason": reason,
            "updatedAt": updated["updatedAt"],
        }
    )
    updated["history"] = history
    validate_goal_record(updated, state=state, require_current=True)
    return updated


def _lineage_from_state(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "stateRevision": state.get("stateRevision"),
    }


def _state_completion_check(state: dict[str, Any]) -> dict[str, Any] | None:
    validation = state.get("completionCheckValidation")
    if not isinstance(validation, dict):
        return None
    check_id = validation.get("checkId")
    check_digest = validation.get("checkDigest")
    if not isinstance(check_id, str) or not isinstance(check_digest, str):
        return None
    return {"checkId": check_id, "checkDigest": check_digest}


def _string_list(value: Any, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-goal-record", f"{label} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise LifecycleError("invalid-goal-record", f"{label} must not be empty")
    return list(value)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
