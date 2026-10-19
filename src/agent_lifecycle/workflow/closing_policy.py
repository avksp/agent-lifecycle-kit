"""Pure closing-only scope classification; never an authority or model permit."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.workflow_state_schemas import _closing_instant, validate_closing_context


def evaluate_closing_action(context: dict[str, Any], action: str, now: str, subject: dict[str, Any]) -> dict[str, Any]:
    """Classify supplied data before independent native authority and gate checks."""
    validated = validate_closing_context(context)
    current = _closing_instant(now, "now")
    if type(subject) is not dict or set(subject) != {
        "runId",
        "packageId",
        "planDigest",
        "sourceRevision",
        "stateRevision",
    }:
        raise LifecycleError("closing-context-invalid", "Closing subject is incomplete")
    if type(subject["stateRevision"]) is not int or subject["stateRevision"] < validated["activationRevision"]:
        raise LifecycleError("closing-context-invalid", "Closing subject revision is invalid")
    if any(validated[key] != subject[key] for key in ("runId", "packageId", "planDigest", "sourceRevision")):
        raise LifecycleError("closing-context-invalid", "Closing subject differs from the active window")
    matched = type(action) is str and action in validated["allowedActions"]
    in_window = (
        _closing_instant(validated["validFrom"], "validFrom")
        <= current
        < _closing_instant(validated["expiresAt"], "expiresAt")
    )
    return {
        "schemaVersion": "agent-closing-action-classification.v1",
        "disposition": "DATA_CANDIDATE" if matched and in_window else "REFUSED",
        "reason": "WITHIN_DECLARED_SCOPE"
        if matched and in_window
        else ("ACTION_OUT_OF_SCOPE" if not matched else "WINDOW_NOT_ACTIVE"),
        "closingWindowId": validated["closingWindowId"],
        "contextDigest": validated["contextDigest"],
        "ownerAuthenticated": False,
        "nonceConsumed": False,
        "nativeStateChanged": False,
        "dispatchAuthorized": False,
        "financialAdmission": False,
        "requiresCurrentAuthorityResourceDeadlineAndEvidenceGates": True,
    }


def require_native_closing_action(state: dict[str, Any], action: str, now: str) -> None:
    """Keep active closing finalization inert until the WS02 native authority join."""
    if "closingWindow" not in state:
        return
    subject = {key: state.get(key) for key in ("runId", "packageId", "planDigest", "sourceRevision", "stateRevision")}
    classification = evaluate_closing_action(state["closingWindow"], action, now, subject)
    if classification["disposition"] != "DATA_CANDIDATE":
        raise LifecycleError("closing-action-refused", "Closing-only action is outside the validated data scope")
    raise LifecycleError(
        "closing-native-authority-required",
        "Closing-only finalization requires the native authority, resource and deadline transaction",
    )


__all__ = ["evaluate_closing_action", "require_native_closing_action"]
