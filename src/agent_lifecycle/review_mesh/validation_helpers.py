"""Internal provider-neutral field checks; no contract or execution authority."""
from __future__ import annotations

from typing import Any
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES
from agent_lifecycle.quality.cross_check import (
    INDEPENDENCE_IDENTITY_FIELDS, MONEY_KEYS, RESOURCE_CAP_KEYS, USAGE_KEYS, _budget_blockers,
)

PROVIDER_MODEL_NAME_KEYS = {
    "provider",
    "providerName",
    "providerModel",
    "providerModelName",
    "model",
    "modelName",
    "modelId",
    "accountName",
}


def _validate_quorum_policy(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "review-mesh-quorum-policy-invalid"})
        return
    min_reviewers = value.get("minReviewers")
    if not isinstance(min_reviewers, int) or isinstance(min_reviewers, bool) or min_reviewers <= 0:
        blockers.append({"code": "review-mesh-quorum-min-reviewers-invalid"})
    required_roles = value.get("requiredRoles", [])
    if required_roles is not None:
        _check_string_list(required_roles, "review-mesh-quorum-required-roles-invalid", blockers, allow_empty=True)
    threshold = value.get("blockingSeverityThreshold")
    if threshold is not None and threshold not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        blockers.append({"code": "review-mesh-quorum-threshold-invalid"})

def _validate_modes(modes: list[str], code: str) -> None:
    unknown = sorted(set(modes).difference(REVIEW_MESH_MODE_IDS))
    if unknown:
        raise LifecycleError(code, "unknown Review Mesh mode", {"modes": unknown})

def _model_classes(values: list[str]) -> list[str]:
    classes = _string_list(values, "invalid-review-mesh-profile", label="reviewerModelClasses")
    unknown = sorted(set(classes).difference(ALLOWED_MODEL_CLASSES))
    if unknown:
        raise LifecycleError(
            "invalid-review-mesh-profile", "unknown provider-neutral model classes", {"classes": unknown}
        )
    return classes

def _validate_model_classes(values: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(values, list) or not values:
        blockers.append({"code": "review-mesh-model-classes-invalid"})
        return
    unknown = sorted({item for item in values if not isinstance(item, str) or item not in ALLOWED_MODEL_CLASSES})
    if unknown:
        blockers.append({"code": "review-mesh-model-classes-unknown", "classes": unknown})

def _validate_resource_cap(value: Any, blockers: list[dict[str, Any]], *, prefix: str) -> None:
    if not isinstance(value, dict) or not value:
        blockers.append({"code": f"{prefix}-budget-cap-invalid"})
        return
    for key, item in value.items():
        if key in MONEY_KEYS:
            blockers.append({"code": "review-mesh-money-cap-not-allowed", "field": key})
        elif key not in RESOURCE_CAP_KEYS:
            blockers.append({"code": f"{prefix}-budget-cap-unsupported", "field": key})
        elif not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            blockers.append({"code": f"{prefix}-budget-cap-value-invalid", "field": key})

def _validate_budget_usage(
    value: Any, blockers: list[dict[str, Any]], *, prefix: str, allow_unknown: bool = False
) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": f"{prefix}-budget-usage-invalid"})
        return
    if set(value) != USAGE_KEYS:
        blockers.append({"code": f"{prefix}-budget-usage-incomplete"})
    for key, item in value.items():
        if key in MONEY_KEYS:
            blockers.append({"code": "review-mesh-money-usage-not-allowed", "field": key})
        elif key not in USAGE_KEYS:
            blockers.append({"code": f"{prefix}-budget-usage-unsupported", "field": key})
        elif not (allow_unknown and item is None) and (type(item) is not int or item < 0):
            blockers.append({"code": f"{prefix}-budget-usage-value-invalid", "field": key})

def _known_usage_budget_blockers(usage: Any, profile: Any) -> list[dict[str, Any]]:
    if not isinstance(usage, dict) or not isinstance(profile, dict):
        return []
    cap = profile.get("budgetCap")
    if not isinstance(cap, dict):
        return []
    known = {key: value for key, value in usage.items() if key in USAGE_KEYS and type(value) is int and value >= 0}
    return _budget_blockers(known, cap)

def _live_call_policy_blockers(started: Any, profile: Any) -> list[dict[str, Any]]:
    if type(started) is not bool:
        return [{"code": "review-mesh-result-live-calls-started-invalid"}]
    cross_profile = profile.get("crossCheckProfile") if isinstance(profile, dict) else None
    if started and isinstance(cross_profile, dict) and cross_profile.get("liveCallsAllowed") is not True:
        return [{"code": "cross-check-live-call-not-allowed"}]
    return []

def _command_outcome_blockers(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [{"code": "review-mesh-result-command-outcomes-invalid"}]
    blockers: list[dict[str, Any]] = []
    seen = set()
    for command in value:
        if not isinstance(command, dict):
            blockers.append({"code": "review-mesh-result-command-outcome-invalid"})
            continue
        identifier = command.get("commandId")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            blockers.append({"code": "review-mesh-result-command-id-invalid"})
        else:
            seen.add(identifier)
        status, exit_code = command.get("status"), command.get("exitCode")
        if not isinstance(status, str) or status not in {"PASS", "FAIL"} or type(exit_code) is not int:
            blockers.append({"code": "review-mesh-result-command-outcome-invalid"})
        elif status == "PASS" and exit_code != 0:
            blockers.append({"code": "review-mesh-result-command-exit-status-mismatch"})
    return blockers

def _money_key_blockers(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else key
            if key in MONEY_KEYS:
                blockers.append({"code": "review-mesh-monetary-field-not-allowed", "path": next_path})
            blockers.extend(_money_key_blockers(item, path=next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blockers.extend(_money_key_blockers(item, path=f"{path}[{index}]"))
    return blockers

def _provider_model_name_blockers(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else key
            if key in PROVIDER_MODEL_NAME_KEYS and not _is_neutral_identity_field_mapping(path, key):
                blockers.append({"code": "review-mesh-provider-model-name-not-portable", "path": next_path})
            blockers.extend(_provider_model_name_blockers(item, path=next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blockers.extend(_provider_model_name_blockers(item, path=f"{path}[{index}]"))
    return blockers

def _is_neutral_identity_field_mapping(path: str, key: str) -> bool:
    return path.endswith("identityFields") and key in INDEPENDENCE_IDENTITY_FIELDS

def _object_or_blocker(value: Any, code: str, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        blockers.append({"code": code})
        return {}
    return value

def _required_string(value: Any, code: str, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} is required")
    return value

def _string_list(value: Any, code: str, *, label: str, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise LifecycleError(code, f"{label} must be a list of strings")
    return list(value)

def _digest_list(value: Any, code: str, *, label: str) -> list[str]:
    values = _string_list(value, code, label=label)
    if any(len(item) != 64 for item in values):
        raise LifecycleError(code, f"{label} must contain 64-character digests")
    return values

def _enum(value: Any, allowed: set[str], code: str, *, label: str) -> str:
    if value not in allowed:
        raise LifecycleError(code, f"{label} is unsupported", {label: value})
    return str(value)

def _non_negative_int(value: Any, code: str, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError(code, f"{label} must be a non-negative integer")
    return value

def _check_const(payload: dict[str, Any], field: str, expected: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if payload.get(field) != expected:
        blockers.append({"code": code})

def _check_required_string(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or not value:
        blockers.append({"code": code})

def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or len(value) != 64:
        blockers.append({"code": code})

def _check_digest_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and len(item) == 64 for item in value):
        blockers.append({"code": code})

def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        blockers.append({"code": code})

def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})
