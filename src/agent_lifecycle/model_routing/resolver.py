"""Deterministic provider-neutral model route resolver."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.context.profiles import WINDOWS
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.quality_modes import MODES as LIFECYCLE_MODES
from agent_lifecycle.contracts.quality_modes import mode_index
from agent_lifecycle.model_routing.profiles import (
    ALLOWED_MODEL_CLASSES,
    CRITICAL_REVIEW_CLASSES,
    LOCAL_MODEL_CLASSES,
    ROUTING_POLICIES,
    SDD_TIERS,
    validate_host_model_profile,
    validate_model_routing_profile,
)
from agent_lifecycle.quality.failure_classification import FAILURE_CLASSES, HIGH_RISK_FAILURE_CLASSES

DEFAULT_CRITICAL_PHASES = {
    "s2-specification",
    "independent-review",
    "security-review",
    "performance-review",
    "release-review",
    "production-promotion",
    "final-audit",
}
DEFAULT_TOKEN_BUDGETS = {
    "S0": {"tight": 20000, "normal": 40000, "generous": 70000},
    "S1": {"tight": 60000, "normal": 120000, "generous": 220000},
    "S2": {"tight": 250000, "normal": 400000, "generous": 800000},
}
RISK_NAME_MAP = {
    "architecture": "architecture",
    "security": "security",
    "performance": "performance",
    "browser": "browser",
    "externalEnvironment": "external-environment",
    "external-environment": "external-environment",
}
FAILURE_STATUSES = {"FAIL", "ERROR", "BLOCKED", "REJECTED"}
FLAKE_STATUSES = {"stable-fail", "stable-pass", "flaky", "inconclusive"}
MODEL_CLASS_RANK = {
    "no-model": 0,
    "budget": 1,
    "local-compact": 1,
    "standard-code": 2,
    "local-standard-code": 2,
    "strong-reasoning": 3,
    "local-strong-review": 3,
    "specialist-review": 4,
}
FORBIDDEN_FAILURE_SIGNAL_KEYS = {
    "provider",
    "providerid",
    "providermodel",
    "providermodelhash",
    "providername",
    "modelid",
    "modelname",
}


def resolve_model_route(
    request: dict[str, Any],
    routing_profile: dict[str, Any],
    *,
    host_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a route decision without invoking a provider model."""

    validate_model_routing_profile(routing_profile)
    normalized = _validate_request(request)
    host_validation = validate_host_model_profile(host_profile) if host_profile is not None else None
    base_candidate = _candidate_for_request(normalized, routing_profile)
    candidate, escalation_reasons = _apply_failure_escalation(base_candidate, normalized)
    fallback_classes = _fallback_classes(candidate, normalized)
    selected, binding, rejections = _select_supported_class(
        candidate,
        fallback_classes,
        normalized,
        host_profile,
    )
    max_billable = _max_billable_tokens(normalized, routing_profile)
    critical = _is_critical_review(normalized, routing_profile)
    decision = {
        "schemaVersion": "agent-lifecycle-model-route-decision.v1",
        "operationId": normalized["operationId"],
        "phase": normalized["phase"],
        "sddTier": normalized["sddTier"],
        "routingPolicy": normalized["routingPolicy"],
        "modelClass": selected,
        "allowedFallbackModelClasses": fallback_classes,
        "targetContextWindow": normalized["targetContextWindow"],
        "capabilityRequirements": normalized["capabilityRequirements"],
        "criticalReview": critical,
        "requiresUsageReceipt": selected != "no-model",
        "maxBillableTokens": max_billable if selected != "no-model" else 0,
        "reasonCodes": _reason_codes(normalized, selected, candidate, critical, rejections, escalation_reasons),
        "escalation": _escalation_summary(normalized, base_candidate, candidate, selected, escalation_reasons),
        "requestDigest": canonical_digest(request),
        "profileDigest": canonical_digest(routing_profile),
    }
    if host_validation is not None:
        decision["host"] = host_validation["host"]
        decision["hostProfileDigest"] = host_validation["profileDigest"]
    if binding is not None:
        decision["hostBindingDigest"] = canonical_digest(binding)
    decision["decisionDigest"] = canonical_digest(decision)
    return decision


def _validate_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schemaVersion") != "agent-lifecycle-model-route-request.v1":
        raise LifecycleError("invalid-model-route-request", "unsupported model route request schema")
    operation_id = _required_str(request, "operationId")
    phase = _required_str(request, "phase")
    sdd_tier = _required_str(request, "sddTier")
    if sdd_tier not in SDD_TIERS:
        raise LifecycleError("invalid-model-route-request", "sddTier is unsupported", {"sddTier": sdd_tier})
    risk_flags = request.get("riskFlags", {})
    if not isinstance(risk_flags, dict):
        raise LifecycleError("invalid-model-route-request", "riskFlags must be an object")
    normalized_risks = {str(key): bool(value) for key, value in risk_flags.items()}
    requirements = request.get("capabilityRequirements", [])
    if not isinstance(requirements, list) or any(not isinstance(item, str) or not item for item in requirements):
        raise LifecycleError("invalid-model-route-request", "capabilityRequirements must be a list of strings")
    target_window = request.get("targetContextWindow", "8k")
    if target_window not in WINDOWS:
        raise LifecycleError(
            "invalid-model-route-request", "targetContextWindow is unsupported", {"targetContextWindow": target_window}
        )
    policy = request.get("routingPolicy", "balanced")
    if policy not in ROUTING_POLICIES:
        raise LifecycleError("invalid-model-route-request", "routingPolicy is unsupported", {"routingPolicy": policy})
    budget_class = request.get("budgetClass", "normal")
    if not isinstance(budget_class, str) or not budget_class:
        raise LifecycleError("invalid-model-route-request", "budgetClass must be a string")
    user_policy = request.get("userPolicy", {})
    if not isinstance(user_policy, dict):
        raise LifecycleError("invalid-model-route-request", "userPolicy must be an object")
    max_billable = request.get("maxBillableTokens")
    if max_billable is not None and (
        not isinstance(max_billable, int) or isinstance(max_billable, bool) or max_billable < 0
    ):
        raise LifecycleError("invalid-model-route-request", "maxBillableTokens must be a non-negative integer")
    lifecycle_mode = request.get("lifecycleMode")
    if lifecycle_mode is not None and lifecycle_mode not in LIFECYCLE_MODES:
        raise LifecycleError(
            "invalid-model-route-request", "lifecycleMode is unsupported", {"lifecycleMode": lifecycle_mode}
        )
    quality_floor = request.get("qualityFloor")
    if quality_floor is not None and quality_floor not in LIFECYCLE_MODES:
        raise LifecycleError(
            "invalid-model-route-request", "qualityFloor is unsupported", {"qualityFloor": quality_floor}
        )
    if (
        lifecycle_mode is not None
        and quality_floor is not None
        and mode_index(lifecycle_mode) < mode_index(quality_floor)
    ):
        raise LifecycleError(
            "model-route-lifecycle-floor",
            "lifecycleMode cannot be below qualityFloor",
            {"lifecycleMode": lifecycle_mode, "qualityFloor": quality_floor},
        )
    failure_signals = _failure_signals(request.get("failureSignals", {}))
    return {
        "operationId": operation_id,
        "phase": phase,
        "sddTier": sdd_tier,
        "riskFlags": normalized_risks,
        "capabilityRequirements": list(requirements),
        "targetContextWindow": target_window,
        "routingPolicy": policy,
        "budgetClass": budget_class,
        "userPolicy": dict(user_policy),
        "maxBillableTokens": max_billable,
        "lifecycleMode": lifecycle_mode,
        "qualityFloor": quality_floor,
        "failureSignals": failure_signals,
    }


def _candidate_for_request(request: dict[str, Any], profile: dict[str, Any]) -> str:
    phase = request["phase"]
    policy = request["routingPolicy"]
    tier = request["sddTier"]
    if phase in {"deterministic-validation", "schema-check", "profile-check", "context-check"}:
        return "no-model"
    if _is_critical_review(request, profile):
        return "local-strong-review" if _local_only(request) else "strong-reasoning"
    if _local_only(request):
        if tier == "S0" and request["targetContextWindow"] in {"4k-strict", "8k"}:
            return "local-compact"
        return "local-standard-code"
    if request.get("lifecycleMode") == "light" and tier in {"S0", "S1"}:
        return "budget"
    if policy == "quality-first":
        return "standard-code" if tier == "S0" else "strong-reasoning"
    phase_rules = profile.get("phaseRules", {})
    if phase in phase_rules and phase_rules[phase] in ALLOWED_MODEL_CLASSES:
        return str(phase_rules[phase])
    if tier == "S0":
        return "budget"
    if tier == "S1":
        return "standard-code"
    return "strong-reasoning"


def _apply_failure_escalation(candidate: str, request: dict[str, Any]) -> tuple[str, list[str]]:
    signals = request.get("failureSignals", {})
    if not signals:
        return candidate, []
    if candidate == "no-model":
        return candidate, ["failure-signals-observed-no-model-phase"]
    base_candidate = candidate
    reasons: list[str] = []
    target = candidate
    failure_class = signals.get("failureClass")
    retry_count = int(signals.get("retryCount", 0))
    remediation_loops = int(signals.get("remediationLoops", 0))
    validation_status = signals.get("validationStatus")
    flake_status = signals.get("flakeStatus")
    previous = signals.get("previousModelClass")
    local_only = _local_only(request)
    standard = "local-standard-code" if local_only else "standard-code"
    strong = "local-strong-review" if local_only else "strong-reasoning"

    if validation_status in FAILURE_STATUSES and _rank(target) < _rank(standard):
        target = standard
        reasons.append("validation-failure-escalation")
    if failure_class in {"api-contract", "serialization", "permission", "migration", "performance"} and _rank(
        target
    ) < _rank(standard):
        target = standard
        reasons.append(f"failure-class-{failure_class}-standard-escalation")
    if failure_class in HIGH_RISK_FAILURE_CLASSES or failure_class == "flaky-test" or flake_status == "flaky":
        target = strong
        reasons.append(f"failure-class-{failure_class or 'flake'}-stronger-review")
    if retry_count >= 2 or remediation_loops >= 2:
        target = strong
        reasons.append("repeated-failure-stronger-review")
    elif retry_count >= 1 and _rank(target) < _rank(standard):
        target = standard
        reasons.append("retry-standard-escalation")
    if previous in ALLOWED_MODEL_CLASSES and retry_count > 0 and _rank(previous) > _rank(base_candidate):
        if _rank(previous) > _rank(target):
            target = _local_equivalent(previous) if local_only else previous
        reasons.append("no-downgrade-after-failure")
    if failure_class in FAILURE_CLASSES:
        reasons.append(f"failure-class-{failure_class}")
    if signals.get("classificationDigest"):
        reasons.append("failure-classification-digest-bound")
    return target, sorted(set(reasons))


def _fallback_classes(candidate: str, request: dict[str, Any]) -> list[str]:
    local_only = _local_only(request)
    cloud_allowed = bool(request["userPolicy"].get("cloudModelsAllowed", True))
    if candidate == "no-model":
        return []
    if candidate == "budget":
        return ["standard-code", "strong-reasoning"] if cloud_allowed else []
    if candidate == "local-compact":
        return ["local-standard-code", "local-strong-review"]
    if candidate == "standard-code":
        return ["strong-reasoning"] if cloud_allowed else []
    if candidate == "local-standard-code":
        return ["local-strong-review"] if local_only else ["local-strong-review", "strong-reasoning"]
    if candidate == "strong-reasoning":
        return ["local-strong-review", "specialist-review"] if not local_only else ["local-strong-review"]
    if candidate == "local-strong-review":
        return ["strong-reasoning", "specialist-review"] if cloud_allowed else ["specialist-review"]
    return []


def _failure_signals(value: Any) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise LifecycleError("invalid-model-route-request", "failureSignals must be an object")
    forbidden = _forbidden_failure_signal_paths(value)
    if forbidden:
        raise LifecycleError(
            "invalid-model-route-request", "failureSignals must not contain provider/model names", {"paths": forbidden}
        )
    failure_class = value.get("failureClass")
    if failure_class is not None and failure_class not in FAILURE_CLASSES:
        raise LifecycleError(
            "invalid-model-route-request", "failureSignals.failureClass is unsupported", {"failureClass": failure_class}
        )
    confidence = value.get("confidence")
    if confidence is not None and confidence not in {"LOW", "MEDIUM", "HIGH"}:
        raise LifecycleError(
            "invalid-model-route-request", "failureSignals.confidence is unsupported", {"confidence": confidence}
        )
    validation_status = value.get("validationStatus")
    if validation_status is not None and not isinstance(validation_status, str):
        raise LifecycleError("invalid-model-route-request", "failureSignals.validationStatus must be a string")
    flake_status = value.get("flakeStatus")
    if flake_status is not None and flake_status not in FLAKE_STATUSES:
        raise LifecycleError(
            "invalid-model-route-request", "failureSignals.flakeStatus is unsupported", {"flakeStatus": flake_status}
        )
    previous = value.get("previousModelClass")
    if previous is not None and previous not in ALLOWED_MODEL_CLASSES:
        raise LifecycleError(
            "invalid-model-route-request",
            "failureSignals.previousModelClass is unsupported",
            {"previousModelClass": previous},
        )
    classification_digest = value.get("classificationDigest")
    if classification_digest is not None and not _is_digest(classification_digest):
        raise LifecycleError(
            "invalid-model-route-request", "failureSignals.classificationDigest must be a sha256 digest"
        )
    return {
        "failureClass": failure_class,
        "confidence": confidence,
        "retryCount": _non_negative_int(value.get("retryCount", 0), "failureSignals.retryCount"),
        "remediationLoops": _non_negative_int(value.get("remediationLoops", 0), "failureSignals.remediationLoops"),
        "validationStatus": validation_status,
        "flakeStatus": flake_status,
        "previousModelClass": previous,
        "classificationDigest": classification_digest,
        "evidenceIds": _optional_string_list(value.get("evidenceIds", []), "failureSignals.evidenceIds"),
    }


def _select_supported_class(
    candidate: str,
    fallback_classes: list[str],
    request: dict[str, Any],
    host_profile: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    if candidate == "no-model":
        return "no-model", None, []
    if host_profile is None:
        if candidate in LOCAL_MODEL_CLASSES or _local_only(request):
            raise LifecycleError("host-model-profile-required", "local routing requires a host model profile")
        return candidate, None, []
    bindings = host_profile.get("bindings", {})
    rejections: list[dict[str, Any]] = []
    for model_class in [candidate, *fallback_classes]:
        binding = bindings.get(model_class)
        if not isinstance(binding, dict):
            rejections.append({"modelClass": model_class, "reason": "binding-missing"})
            continue
        rejection = _binding_rejection(model_class, binding, request)
        if rejection is None:
            return model_class, binding, rejections
        rejections.append({"modelClass": model_class, "reason": rejection})
    raise LifecycleError(
        "model-route-unsupported",
        "no host model binding satisfies the route",
        {"candidate": candidate, "fallbacks": fallback_classes, "rejections": rejections},
    )


def _binding_rejection(model_class: str, binding: dict[str, Any], request: dict[str, Any]) -> str | None:
    required_context = WINDOWS[request["targetContextWindow"]]
    if WINDOWS[binding.get("contextWindow", "")] < required_context:
        return "context-window-too-small"
    capabilities = set(binding.get("capabilities", []))
    missing = sorted(set(request["capabilityRequirements"]) - capabilities)
    if missing:
        return f"missing-capabilities:{','.join(missing)}"
    if "tool-use" in request["capabilityRequirements"] and binding.get("toolUse", "unsupported") != "supported":
        return "tool-use-unsupported"
    if "json" in request["capabilityRequirements"] and binding.get("jsonReliability") not in {"strict", "best-effort"}:
        return "json-unsupported"
    allowed_tiers = binding.get("allowedForTiers", [])
    if allowed_tiers and request["sddTier"] not in allowed_tiers:
        return "tier-disallowed"
    allowed_phases = binding.get("allowedForPhases", [])
    if allowed_phases and request["phase"] not in allowed_phases:
        return "phase-disallowed"
    disallowed = set(binding.get("disallowedForRisks", []))
    active_risks = _active_risks(request)
    if request["phase"] in {"final-audit", "release-review", "production-promotion"}:
        active_risks.add("release-final")
    blocked = sorted(active_risks & disallowed)
    if blocked:
        return f"risk-disallowed:{','.join(blocked)}"
    data_policy = binding.get("dataPolicy")
    if data_policy == "cloud-allowed" and not request["userPolicy"].get("cloudModelsAllowed", True):
        return "cloud-disallowed"
    if data_policy == "local-only" and not request["userPolicy"].get("localModelsAllowed", False):
        return "local-disallowed"
    if _is_critical_class_required(request):
        if model_class not in CRITICAL_REVIEW_CLASSES:
            return "critical-review-class-required"
        if model_class == "local-strong-review":
            return _local_strong_review_rejection(binding, request)
        if binding.get("calibrationStatus") not in {"PASSED", "UNKNOWN"}:
            return "critical-review-calibration-failed"
    return None


def _local_strong_review_rejection(binding: dict[str, Any], request: dict[str, Any]) -> str | None:
    capabilities = set(binding.get("capabilities", []))
    if "deep-review" not in capabilities:
        return "deep-review-missing"
    if binding.get("jsonReliability") != "strict":
        return "strict-json-required"
    if "tool-use" in request["capabilityRequirements"] and binding.get("toolUse") != "supported":
        return "tool-use-required"
    if binding.get("usageAccounting") != "host-attested":
        return "usage-attestation-required"
    if binding.get("calibrationStatus") != "PASSED":
        return "live-calibration-required"
    if (
        binding.get("contextWindow") in {"4k-strict", "8k"}
        and binding.get("reviewStrategy") != "large-context-or-sliced-review"
    ):
        return "review-strategy-required"
    return None


def _max_billable_tokens(request: dict[str, Any], profile: dict[str, Any]) -> int:
    if request["maxBillableTokens"] is not None:
        return int(request["maxBillableTokens"])
    token_budgets = profile.get("tokenBudgets", DEFAULT_TOKEN_BUDGETS)
    tier_budgets = token_budgets.get(request["sddTier"], DEFAULT_TOKEN_BUDGETS[request["sddTier"]])
    value = tier_budgets.get(request["budgetClass"], tier_budgets.get("normal"))
    if not isinstance(value, int):
        return DEFAULT_TOKEN_BUDGETS[request["sddTier"]]["normal"]
    return value


def _reason_codes(
    request: dict[str, Any],
    selected: str,
    candidate: str,
    critical: bool,
    rejections: list[dict[str, Any]],
    escalation_reasons: list[str],
) -> list[str]:
    reasons = [f"tier-{request['sddTier'].lower()}", f"phase-{request['phase']}", f"policy-{request['routingPolicy']}"]
    if selected == "no-model":
        reasons.append("deterministic-no-model")
    if selected != candidate:
        reasons.append(f"fallback-from-{candidate}")
    if critical:
        reasons.append("critical-review")
    if _local_only(request):
        reasons.append("local-only")
    if request["targetContextWindow"] in {"4k-strict", "8k"}:
        reasons.append(f"context-{request['targetContextWindow']}")
    if request.get("lifecycleMode") is not None:
        reasons.append(f"lifecycle-mode-{request['lifecycleMode']}")
    if request.get("qualityFloor") is not None:
        reasons.append(f"quality-floor-{request['qualityFloor']}")
    for risk in sorted(_active_risks(request)):
        reasons.append(f"risk-{risk}")
    if rejections:
        reasons.append("host-binding-filtered")
    reasons.extend(escalation_reasons)
    return reasons


def _escalation_summary(
    request: dict[str, Any],
    base_candidate: str,
    candidate: str,
    selected: str,
    escalation_reasons: list[str],
) -> dict[str, Any]:
    signals = request.get("failureSignals", {})
    step = _ladder_step(selected)
    optional_cross_check = (
        signals.get("failureClass") in HIGH_RISK_FAILURE_CLASSES
        or bool(request["riskFlags"].get("security"))
        or "repeated-failure-stronger-review" in escalation_reasons
    )
    return {
        "schemaVersion": "agent-progressive-escalation-decision.v1",
        "status": "PASS",
        "evidenceBacked": bool(signals),
        "fromModelClass": base_candidate,
        "candidateModelClass": candidate,
        "selectedModelClass": selected,
        "ladderStep": step,
        "escalated": _rank(candidate) > _rank(base_candidate) or selected != base_candidate,
        "reasonCodes": list(escalation_reasons),
        "failureClass": signals.get("failureClass"),
        "retryCount": signals.get("retryCount", 0),
        "remediationLoops": signals.get("remediationLoops", 0),
        "optionalCrossCheckRecommended": optional_cross_check,
        "downgradeBlocked": "no-downgrade-after-failure" in escalation_reasons,
        "qualityFloorPreserved": True,
        "providerModelNamesInCore": False,
    }


def _is_critical_review(request: dict[str, Any], profile: dict[str, Any]) -> bool:
    phase = request["phase"]
    configured = set(profile.get("criticalReviewPhases", [])) or DEFAULT_CRITICAL_PHASES
    if phase in configured:
        return True
    if request["sddTier"] == "S2" and phase in {"s2-specification", "independent-review", "final-audit"}:
        return True
    return phase.endswith("-review") and any(
        request["riskFlags"].get(key) for key in ("security", "performance", "architecture")
    )


def _is_critical_class_required(request: dict[str, Any]) -> bool:
    if request["phase"] in DEFAULT_CRITICAL_PHASES:
        return True
    if request["sddTier"] == "S2" and request["phase"] in {"s2-specification", "independent-review", "final-audit"}:
        return True
    return any(request["riskFlags"].get(key) for key in ("security", "performance")) and request["phase"].endswith(
        "-review"
    )


def _local_only(request: dict[str, Any]) -> bool:
    policy = request["userPolicy"]
    return request["routingPolicy"] == "local-only" or (
        bool(policy.get("localModelsAllowed", False)) and not bool(policy.get("cloudModelsAllowed", True))
    )


def _active_risks(request: dict[str, Any]) -> set[str]:
    return {RISK_NAME_MAP.get(key, key) for key, value in request["riskFlags"].items() if value}


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-model-route-request", f"{key} is required")
    return value


def _rank(model_class: str) -> int:
    return MODEL_CLASS_RANK.get(model_class, 99)


def _ladder_step(model_class: str) -> str:
    if model_class == "no-model":
        return "no-model"
    if model_class in {"budget", "local-compact"}:
        return "local-small-packet"
    if model_class in {"standard-code", "local-standard-code"}:
        return "standard-implementation"
    if model_class in {"strong-reasoning", "local-strong-review"}:
        return "stronger-review"
    return "optional-cross-check"


def _local_equivalent(model_class: str) -> str:
    if model_class in {"strong-reasoning", "specialist-review"}:
        return "local-strong-review"
    if model_class == "standard-code":
        return "local-standard-code"
    if model_class == "budget":
        return "local-compact"
    return model_class


def _non_negative_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError("invalid-model-route-request", f"{field} must be a non-negative integer")
    return value


def _optional_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise LifecycleError("invalid-model-route-request", f"{field} must be a list of strings")
    return list(value)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _forbidden_failure_signal_paths(value: Any, prefix: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            normalized = key.replace("_", "").replace("-", "").lower()
            if normalized in FORBIDDEN_FAILURE_SIGNAL_KEYS:
                found.append(path)
            found.extend(_forbidden_failure_signal_paths(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_forbidden_failure_signal_paths(item, f"{prefix}[{index}]"))
    return found
