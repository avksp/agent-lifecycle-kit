"""Budget exceeded policy validation and deterministic action selection."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

ALLOWED_BUDGET_ACTIONS = {
    "continue-same-route",
    "reroute-cheaper",
    "reroute-stronger",
    "split-task",
    "abort",
}
BUDGET_MODES = {"metered", "subscription", "local"}
CRITICAL_DOWNGRADE_ACTIONS = {"reroute-cheaper"}


def validate_budget_exceeded_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get("schemaVersion") != "agent-lifecycle-budget-exceeded-policy.v1":
        raise LifecycleError("invalid-budget-policy", "unsupported budget exceeded policy schema")
    mode = _required_str(policy, "mode")
    if mode not in {"manual", "auto"}:
        raise LifecycleError("invalid-budget-policy", "mode must be manual or auto", {"mode": mode})
    allowed_actions = _required_string_list(policy, "allowedActions")
    unknown = sorted(set(allowed_actions) - ALLOWED_BUDGET_ACTIONS)
    if unknown:
        raise LifecycleError("invalid-budget-policy", "allowedActions contains unsupported actions", {"actions": unknown})
    if not allowed_actions:
        raise LifecycleError("invalid-budget-policy", "allowedActions must not be empty")
    forbid_critical = policy.get("forbidDowngradeForCriticalReview")
    if not isinstance(forbid_critical, bool):
        raise LifecycleError("invalid-budget-policy", "forbidDowngradeForCriticalReview must be boolean")
    max_auto = policy.get("maxAutoReroutesPerTask")
    if not isinstance(max_auto, int) or isinstance(max_auto, bool) or max_auto < 0:
        raise LifecycleError("invalid-budget-policy", "maxAutoReroutesPerTask must be a non-negative integer")
    default_auto = policy.get("defaultAutoAction")
    if mode == "auto" and default_auto not in allowed_actions:
        raise LifecycleError("invalid-budget-policy", "defaultAutoAction must be one of allowedActions")
    budget_modes = policy.get("budgetModes")
    if not isinstance(budget_modes, dict):
        raise LifecycleError("invalid-budget-policy", "budgetModes must be an object")
    mode_checks = [_budget_mode_check(name, budget_modes.get(name)) for name in sorted(BUDGET_MODES)]
    if any(item["status"] == "FAIL" for item in mode_checks):
        raise LifecycleError("invalid-budget-policy", "budget mode caps are invalid", {"checks": mode_checks})
    return {
        "schemaVersion": "agent-lifecycle-budget-exceeded-policy-validation.v1",
        "status": "PASS",
        "mode": mode,
        "allowedActions": allowed_actions,
        "policyDigest": canonical_digest(policy),
        "checks": mode_checks,
    }


def select_auto_budget_action(
    policy: dict[str, Any],
    *,
    task: dict[str, Any],
    route_decision: dict[str, Any],
) -> str:
    validation = validate_budget_exceeded_policy(policy)
    if validation["mode"] != "auto":
        raise LifecycleError("invalid-budget-policy", "auto action selection requires auto mode")
    reroutes = int(task.get("budgetAutoReroutes", 0))
    if reroutes >= int(policy["maxAutoReroutesPerTask"]):
        raise LifecycleError("budget-auto-reroute-limit", "max auto reroutes per task exhausted")
    action = str(policy["defaultAutoAction"])
    if (
        policy.get("forbidDowngradeForCriticalReview") is True
        and route_decision.get("criticalReview") is True
        and action in CRITICAL_DOWNGRADE_ACTIONS
    ):
        for candidate in ("reroute-stronger", "split-task", "continue-same-route", "abort"):
            if candidate in policy["allowedActions"]:
                return candidate
        raise LifecycleError("budget-critical-downgrade", "critical review cannot auto-downgrade to a cheaper route")
    return action


def _budget_mode_check(mode: str, config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {"id": f"{mode}-cap-config", "status": "FAIL", "reason": "missing"}
    if mode == "metered":
        cap = config.get("budgetCapUsd")
        threshold = config.get("meteredAskThreshold")
        has_cap = _positive_number(cap)
        threshold_present = threshold is not None
        threshold_valid = (
            not threshold_present
            or (_positive_number(threshold) and has_cap and float(threshold) < float(cap))
        )
        return {
            "id": "metered-usd-cap",
            "status": "PASS" if has_cap and threshold_valid else "FAIL",
            "hasBudgetCapUsd": has_cap,
            "advisoryThresholdEnabled": threshold_present and threshold_valid,
            "advisoryOnly": threshold_present,
        }
    if "meteredAskThreshold" in config:
        return {
            "id": f"{mode}-resource-caps",
            "status": "FAIL",
            "reason": "meteredAskThreshold is only valid for metered budget mode",
        }
    max_invocations = config.get("maxInvocations")
    has_invocations = isinstance(max_invocations, int) and not isinstance(max_invocations, bool) and max_invocations > 0
    has_tokens = (
        isinstance(config.get("maxBillableTokens"), int)
        and not isinstance(config.get("maxBillableTokens"), bool)
        and config["maxBillableTokens"] > 0
    )
    has_wall = _positive_number(config.get("maxWallSeconds"))
    return {
        "id": f"{mode}-resource-caps",
        "status": "PASS" if has_invocations and (has_tokens or has_wall) else "FAIL",
        "hasMaxInvocations": has_invocations,
        "hasTokenOrWallCap": has_tokens or has_wall,
    }


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-budget-policy", f"{key} is required")
    return value


def _required_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise LifecycleError("invalid-budget-policy", f"{key} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise LifecycleError("invalid-budget-policy", f"{key} contains duplicates")
    return list(value)


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
