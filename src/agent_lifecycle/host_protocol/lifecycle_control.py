"""Host-bound helpers for optional adapter lifecycle control."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.contracts.lifecycle_control_schemas import (
    CONTROL_LEVELS,
    build_default_lifecycle_control_policy,
    build_lifecycle_control_attestation,
    build_lifecycle_control_decision,
    build_lifecycle_control_event,
    build_lifecycle_control_qualification_receipt,
    build_lifecycle_control_request,
    lifecycle_control_limits,
    resolve_lifecycle_control,
    validate_lifecycle_control_attestation,
    validate_lifecycle_control_decision,
    validate_lifecycle_control_event,
    validate_lifecycle_control_event_batch,
    validate_lifecycle_control_policy,
    validate_lifecycle_control_qualification_receipt,
    validate_lifecycle_control_request,
)

DEFAULT_LIFECYCLE_CONTROL_POLICY = Path("policy/adapter-lifecycle-control.json")


def load_lifecycle_control_policy(path: Path = DEFAULT_LIFECYCLE_CONTROL_POLICY) -> dict[str, Any]:
    """Load a JSON policy without inferring authority from its location."""

    policy = read_json_object(path, label="adapter lifecycle control policy")
    validation = validate_lifecycle_control_policy(policy)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "lifecycle-control-policy-invalid", "adapter lifecycle control policy is invalid", validation
        )
    return policy


def require_lifecycle_control_policy_pass(validation: dict[str, Any]) -> dict[str, Any]:
    """Raise a stable error when a control policy is invalid."""

    if validation.get("status") != "PASS":
        raise LifecycleError(
            "lifecycle-control-policy-invalid", "adapter lifecycle control policy validation failed", validation
        )
    return validation


def require_lifecycle_control_decision_pass(decision: dict[str, Any]) -> dict[str, Any]:
    """Require a structurally valid decision; callers still enforce BLOCKED."""

    validation = validate_lifecycle_control_decision(decision)
    if validation["status"] != "PASS":
        raise LifecycleError("lifecycle-control-decision-invalid", "lifecycle control decision is invalid", validation)
    return decision


def require_lifecycle_control_event_pass(event: dict[str, Any]) -> dict[str, Any]:
    """Require a structurally valid host event."""

    validation = validate_lifecycle_control_event(event)
    if validation["status"] != "PASS":
        raise LifecycleError("lifecycle-control-event-invalid", "lifecycle control event is invalid", validation)
    return event


def effective_control_level(policy: dict[str, Any], operation: str, *, requested_level: str | None = None) -> str:
    """Return the resolved level, never a level inferred from a prompt."""

    decision = resolve_lifecycle_control(policy, operation, requested_level=requested_level)
    return str(decision["effectiveLevel"])


def lifecycle_control_is_enforced(policy: dict[str, Any], operation: str) -> bool:
    """Return true only for a policy entry already supported and qualified."""

    decision = resolve_lifecycle_control(policy, operation, requested_level="ENFORCED")
    return decision["status"] == "PASS" and decision["effectiveLevel"] == "ENFORCED" and decision["qualified"] is True


def validate_lifecycle_control_request_with_policy(request: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Apply the validated policy limits while checking a control request."""

    return validate_lifecycle_control_request(request, policy_limits=lifecycle_control_limits(policy))


def validate_lifecycle_control_decision_with_policy(decision: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Apply the validated policy payload limit while checking a decision."""

    return validate_lifecycle_control_decision(decision, policy_limits=lifecycle_control_limits(policy))


def validate_lifecycle_control_event_with_policy(event: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Apply the validated policy limits while checking one control event."""

    return validate_lifecycle_control_event(event, policy_limits=lifecycle_control_limits(policy))


def validate_lifecycle_control_event_batch_with_policy(
    events: list[dict[str, Any]], policy: dict[str, Any]
) -> dict[str, Any]:
    """Apply the validated policy limits while checking an event batch."""

    return validate_lifecycle_control_event_batch(events, policy_limits=lifecycle_control_limits(policy))


def validate_lifecycle_control_attestation_with_policy(
    attestation: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Apply policy nonce and freshness limits while checking an attestation."""

    return validate_lifecycle_control_attestation(attestation, policy_limits=lifecycle_control_limits(policy))


def validate_lifecycle_control_qualification_with_policy(
    receipt: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Apply the validated policy payload limit while checking qualification evidence."""

    return validate_lifecycle_control_qualification_receipt(receipt, policy_limits=lifecycle_control_limits(policy))


__all__ = [
    "CONTROL_LEVELS",
    "DEFAULT_LIFECYCLE_CONTROL_POLICY",
    "build_default_lifecycle_control_policy",
    "build_lifecycle_control_attestation",
    "build_lifecycle_control_decision",
    "build_lifecycle_control_event",
    "build_lifecycle_control_qualification_receipt",
    "build_lifecycle_control_request",
    "effective_control_level",
    "lifecycle_control_is_enforced",
    "load_lifecycle_control_policy",
    "require_lifecycle_control_decision_pass",
    "require_lifecycle_control_event_pass",
    "require_lifecycle_control_policy_pass",
    "resolve_lifecycle_control",
    "validate_lifecycle_control_attestation",
    "validate_lifecycle_control_attestation_with_policy",
    "validate_lifecycle_control_decision",
    "validate_lifecycle_control_decision_with_policy",
    "validate_lifecycle_control_event",
    "validate_lifecycle_control_event_batch_with_policy",
    "validate_lifecycle_control_event_with_policy",
    "validate_lifecycle_control_policy",
    "validate_lifecycle_control_qualification_receipt",
    "validate_lifecycle_control_qualification_with_policy",
    "validate_lifecycle_control_request",
    "validate_lifecycle_control_request_with_policy",
]
