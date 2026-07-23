"""Validation helpers for provider-neutral model routing profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.context.profiles import WINDOWS
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object

ALLOWED_MODEL_CLASSES = {
    "no-model",
    "budget",
    "local-compact",
    "standard-code",
    "local-standard-code",
    "strong-reasoning",
    "local-strong-review",
    "specialist-review",
}
LOCAL_MODEL_CLASSES = {"local-compact", "local-standard-code", "local-strong-review"}
CRITICAL_REVIEW_CLASSES = {"strong-reasoning", "local-strong-review", "specialist-review"}
ROUTING_POLICIES = {"cost-optimized", "balanced", "quality-first", "local-only", "manual"}
SDD_TIERS = {"S0", "S1", "S2"}
JSON_RELIABILITY = {"strict", "best-effort", "unsupported"}
TOOL_USE = {"supported", "unsupported"}
USAGE_ACCOUNTING = {"host-attested", "required", "unavailable"}
DATA_POLICIES = {"cloud-allowed", "local-only", "restricted"}
CALIBRATION_STATUSES = {"PASSED", "PENDING", "FAILED", "UNKNOWN"}


def load_model_routing_profile(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="model routing profile")


def load_host_model_profile(path: Path) -> dict[str, Any]:
    return read_json_object(path, label="host model profile")


def validate_model_routing_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("schemaVersion") != "agent-lifecycle-model-routing-profile.v1":
        raise LifecycleError("invalid-model-routing-profile", "unsupported model routing profile schema")
    profile_id = _required_str(profile, "profileId", "model routing profile")
    classes = _required_string_list(profile, "classes", "model routing profile")
    unknown = sorted(set(classes) - ALLOWED_MODEL_CLASSES)
    if unknown:
        raise LifecycleError("invalid-model-routing-profile", "unknown model classes", {"classes": unknown})
    if "no-model" not in classes:
        raise LifecycleError("invalid-model-routing-profile", "no-model class is required")
    phase_rules = _required_dict(profile, "phaseRules", "model routing profile")
    invalid_phase_rules = sorted(
        phase
        for phase, model_class in phase_rules.items()
        if not isinstance(phase, str) or not phase or model_class not in classes
    )
    if invalid_phase_rules:
        raise LifecycleError(
            "invalid-model-routing-profile",
            "phaseRules must map phases to declared model classes",
            {"phases": invalid_phase_rules},
        )
    token_budgets = profile.get("tokenBudgets", {})
    if token_budgets is not None:
        _validate_token_budgets(token_budgets)
    critical_phases = profile.get("criticalReviewPhases", [])
    if critical_phases is not None:
        _required_string_list(profile, "criticalReviewPhases", "model routing profile")
    policy_presets = profile.get("policyPresets", {})
    if policy_presets is not None:
        _validate_policy_presets(policy_presets)
    return {
        "schemaVersion": "agent-lifecycle-model-routing-profile-validation.v1",
        "profileId": profile_id,
        "classes": classes,
        "phaseRuleCount": len(phase_rules),
        "criticalReviewPhases": sorted(critical_phases),
        "policyPresets": sorted(policy_presets),
        "profileDigest": canonical_digest(profile),
    }


def validate_host_model_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("schemaVersion") != "agent-lifecycle-host-model-profile.v1":
        raise LifecycleError("invalid-host-model-profile", "unsupported host model profile schema")
    profile_id = _required_str(profile, "profileId", "host model profile")
    host = _required_str(profile, "host", "host model profile")
    bindings = _required_dict(profile, "bindings", "host model profile")
    if not bindings:
        raise LifecycleError("invalid-host-model-profile", "bindings are required")
    checked: dict[str, Any] = {}
    for model_class, binding in bindings.items():
        if model_class not in ALLOWED_MODEL_CLASSES:
            raise LifecycleError(
                "invalid-host-model-profile",
                "unknown model class binding",
                {"modelClass": model_class},
            )
        if model_class == "no-model":
            raise LifecycleError("invalid-host-model-profile", "no-model must not have a host binding")
        if not isinstance(binding, dict):
            raise LifecycleError("invalid-host-model-profile", "binding must be an object", {"modelClass": model_class})
        checked[model_class] = _validate_binding(model_class, binding)
    return {
        "schemaVersion": "agent-lifecycle-host-model-profile-validation.v1",
        "host": host,
        "profileId": profile_id,
        "classes": sorted(checked),
        "bindings": checked,
        "profileDigest": canonical_digest(profile),
    }


def _validate_binding(model_class: str, binding: dict[str, Any]) -> dict[str, Any]:
    _required_str(binding, "providerModel", f"{model_class} binding")
    context_window = _required_str(binding, "contextWindow", f"{model_class} binding")
    if context_window not in WINDOWS:
        raise LifecycleError(
            "invalid-host-model-profile",
            "binding contextWindow is unsupported",
            {"modelClass": model_class, "contextWindow": context_window},
        )
    capabilities = _required_string_list(binding, "capabilities", f"{model_class} binding")
    json_reliability = _enum(binding, "jsonReliability", JSON_RELIABILITY, default="best-effort")
    tool_use = _enum(binding, "toolUse", TOOL_USE, default="unsupported")
    usage_accounting = _enum(binding, "usageAccounting", USAGE_ACCOUNTING, default="unavailable")
    data_policy = _enum(binding, "dataPolicy", DATA_POLICIES, default="restricted")
    calibration_status = _enum(binding, "calibrationStatus", CALIBRATION_STATUSES, default="UNKNOWN")
    allowed_tiers = _optional_limited_string_list(binding, "allowedForTiers", SDD_TIERS)
    allowed_phases = _optional_string_list(binding, "allowedForPhases")
    disallowed_risks = _optional_string_list(binding, "disallowedForRisks")
    review_strategy = binding.get("reviewStrategy")
    if review_strategy is not None and not isinstance(review_strategy, str):
        raise LifecycleError("invalid-host-model-profile", "reviewStrategy must be a string", {"modelClass": model_class})
    return {
        "contextWindow": context_window,
        "capabilities": capabilities,
        "jsonReliability": json_reliability,
        "toolUse": tool_use,
        "allowedForTiers": allowed_tiers,
        "allowedForPhases": allowed_phases,
        "disallowedForRisks": disallowed_risks,
        "usageAccounting": usage_accounting,
        "dataPolicy": data_policy,
        "calibrationStatus": calibration_status,
        "reviewStrategy": review_strategy,
        "bindingDigest": canonical_digest(binding),
    }


def _validate_token_budgets(value: Any) -> None:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-model-routing-profile", "tokenBudgets must be an object")
    for tier, budgets in value.items():
        if tier not in SDD_TIERS or not isinstance(budgets, dict):
            raise LifecycleError("invalid-model-routing-profile", "tokenBudgets keys must be SDD tiers")
        for budget_class, amount in budgets.items():
            if not isinstance(budget_class, str) or not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                raise LifecycleError("invalid-model-routing-profile", "token budget values must be non-negative integers")


def _validate_policy_presets(value: Any) -> None:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-model-routing-profile", "policyPresets must be an object")
    unknown = sorted(set(value) - ROUTING_POLICIES)
    if unknown:
        raise LifecycleError("invalid-model-routing-profile", "unknown policy presets", {"policies": unknown})
    for policy, payload in value.items():
        if not isinstance(payload, dict):
            raise LifecycleError("invalid-model-routing-profile", "policy preset must be an object", {"policy": policy})


def _required_str(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-model-routing-profile", f"{label}: {key} is required")
    return value


def _required_dict(payload: dict[str, Any], key: str, label: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise LifecycleError("invalid-model-routing-profile", f"{label}: {key} object is required")
    return value


def _required_string_list(payload: dict[str, Any], key: str, label: str) -> list[str]:
    if key not in payload:
        raise LifecycleError("invalid-model-routing-profile", f"{label}: {key} is required")
    return _string_list(payload[key], key=key)


def _optional_string_list(payload: dict[str, Any], key: str) -> list[str]:
    if key not in payload:
        return []
    return _string_list(payload[key], key=key)


def _optional_limited_string_list(payload: dict[str, Any], key: str, allowed: set[str]) -> list[str]:
    values = _optional_string_list(payload, key)
    invalid = sorted(set(values) - allowed)
    if invalid:
        raise LifecycleError("invalid-host-model-profile", f"{key} contains unsupported values", {"values": invalid})
    return values


def _string_list(value: Any, *, key: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise LifecycleError("invalid-model-routing-profile", f"{key} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise LifecycleError("invalid-model-routing-profile", f"{key} contains duplicates")
    return list(value)


def _enum(payload: dict[str, Any], key: str, allowed: set[str], *, default: str) -> str:
    value = payload.get(key, default)
    if value not in allowed:
        raise LifecycleError("invalid-host-model-profile", f"{key} is unsupported", {"value": value})
    return value
