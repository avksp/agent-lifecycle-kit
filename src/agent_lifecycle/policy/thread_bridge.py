"""Deterministic policy for the optional host-thread bridge."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.thread_bridge_schemas import (
    THREAD_BRIDGE_MODES,
    THREAD_OPERATIONS,
    THREAD_SCOPES,
)

THREAD_POLICY_PHASES = (
    "intake",
    "research",
    "planning",
    "review",
    "implementation",
    "audit",
    "finalization",
)
THREAD_POLICY_BLOCKING = ("non-blocking", "required")
THREAD_BRIDGE_POLICY_MAX_BYTES = 32768
THREAD_BRIDGE_POLICY_MAX_TOKENS = 4096

_MODE_ORDER = {mode: index for index, mode in enumerate(THREAD_BRIDGE_MODES)}
_SCOPE_ORDER = {"explicit-target": 0, "project": 1, "workflow": 2}
_DEFAULT_LIMITS = {"maxImportedBytes": 32768, "maxImportedTokens": 2048}
_OPERATION_DEFAULTS = {
    "read": {"enabled": False, "scope": "explicit-target", "approval": "none", "blocking": "non-blocking"},
    "list": {"enabled": False, "scope": "project", "approval": "none", "blocking": "non-blocking"},
    "send": {"enabled": False, "scope": "explicit-target", "approval": "operator", "blocking": "required"},
    "create": {"enabled": False, "scope": "project", "approval": "operator", "blocking": "required"},
}

THREAD_BRIDGE_DEFAULT_POLICY: dict[str, Any] = {
    "mode": "off",
    "operations": deepcopy(_OPERATION_DEFAULTS),
    "phaseRules": {},
    "limits": dict(_DEFAULT_LIMITS),
}


def build_default_thread_bridge_policy() -> dict[str, Any]:
    """Return a detached, disabled policy for a new project profile."""

    return deepcopy(THREAD_BRIDGE_DEFAULT_POLICY)


def normalize_thread_bridge_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Fill the canonical policy shape without granting undeclared authority."""

    value = deepcopy(policy) if isinstance(policy, dict) else build_default_thread_bridge_policy()
    validate_thread_bridge_policy(value)
    operations = {
        operation: {**_OPERATION_DEFAULTS[operation], **value.get("operations", {}).get(operation, {})}
        for operation in THREAD_OPERATIONS
    }
    normalized = {
        "mode": value.get("mode", "off"),
        "operations": operations,
        "phaseRules": deepcopy(value.get("phaseRules", {})),
        "limits": {**_DEFAULT_LIMITS, **value.get("limits", {})},
    }
    return normalized


def validate_thread_bridge_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate policy structure, bounds and authorization defaults."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(policy, dict):
        raise LifecycleError("thread-policy-invalid", "threadBridge policy must be an object")
    unknown = sorted(set(policy) - {"mode", "operations", "phaseRules", "limits"})
    if unknown:
        blockers.append({"code": "thread-policy-field-unsupported", "fields": unknown})
    if policy.get("mode") not in THREAD_BRIDGE_MODES:
        blockers.append({"code": "thread-policy-mode-invalid"})

    operations = policy.get("operations")
    if not isinstance(operations, dict):
        blockers.append({"code": "thread-policy-operations-invalid"})
        operations = {}
    unknown_operations = sorted(set(operations) - set(THREAD_OPERATIONS))
    if unknown_operations:
        blockers.append({"code": "thread-policy-operation-unsupported", "operations": unknown_operations})
    for operation in THREAD_OPERATIONS:
        config = operations.get(operation)
        if not isinstance(config, dict):
            blockers.append({"code": "thread-policy-operation-missing", "operation": operation})
            continue
        blockers.extend(_validate_operation_config(operation, config))

    phase_rules = policy.get("phaseRules", {})
    if not isinstance(phase_rules, dict):
        blockers.append({"code": "thread-policy-phase-rules-invalid"})
        phase_rules = {}
    for phase, rules in phase_rules.items():
        if phase not in THREAD_POLICY_PHASES:
            blockers.append({"code": "thread-policy-phase-invalid", "phase": phase})
            continue
        if not isinstance(rules, dict):
            blockers.append({"code": "thread-policy-phase-rule-invalid", "phase": phase})
            continue
        unknown_phase_operations = sorted(set(rules) - set(THREAD_OPERATIONS))
        if unknown_phase_operations:
            blockers.append(
                {
                    "code": "thread-policy-phase-operation-unsupported",
                    "phase": phase,
                    "operations": unknown_phase_operations,
                }
            )
        for operation, config in rules.items():
            if isinstance(config, dict):
                blockers.extend(_validate_operation_config(operation, config, phase=phase, partial=True))
            else:
                blockers.append({"code": "thread-policy-phase-rule-invalid", "phase": phase, "operation": operation})

    limits = policy.get("limits")
    if not isinstance(limits, dict):
        blockers.append({"code": "thread-policy-limits-invalid"})
        limits = {}
    unknown_limits = sorted(set(limits) - set(_DEFAULT_LIMITS))
    if unknown_limits:
        blockers.append({"code": "thread-policy-limit-unsupported", "fields": unknown_limits})
    for field, maximum in (
        ("maxImportedBytes", THREAD_BRIDGE_POLICY_MAX_BYTES),
        ("maxImportedTokens", THREAD_BRIDGE_POLICY_MAX_TOKENS),
    ):
        value = limits.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > maximum:
            blockers.append({"code": "thread-policy-limit-invalid", "field": field, "maximum": maximum})

    if policy.get("mode") == "off" and any(
        isinstance(config, dict) and config.get("enabled") is True for config in operations.values()
    ):
        blockers.append({"code": "thread-policy-off-enabled-operation"})
    if blockers:
        raise LifecycleError("thread-policy-invalid", "threadBridge policy is invalid", {"blockers": blockers})
    return {
        "status": "PASS",
        "policyDigest": canonical_digest(policy),
        "operationCount": len(operations),
        "phaseCount": len(phase_rules),
        "productionPromotionClaimed": False,
    }


def merge_thread_bridge_policy(
    profile_policy: dict[str, Any] | None,
    plan_policy: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge profile defaults with optional plan authority.

    A plan can opt an operation in, disable it, or narrow its scope and limits.
    A project profile may remain narrower, but it can never widen a plan-bound
    operation, scope or resource cap.
    """

    profile = normalize_thread_bridge_policy(profile_policy)
    if plan_policy is None:
        return profile
    plan = normalize_thread_bridge_policy(plan_policy)
    mode = _merge_mode(profile["mode"], plan["mode"])
    operations: dict[str, dict[str, Any]] = {}
    for operation in THREAD_OPERATIONS:
        profile_operation = profile["operations"][operation]
        plan_operation = plan["operations"][operation]
        operations[operation] = {
            "enabled": bool(profile_operation["enabled"] or plan_operation["enabled"])
            and plan_operation["enabled"] is not False,
            "scope": _narrow_scope(profile_operation["scope"], plan_operation["scope"]),
            "approval": "operator"
            if "operator" in {profile_operation["approval"], plan_operation["approval"]}
            else "none",
            "blocking": "required"
            if "required" in {profile_operation["blocking"], plan_operation["blocking"]}
            else "non-blocking",
        }
        if mode == "off":
            operations[operation]["enabled"] = False
        if mode == "read-only" and operation in {"send", "create"}:
            operations[operation]["enabled"] = False

    phase_rules = _merge_phase_rules(profile["phaseRules"], plan["phaseRules"])
    limits = {
        field: min(profile["limits"][field], plan["limits"][field]) for field in _DEFAULT_LIMITS
    }
    result = {"mode": mode, "operations": operations, "phaseRules": phase_rules, "limits": limits}
    validate_thread_bridge_policy(result)
    return result


def evaluate_thread_operation(
    policy: dict[str, Any],
    operation: str,
    *,
    phase: str | None = None,
    target_scope: str | None = None,
    capability_support: str = "unknown",
) -> dict[str, Any]:
    """Return a deterministic permission decision without contacting a host."""

    normalized = normalize_thread_bridge_policy(policy)
    blockers: list[dict[str, Any]] = []
    if operation not in THREAD_OPERATIONS:
        blockers.append({"code": "thread-operation-invalid", "operation": operation})
        return _decision(operation, phase, "BLOCKED", blockers)
    operation_policy = normalized["operations"][operation]
    effective = _phase_operation(normalized, operation, phase)
    if normalized["mode"] == "off":
        blockers.append({"code": "thread-bridge-disabled"})
    elif normalized["mode"] == "advisory":
        blockers.append({"code": "thread-bridge-advisory-only"})
    if not operation_policy["enabled"] or not effective["enabled"]:
        blockers.append({"code": "thread-operation-disabled", "operation": operation})
    if normalized["mode"] == "read-only" and operation in {"send", "create"}:
        blockers.append({"code": "thread-mutating-operation-read-only"})
    if target_scope is not None and target_scope not in THREAD_SCOPES:
        blockers.append({"code": "thread-target-scope-invalid", "scope": target_scope})
    if target_scope is not None and target_scope in THREAD_SCOPES and _SCOPE_ORDER[target_scope] > _SCOPE_ORDER[effective["scope"]]:
        blockers.append({"code": "thread-target-scope-too-broad", "allowed": effective["scope"], "requested": target_scope})
    if capability_support != "supported":
        blockers.append({"code": "thread-capability-unavailable", "support": capability_support})
    required = effective["blocking"] == "required"
    status = "PASS" if not blockers else "BLOCKED" if required else "UNAVAILABLE"
    return _decision(operation, phase, status, blockers, scope=effective["scope"], approval=effective["approval"])


def require_thread_operation_allowed(
    policy: dict[str, Any],
    operation: str,
    *,
    phase: str | None = None,
    target_scope: str | None = None,
    capability_support: str = "unknown",
) -> dict[str, Any]:
    decision = evaluate_thread_operation(
        policy,
        operation,
        phase=phase,
        target_scope=target_scope,
        capability_support=capability_support,
    )
    if decision["status"] != "PASS":
        raise LifecycleError("thread-operation-not-allowed", "thread operation is not allowed", {"decision": decision})
    return decision


def _validate_operation_config(
    operation: str,
    config: dict[str, Any],
    *,
    phase: str | None = None,
    partial: bool = False,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    allowed = {"enabled", "scope", "approval", "blocking"}
    unknown = sorted(set(config) - allowed)
    if unknown:
        blockers.append({"code": "thread-policy-operation-field-unsupported", "operation": operation, "fields": unknown})
    if not partial or "enabled" in config:
        if not isinstance(config.get("enabled"), bool):
            blockers.append({"code": "thread-policy-enabled-invalid", "operation": operation, "phase": phase})
    if not partial or "scope" in config:
        if config.get("scope") not in THREAD_SCOPES:
            blockers.append({"code": "thread-policy-scope-invalid", "operation": operation, "phase": phase})
    if not partial or "approval" in config:
        expected = "none" if operation in {"read", "list"} else "operator"
        if config.get("approval") != expected:
            blockers.append({"code": "thread-policy-approval-invalid", "operation": operation, "phase": phase})
    if not partial or "blocking" in config:
        if config.get("blocking") not in THREAD_POLICY_BLOCKING:
            blockers.append({"code": "thread-policy-blocking-invalid", "operation": operation, "phase": phase})
    return blockers


def _merge_mode(profile: str, plan: str) -> str:
    if profile == "off":
        return plan
    if plan == "off":
        return "off"
    return profile if _MODE_ORDER[profile] <= _MODE_ORDER[plan] else plan


def _narrow_scope(profile: str, plan: str) -> str:
    return profile if _SCOPE_ORDER[profile] <= _SCOPE_ORDER[plan] else plan


def _merge_phase_rules(profile: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(profile)
    for phase, plan_rules in plan.items():
        current = result.setdefault(phase, {})
        for operation, plan_rule in plan_rules.items():
            if operation not in THREAD_OPERATIONS:
                continue
            profile_rule = current.get(operation, {})
            result[phase][operation] = {
                "enabled": bool(profile_rule.get("enabled", False) or plan_rule.get("enabled", False)),
                "scope": _narrow_scope(profile_rule.get("scope", _OPERATION_DEFAULTS[operation]["scope"]), plan_rule.get("scope", _OPERATION_DEFAULTS[operation]["scope"])),
                "approval": "operator" if "operator" in {profile_rule.get("approval", _OPERATION_DEFAULTS[operation]["approval"]), plan_rule.get("approval", _OPERATION_DEFAULTS[operation]["approval"])} else "none",
                "blocking": "required" if "required" in {profile_rule.get("blocking", "non-blocking"), plan_rule.get("blocking", "non-blocking")} else "non-blocking",
            }
    return result


def _phase_operation(policy: dict[str, Any], operation: str, phase: str | None) -> dict[str, Any]:
    if phase is None:
        return policy["operations"][operation]
    if phase not in THREAD_POLICY_PHASES:
        return {**policy["operations"][operation], "enabled": False}
    return {**policy["operations"][operation], **policy["phaseRules"].get(phase, {}).get(operation, {})}


def _decision(
    operation: str,
    phase: str | None,
    status: str,
    blockers: list[dict[str, Any]],
    *,
    scope: str | None = None,
    approval: str | None = None,
) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-thread-operation-decision.v1",
        "status": status,
        "operation": operation,
        "phase": phase,
        "scope": scope,
        "approval": approval,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "decisionDigest": canonical_digest(body)}
