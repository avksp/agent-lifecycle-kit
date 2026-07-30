"""Goal record validation and compact continuation snapshots."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_lifecycle.context.profiles import resolve_window, validate_context_profile
from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_digest

GOAL_STATUSES = {"ACTIVE", "BLOCKED", "READY_FOR_FINALIZATION", "COMPLETE"}
LINEAGE_KEYS = ("runId", "packageId", "planRevision", "planDigest", "sourceRevision")


def validate_goal_record(
    record: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    require_current: bool = False,
) -> dict[str, Any]:
    """Validate a goal record and optionally bind it to current workflow state."""

    if not isinstance(record, dict):
        raise LifecycleError("invalid-goal-record", "goal record must be an object")
    if record.get("schemaVersion") != "agent-goal-record.v1":
        raise LifecycleError("invalid-goal-record", "goal record schemaVersion is unsupported")
    goal_id = _required_string(record.get("goalId"), label="goalId")
    _required_string(record.get("userIntent"), label="userIntent")
    _required_string(record.get("ownerOutcome"), label="ownerOutcome")
    status = record.get("status")
    if status not in GOAL_STATUSES:
        raise LifecycleError("invalid-goal-record", "goal status is unsupported")
    constraints = _string_list(record.get("constraints"), label="constraints")
    evidence_ids = _string_list(record.get("evidenceIds"), label="evidenceIds", allow_empty=True)
    lineage = _lineage(record)
    completion_check = _completion_check(record.get("completionCheck"))
    if state is not None:
        _validate_state_binding(lineage, completion_check, state, require_current=require_current)
    return {
        "schemaVersion": "agent-goal-record-validation.v1",
        "status": "PASS",
        "goalId": goal_id,
        "goalStatus": status,
        "lineage": lineage,
        "stateRevision": lineage.get("stateRevision"),
        "constraintCount": len(constraints),
        "evidenceIds": evidence_ids,
        "completionCheck": completion_check,
        "goalDigest": canonical_digest(record),
    }


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
    history.append({
        "previousGoalDigest": previous["goalDigest"],
        "previousStateRevision": previous["stateRevision"],
        "reason": reason,
        "updatedAt": updated["updatedAt"],
    })
    updated["history"] = history
    validate_goal_record(updated, state=state, require_current=True)
    return updated


def _validate_state_binding(
    lineage: dict[str, Any],
    completion_check: dict[str, Any] | None,
    state: dict[str, Any],
    *,
    require_current: bool,
) -> None:
    for key in LINEAGE_KEYS:
        if lineage.get(key) != state.get(key):
            raise LifecycleError("goal-lineage-mismatch", f"goal record {key} mismatch")
    state_revision = lineage.get("stateRevision")
    if not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
        raise LifecycleError("invalid-goal-record", "goal lineage.stateRevision must be a positive integer")
    if require_current and state_revision != state.get("stateRevision"):
        raise LifecycleError(
            "goal-state-stale",
            "goal record is not bound to the current workflow state revision",
            {"goalStateRevision": state_revision, "stateRevision": state.get("stateRevision")},
        )
    expected_check = _state_completion_check(state)
    if expected_check != completion_check:
        raise LifecycleError("goal-completion-check-mismatch", "goal record completionCheck does not match workflow state")


def _lineage(record: dict[str, Any]) -> dict[str, Any]:
    lineage = record.get("lineage")
    if not isinstance(lineage, dict):
        raise LifecycleError("invalid-goal-record", "goal lineage is required")
    result = {key: lineage.get(key) for key in LINEAGE_KEYS}
    for key, value in result.items():
        if key == "planRevision":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise LifecycleError("invalid-goal-record", "goal lineage.planRevision must be a positive integer")
        elif not isinstance(value, str) or not value:
            raise LifecycleError("invalid-goal-record", f"goal lineage.{key} is required")
    state_revision = lineage.get("stateRevision")
    if not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
        raise LifecycleError("invalid-goal-record", "goal lineage.stateRevision must be a positive integer")
    result["stateRevision"] = state_revision
    return result


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


def _completion_check(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise LifecycleError("invalid-goal-record", "goal completionCheck must be an object")
    check_id = _required_string(value.get("checkId"), label="completionCheck.checkId")
    check_digest = _digest(value.get("checkDigest"), label="completionCheck.checkDigest")
    return {"checkId": check_id, "checkDigest": check_digest}


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-goal-record", f"{label} is required")
    return value


def _digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise LifecycleError("invalid-goal-record", f"{label} must be a 64-character digest")
    return value


def _string_list(value: Any, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-goal-record", f"{label} must be a list of non-empty strings")
    if not value and not allow_empty:
        raise LifecycleError("invalid-goal-record", f"{label} must not be empty")
    return list(value)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
