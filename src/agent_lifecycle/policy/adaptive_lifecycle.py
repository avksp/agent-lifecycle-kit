"""Adaptive lifecycle policy decisions from provider-neutral inputs."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.metrics.recommendations import validate_lifecycle_baselines
from agent_lifecycle.policy.quality_floor import MODES, max_mode, mode_index, resolve_quality_floor
from agent_lifecycle.quality.failure_classification import FAILURE_CLASSES, HIGH_RISK_FAILURE_CLASSES

ADAPTIVE_REQUEST_SCHEMA = "agent-adaptive-lifecycle-policy-request.v1"
ADAPTIVE_DECISION_SCHEMA = "agent-adaptive-lifecycle-policy-decision.v1"
ADAPTIVE_VALIDATION_SCHEMA = "agent-adaptive-lifecycle-policy-decision-validation.v1"
RESOURCE_BASIS = "tokens-and-resources"
SDD_TIERS = {"S0", "S1", "S2"}
BUDGET_MODES = {"local", "subscription", "metered"}
FLAKE_STATUSES = {"stable-fail", "stable-pass", "flaky", "inconclusive"}
FORBIDDEN_NEUTRAL_KEYS = {
    "apikey",
    "auth",
    "authheader",
    "credential",
    "credentials",
    "model",
    "modelid",
    "modelname",
    "password",
    "provider",
    "providerid",
    "providermodel",
    "providermodelhash",
    "providername",
    "secret",
}


def build_adaptive_lifecycle_decision(request: dict[str, Any], baseline_profile: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic advisory-or-opt-in lifecycle mode decision."""

    normalized, blockers = _normalize_request(request)
    blockers.extend(_neutrality_blockers(request))
    blockers.extend(_monetary_blockers(request, budget_mode=normalized["budgetMode"]))
    baseline_validation = validate_lifecycle_baselines(baseline_profile)
    if baseline_validation["status"] != "PASS":
        blockers.extend({"code": "adaptive-baseline-invalid", "blocker": item} for item in baseline_validation["blockers"])

    floor_decision = resolve_quality_floor(
        task_shape=normalized["taskShape"],
        baseline_profile=baseline_profile,
        sdd_tier=normalized["sddTier"],
        risk_flags=normalized["riskFlags"],
        required_evidence=normalized["requiredEvidence"],
    )
    if floor_decision["status"] != "PASS":
        blockers.extend({"code": "adaptive-quality-floor-invalid", "blocker": item} for item in floor_decision["blockers"])

    recommended, reasons = _recommended_mode(normalized, baseline_profile, floor_decision["qualityFloor"])
    apply_automatically = normalized["automaticSelectionEnabled"] and not blockers
    body = {
        "schemaVersion": ADAPTIVE_DECISION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "requestId": normalized["requestId"],
        "taskShape": normalized["taskShape"],
        "sddTier": normalized["sddTier"],
        "currentMode": normalized["currentMode"],
        "recommendedMode": recommended,
        "selectedMode": recommended,
        "qualityFloor": floor_decision["qualityFloor"],
        "qualityFloorPreserved": mode_index(recommended) >= mode_index(floor_decision["qualityFloor"]),
        "automaticSelectionEnabled": normalized["automaticSelectionEnabled"],
        "applyAutomatically": apply_automatically,
        "advisoryOnly": not apply_automatically,
        "reasonCodes": [*floor_decision["reasonCodes"], *reasons],
        "neutralInputs": _neutral_inputs(normalized, monetary_keys=_monetary_keys(request)),
        "resourceBasis": RESOURCE_BASIS,
        "monetaryFieldsUsed": False,
        "providerModelNamesInCore": False,
        "blockers": blockers,
        "qualityFloorDecision": floor_decision,
        "baselineValidation": baseline_validation,
        "requestDigest": canonical_digest(request),
        "baselineProfileDigest": canonical_digest(baseline_profile),
        "productionPromotionClaimed": False,
    }
    return {**body, "decisionDigest": canonical_digest(body)}


def validate_adaptive_lifecycle_decision(decision: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise LifecycleError("invalid-adaptive-lifecycle-decision", "adaptive lifecycle decision must be an object")
    blockers: list[dict[str, Any]] = []
    if decision.get("schemaVersion") != ADAPTIVE_DECISION_SCHEMA:
        blockers.append({"code": "adaptive-decision-schema-invalid"})
    if decision.get("status") not in {"PASS", "FAIL"}:
        blockers.append({"code": "adaptive-decision-status-invalid"})
    floor = decision.get("qualityFloor")
    selected = decision.get("selectedMode")
    recommended = decision.get("recommendedMode")
    for field, value in [("qualityFloor", floor), ("selectedMode", selected), ("recommendedMode", recommended)]:
        if value not in MODES:
            blockers.append({"code": "adaptive-decision-mode-invalid", "field": field, "mode": value})
    if floor in MODES and selected in MODES and mode_index(selected) < mode_index(floor):
        blockers.append({"code": "adaptive-decision-selected-below-floor", "selectedMode": selected, "qualityFloor": floor})
    if floor in MODES and recommended in MODES and mode_index(recommended) < mode_index(floor):
        blockers.append({"code": "adaptive-decision-recommended-below-floor", "recommendedMode": recommended, "qualityFloor": floor})
    if decision.get("qualityFloorPreserved") is not True:
        blockers.append({"code": "adaptive-decision-quality-floor-not-preserved"})
    if decision.get("resourceBasis") != RESOURCE_BASIS:
        blockers.append({"code": "adaptive-decision-resource-basis-invalid"})
    if decision.get("monetaryFieldsUsed") is not False:
        blockers.append({"code": "adaptive-decision-monetary-fields-used"})
    if decision.get("providerModelNamesInCore") is not False:
        blockers.append({"code": "adaptive-decision-provider-model-core"})
    if decision.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "adaptive-decision-production-claim"})
    if not isinstance(decision.get("automaticSelectionEnabled"), bool):
        blockers.append({"code": "adaptive-decision-auto-flag-invalid"})
    if not isinstance(decision.get("applyAutomatically"), bool):
        blockers.append({"code": "adaptive-decision-apply-flag-invalid"})
    if not isinstance(decision.get("advisoryOnly"), bool):
        blockers.append({"code": "adaptive-decision-advisory-flag-invalid"})
    if decision.get("applyAutomatically") is True and decision.get("automaticSelectionEnabled") is not True:
        blockers.append({"code": "adaptive-decision-auto-apply-without-opt-in"})
    if decision.get("applyAutomatically") is True and decision.get("advisoryOnly") is True:
        blockers.append({"code": "adaptive-decision-auto-apply-advisory"})
    embedded_blockers = decision.get("blockers")
    if not isinstance(embedded_blockers, list) or not all(isinstance(item, dict) for item in embedded_blockers):
        blockers.append({"code": "adaptive-decision-blockers-invalid"})
        embedded_blockers = []
    if decision.get("status") == "PASS" and embedded_blockers:
        blockers.append({"code": "adaptive-decision-pass-with-blockers"})
    if decision.get("status") == "FAIL" and not embedded_blockers:
        blockers.append({"code": "adaptive-decision-fail-without-blockers"})
    expected_digest = canonical_digest({key: value for key, value in decision.items() if key != "decisionDigest"})
    if decision.get("decisionDigest") != expected_digest:
        blockers.append({"code": "adaptive-decision-digest-mismatch"})
    body = {
        "schemaVersion": ADAPTIVE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "decisionStatus": decision.get("status") if isinstance(decision.get("status"), str) else None,
        "recommendedMode": recommended if recommended in MODES else None,
        "selectedMode": selected if selected in MODES else None,
        "qualityFloor": floor if floor in MODES else None,
        "qualityFloorPreserved": decision.get("qualityFloorPreserved") is True,
        "applyAutomatically": decision.get("applyAutomatically") is True,
        "advisoryOnly": decision.get("advisoryOnly") is True,
        "blockers": blockers,
        "decisionDigest": decision.get("decisionDigest") if isinstance(decision.get("decisionDigest"), str) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_adaptive_lifecycle_decision_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("decisionStatus") != "PASS":
        raise LifecycleError("adaptive-lifecycle-decision-validation-failed", "adaptive lifecycle decision did not pass", {"validation": validation})
    return validation


def small_model_packet_eligibility(decision: dict[str, Any]) -> dict[str, Any]:
    """Return whether a small-model packet surface is allowed by the decision."""

    validation = validate_adaptive_lifecycle_decision(decision)
    blockers = []
    if validation.get("status") != "PASS" or validation.get("decisionStatus") != "PASS":
        blockers.append({"code": "small-model-adaptive-decision-invalid", "validation": validation})
    floor = decision.get("qualityFloor")
    if floor not in {"light", "standard"}:
        blockers.append({"code": "small-model-quality-floor-blocked", "qualityFloor": floor})
    body = {
        "status": "PASS" if not blockers else "FAIL",
        "decisionDigest": decision.get("decisionDigest"),
        "qualityFloor": floor,
        "recommendedMode": decision.get("recommendedMode"),
        "smallModelPacketEligible": not blockers,
        "advisoryOnly": decision.get("advisoryOnly") is True,
        "blockers": blockers,
    }
    return {**body, "eligibilityDigest": canonical_digest(body)}


def _normalize_request(request: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(request, dict):
        raise LifecycleError("invalid-adaptive-lifecycle-request", "adaptive lifecycle request must be an object")
    if request.get("schemaVersion") != ADAPTIVE_REQUEST_SCHEMA:
        blockers.append({"code": "adaptive-request-schema-invalid"})
    task_shape = _string(request.get("taskShape"), default="feature")
    if "taskShape" not in request:
        blockers.append({"code": "adaptive-request-task-shape-missing"})
    sdd_tier = _string(request.get("sddTier"), default="S1")
    if sdd_tier not in SDD_TIERS:
        blockers.append({"code": "adaptive-request-sdd-tier-invalid", "sddTier": sdd_tier})
        sdd_tier = "S1"
    risk_flags = _risk_list(request.get("riskFlags"))
    required_evidence = _string_list(request.get("requiredEvidence", []))
    prior_attempts = _non_negative_int(request.get("priorAttempts", 0), field="priorAttempts", blockers=blockers)
    context_tokens = _non_negative_int(request.get("contextTokens", 0), field="contextTokens", blockers=blockers)
    resource_caps = _resource_caps(request.get("resourceCaps", {}), blockers)
    failure_signals = _failure_signals(request.get("failureSignals", {}), blockers)
    budget_mode = _string(request.get("budgetMode"), default="local")
    if budget_mode not in BUDGET_MODES:
        blockers.append({"code": "adaptive-request-budget-mode-invalid", "budgetMode": budget_mode})
        budget_mode = "local"
    current_mode = request.get("currentMode")
    if current_mode is not None and current_mode not in MODES:
        blockers.append({"code": "adaptive-request-current-mode-invalid", "currentMode": current_mode})
        current_mode = None
    automatic = request.get("automaticSelectionEnabled", False)
    if not isinstance(automatic, bool):
        blockers.append({"code": "adaptive-request-auto-flag-invalid"})
        automatic = False
    return (
        {
            "requestId": request.get("requestId") if isinstance(request.get("requestId"), str) and request.get("requestId") else None,
            "taskShape": task_shape,
            "sddTier": sdd_tier,
            "riskFlags": risk_flags,
            "requiredEvidence": required_evidence,
            "priorAttempts": prior_attempts,
            "contextTokens": context_tokens,
            "resourceCaps": resource_caps,
            "failureSignals": failure_signals,
            "budgetMode": budget_mode,
            "currentMode": current_mode,
            "automaticSelectionEnabled": automatic,
        },
        blockers,
    )


def _recommended_mode(normalized: dict[str, Any], baseline_profile: dict[str, Any], quality_floor: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    shape = {}
    shapes = baseline_profile.get("taskShapes") if isinstance(baseline_profile, dict) else {}
    if isinstance(shapes, dict) and isinstance(shapes.get(normalized["taskShape"]), dict):
        shape = shapes[normalized["taskShape"]]
    default_mode = shape.get("defaultMode") if shape.get("defaultMode") in MODES else "standard"
    target = max_mode(default_mode, quality_floor)
    reasons.append(f"default-mode-{default_mode}")
    if normalized["priorAttempts"] >= 2:
        target = max_mode(target, "strict")
        reasons.append("retry-escalation")
    failure_signals = normalized.get("failureSignals", {})
    failure_class = failure_signals.get("failureClass")
    if failure_class in {"api-contract", "serialization", "permission", "migration", "performance"}:
        target = max_mode(target, "standard")
        reasons.append(f"failure-class-{failure_class}-escalation")
    if failure_class in HIGH_RISK_FAILURE_CLASSES or failure_class == "flaky-test" or failure_signals.get("flakeStatus") == "flaky":
        target = max_mode(target, "strict")
        reasons.append(f"failure-class-{failure_class or 'flake'}-strict-escalation")
    if failure_signals.get("validationStatus") in {"FAIL", "ERROR", "BLOCKED", "REJECTED"}:
        target = max_mode(target, "standard")
        reasons.append("validation-failure-escalation")
    if int(failure_signals.get("retryCount", 0)) >= 2 or int(failure_signals.get("remediationLoops", 0)) >= 2:
        target = max_mode(target, "strict")
        reasons.append("failure-loop-strict-escalation")
    if normalized["currentMode"] in MODES and (normalized["priorAttempts"] > 0 or failure_signals):
        raised = max_mode(target, normalized["currentMode"])
        if raised != target:
            reasons.append("no-downgrade-after-failure")
        target = raised
    if normalized["contextTokens"] >= 64000:
        target = max_mode(target, "strict")
        reasons.append("large-context-escalation")
    elif normalized["contextTokens"] >= 32000:
        target = max_mode(target, "standard")
        reasons.append("medium-context-floor")
    caps = normalized["resourceCaps"]
    if caps.get("maxInvocations") == 1 and quality_floor in {"light", "standard"} and not _high_risk(normalized, shape):
        target = quality_floor
        reasons.append("resource-cap-tight")
    return max_mode(target, quality_floor), reasons


def _neutral_inputs(normalized: dict[str, Any], *, monetary_keys: list[str]) -> dict[str, Any]:
    caps = normalized["resourceCaps"]
    return {
        "taskShape": normalized["taskShape"],
        "sddTier": normalized["sddTier"],
        "riskFlags": list(normalized["riskFlags"]),
        "requiredEvidence": list(normalized["requiredEvidence"]),
        "priorAttempts": normalized["priorAttempts"],
        "contextTokens": normalized["contextTokens"],
        "resourceCaps": {key: caps[key] for key in sorted(caps) if key in {"maxInvocations", "maxWallSeconds", "maxBillableTokens"}},
        "failureSignals": dict(normalized["failureSignals"]),
        "budgetMode": normalized["budgetMode"],
        "automaticSelectionEnabled": normalized["automaticSelectionEnabled"],
        "monetaryMetadataKeys": monetary_keys,
    }


def _resource_caps(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        blockers.append({"code": "adaptive-request-resource-caps-invalid"})
        return {}
    caps = dict(value)
    for field in ("maxInvocations", "maxWallSeconds", "maxBillableTokens"):
        if field in caps:
            caps[field] = _non_negative_int(caps[field], field=f"resourceCaps.{field}", blockers=blockers)
    return caps


def _failure_signals(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        blockers.append({"code": "adaptive-request-failure-signals-invalid"})
        return {}
    failure_class = value.get("failureClass")
    if failure_class is not None and failure_class not in FAILURE_CLASSES:
        blockers.append({"code": "adaptive-request-failure-class-invalid", "failureClass": failure_class})
        failure_class = None
    confidence = value.get("confidence")
    if confidence is not None and confidence not in {"LOW", "MEDIUM", "HIGH"}:
        blockers.append({"code": "adaptive-request-failure-confidence-invalid", "confidence": confidence})
        confidence = None
    flake_status = value.get("flakeStatus")
    if flake_status is not None and flake_status not in FLAKE_STATUSES:
        blockers.append({"code": "adaptive-request-flake-status-invalid", "flakeStatus": flake_status})
        flake_status = None
    validation_status = value.get("validationStatus")
    if validation_status is not None and not isinstance(validation_status, str):
        blockers.append({"code": "adaptive-request-validation-status-invalid"})
        validation_status = None
    classification_digest = value.get("classificationDigest")
    if classification_digest is not None and not _is_digest(classification_digest):
        blockers.append({"code": "adaptive-request-classification-digest-invalid"})
        classification_digest = None
    return {
        "failureClass": failure_class,
        "confidence": confidence,
        "retryCount": _non_negative_int(value.get("retryCount", 0), field="failureSignals.retryCount", blockers=blockers),
        "remediationLoops": _non_negative_int(value.get("remediationLoops", 0), field="failureSignals.remediationLoops", blockers=blockers),
        "validationStatus": validation_status,
        "flakeStatus": flake_status,
        "classificationDigest": classification_digest,
    }


def _monetary_blockers(value: Any, *, budget_mode: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for path, item in _walk(value):
        key = path.rsplit(".", 1)[-1]
        if _is_monetary_key(key) and item is not None and budget_mode != "metered":
            blockers.append({"code": "adaptive-request-monetary-field-not-metered", "path": path})
    return blockers


def _monetary_keys(value: Any) -> list[str]:
    return sorted({path for path, item in _walk(value) if _is_monetary_key(path.rsplit(".", 1)[-1]) and item is not None})


def _neutrality_blockers(value: Any) -> list[dict[str, Any]]:
    blockers = []
    for path, _item in _walk(value):
        key = path.rsplit(".", 1)[-1]
        normalized = key.replace("_", "").replace("-", "").lower()
        if normalized in FORBIDDEN_NEUTRAL_KEYS:
            blockers.append({"code": "adaptive-request-provider-model-key", "path": path})
    return blockers


def _walk(value: Any, prefix: str = "$") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            rows.append((path, item))
            rows.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(_walk(item, f"{prefix}[{index}]"))
    return rows


def _is_monetary_key(key: str) -> bool:
    normalized = key.replace("_", "").replace("-", "").lower()
    return "usd" in normalized or "cost" in normalized


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _risk_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return sorted(str(key) for key, active in value.items() if active)
    if isinstance(value, list):
        return sorted({item for item in value if isinstance(item, str) and item})
    return []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _string(value: Any, *, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _non_negative_int(value: Any, *, field: str, blockers: list[dict[str, Any]]) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        blockers.append({"code": "adaptive-request-non-negative-int-invalid", "field": field, "value": value})
        return 0
    return value


def _high_risk(normalized: dict[str, Any], shape: dict[str, Any]) -> bool:
    if shape.get("highRisk") is True:
        return True
    return bool(set(normalized["riskFlags"]).intersection({"security", "contracts", "adapter", "architecture", "release"}))
