"""Optional cross-check profile and receipt helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

CROSS_CHECK_PROFILE_SCHEMA = "agent-cross-check-profile.v1"
CROSS_CHECK_PROFILE_VALIDATION_SCHEMA = "agent-cross-check-profile-validation.v1"
CROSS_CHECK_RECEIPT_SCHEMA = "agent-cross-check-receipt.v1"
CROSS_CHECK_RECEIPT_VALIDATION_SCHEMA = "agent-cross-check-receipt-validation.v1"

RECEIPT_STATUSES = {"PASS", "FAIL", "SKIPPED"}
DEFAULT_RISK_TRIGGERS = ("S2", "security", "release", "high-risk", "bugfix", "regression")
RESOURCE_CAP_KEYS = {"maxInvocations", "maxInputTokens", "maxOutputTokens", "maxWallSeconds"}
USAGE_KEYS = {"invocations", "inputTokens", "outputTokens", "wallSeconds"}
MONEY_KEYS = {"costUsd", "cost_usd", "usd", "budgetUsd", "maxUsd", "money", "monetary"}


def build_cross_check_profile(
    *,
    profile_id: str = "optional-cross-check",
    budget_cap: dict[str, int] | None = None,
    risk_triggers: list[str] | None = None,
    live_calls_allowed: bool = False,
) -> dict[str, Any]:
    """Build the generic optional cross-check profile."""

    cap = budget_cap or {"maxInvocations": 1, "maxInputTokens": 12000, "maxOutputTokens": 4000, "maxWallSeconds": 180}
    body = {
        "schemaVersion": CROSS_CHECK_PROFILE_SCHEMA,
        "profileId": _required_string(profile_id, label="profileId", code="invalid-cross-check-profile"),
        "status": "OPTIONAL",
        "enabledByDefault": False,
        "activationMode": "opt-in",
        "advisoryByDefault": True,
        "blockingRequiresPlanOptIn": True,
        "requiresExplicitActivation": True,
        "liveCallsAllowed": bool(live_calls_allowed),
        "riskTriggers": _string_list(list(risk_triggers or DEFAULT_RISK_TRIGGERS), label="riskTriggers", code="invalid-cross-check-profile"),
        "budgetCap": _resource_cap(cap, code="invalid-cross-check-profile"),
        "budgetUnits": "tokens-and-resources",
        "monetaryCostCanonical": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


def validate_cross_check_profile(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        raise LifecycleError("invalid-cross-check-profile", "cross-check profile must be an object")
    if profile.get("schemaVersion") != CROSS_CHECK_PROFILE_SCHEMA:
        blockers.append({"code": "cross-check-profile-schema-invalid"})
    if not isinstance(profile.get("profileId"), str) or not profile["profileId"]:
        blockers.append({"code": "cross-check-profile-id-missing"})
    if profile.get("status") != "OPTIONAL":
        blockers.append({"code": "cross-check-profile-not-optional"})
    if profile.get("enabledByDefault") is not False:
        blockers.append({"code": "cross-check-profile-default-enabled"})
    if profile.get("activationMode") != "opt-in":
        blockers.append({"code": "cross-check-profile-not-opt-in"})
    if profile.get("advisoryByDefault") is not True:
        blockers.append({"code": "cross-check-profile-not-advisory"})
    if profile.get("blockingRequiresPlanOptIn") is not True:
        blockers.append({"code": "cross-check-profile-blocking-not-plan-gated"})
    if profile.get("requiresExplicitActivation") is not True:
        blockers.append({"code": "cross-check-profile-activation-not-explicit"})
    if not isinstance(profile.get("liveCallsAllowed"), bool):
        blockers.append({"code": "cross-check-profile-live-calls-invalid"})
    _validate_string_list(profile.get("riskTriggers"), "cross-check-profile-risk-triggers-invalid", blockers)
    _validate_resource_cap(profile.get("budgetCap"), blockers)
    if profile.get("budgetUnits") != "tokens-and-resources":
        blockers.append({"code": "cross-check-profile-budget-units-invalid"})
    if profile.get("monetaryCostCanonical") is not False:
        blockers.append({"code": "cross-check-profile-money-canonical"})
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "cross-check-profile-production-claim"})
    expected_digest = canonical_digest({key: value for key, value in profile.items() if key != "profileDigest"})
    if profile.get("profileDigest") != expected_digest:
        blockers.append({"code": "cross-check-profile-digest-mismatch"})
    body = {
        "schemaVersion": CROSS_CHECK_PROFILE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "profileId": profile.get("profileId") if isinstance(profile.get("profileId"), str) else None,
        "enabledByDefault": profile.get("enabledByDefault") if isinstance(profile.get("enabledByDefault"), bool) else None,
        "blockers": blockers,
        "profileDigest": profile.get("profileDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_cross_check_receipt(
    *,
    profile: dict[str, Any],
    subject: dict[str, Any],
    reviewer: dict[str, Any],
    budget_usage: dict[str, int],
    findings: list[dict[str, Any]] | None = None,
    blocking: bool = False,
    live_calls_started: bool = False,
    evidence_ids: list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build an optional cross-check receipt with a hard resource cap."""

    profile_validation = validate_cross_check_profile(profile)
    usage = _budget_usage(budget_usage, code="invalid-cross-check-receipt")
    cap = profile.get("budgetCap") if isinstance(profile, dict) and isinstance(profile.get("budgetCap"), dict) else {}
    cap_blockers = _budget_blockers(usage, cap)
    if live_calls_started and profile.get("liveCallsAllowed") is not True:
        cap_blockers.append({"code": "cross-check-live-call-not-allowed"})
    if blocking and subject.get("blockingCrossCheckRequired") is not True:
        cap_blockers.append({"code": "cross-check-blocking-without-plan-opt-in"})
    if profile_validation["status"] != "PASS":
        cap_blockers.append({"code": "cross-check-profile-invalid"})
    body = {
        "schemaVersion": CROSS_CHECK_RECEIPT_SCHEMA,
        "status": _enum(status or ("FAIL" if cap_blockers else "PASS"), RECEIPT_STATUSES, label="status", code="invalid-cross-check-receipt"),
        "profileId": profile.get("profileId"),
        "profileDigest": profile.get("profileDigest"),
        "subject": dict(subject),
        "reviewer": dict(reviewer),
        "findings": list(findings or []),
        "blocking": bool(blocking),
        "advisory": not blocking,
        "budgetCap": dict(cap),
        "budgetUsage": usage,
        "liveCallsStarted": bool(live_calls_started),
        "evidenceIds": _string_list(evidence_ids or [], label="evidenceIds", code="invalid-cross-check-receipt", allow_empty=True),
        "blockers": cap_blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_cross_check_receipt(receipt: dict[str, Any], *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-cross-check-receipt", "cross-check receipt must be an object")
    if receipt.get("schemaVersion") != CROSS_CHECK_RECEIPT_SCHEMA:
        blockers.append({"code": "cross-check-receipt-schema-invalid"})
    status = receipt.get("status")
    if status not in RECEIPT_STATUSES:
        blockers.append({"code": "cross-check-receipt-status-invalid", "status": status})
    if not isinstance(receipt.get("profileId"), str) or not receipt["profileId"]:
        blockers.append({"code": "cross-check-receipt-profile-id-missing"})
    _check_digest(receipt.get("profileDigest"), "cross-check-receipt-profile-digest-invalid", blockers)
    if profile is not None:
        profile_validation = validate_cross_check_profile(profile)
        if profile_validation["status"] != "PASS":
            blockers.append({"code": "cross-check-profile-invalid"})
        if receipt.get("profileDigest") != profile.get("profileDigest"):
            blockers.append({"code": "cross-check-profile-digest-mismatch"})
        if receipt.get("liveCallsStarted") is True and profile.get("liveCallsAllowed") is not True:
            blockers.append({"code": "cross-check-live-call-not-allowed"})
    subject = receipt.get("subject")
    if not isinstance(subject, dict) or not subject:
        blockers.append({"code": "cross-check-subject-invalid"})
        subject = {}
    if receipt.get("blocking") is True and subject.get("blockingCrossCheckRequired") is not True:
        blockers.append({"code": "cross-check-blocking-without-plan-opt-in"})
    if receipt.get("advisory") is not (receipt.get("blocking") is not True):
        blockers.append({"code": "cross-check-advisory-mismatch"})
    if not isinstance(receipt.get("reviewer"), dict) or not receipt["reviewer"]:
        blockers.append({"code": "cross-check-reviewer-invalid"})
    if not isinstance(receipt.get("findings", []), list) or not all(isinstance(item, dict) for item in receipt.get("findings", [])):
        blockers.append({"code": "cross-check-findings-invalid"})
    cap = receipt.get("budgetCap")
    usage = receipt.get("budgetUsage")
    _validate_resource_cap(cap, blockers)
    _validate_budget_usage(usage, blockers)
    if isinstance(cap, dict) and isinstance(usage, dict):
        blockers.extend(_budget_blockers(usage, cap))
    if not isinstance(receipt.get("liveCallsStarted"), bool):
        blockers.append({"code": "cross-check-live-calls-started-invalid"})
    _check_string_list(receipt.get("evidenceIds", []), "cross-check-evidence-ids-invalid", blockers, allow_empty=True)
    _check_object_list(receipt.get("blockers", []), "cross-check-blockers-invalid", blockers)
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "cross-check-production-claim"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "cross-check-receipt-digest-mismatch"})
    body = {
        "schemaVersion": CROSS_CHECK_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": status if isinstance(status, str) else None,
        "profileId": receipt.get("profileId") if isinstance(receipt.get("profileId"), str) else None,
        "blocking": receipt.get("blocking") if isinstance(receipt.get("blocking"), bool) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_cross_check_profile_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("cross-check-profile-validation-failed", "cross-check profile validation failed", {"validation": validation})
    return validation


def require_cross_check_receipt_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
        raise LifecycleError("cross-check-receipt-validation-failed", "cross-check receipt did not pass", {"validation": validation})
    return validation


def _budget_blockers(usage: dict[str, Any], cap: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    cap_map = {
        "invocations": cap.get("maxInvocations"),
        "inputTokens": cap.get("maxInputTokens"),
        "outputTokens": cap.get("maxOutputTokens"),
        "wallSeconds": cap.get("maxWallSeconds"),
    }
    for key, value in usage.items():
        limit = cap_map.get(key)
        if isinstance(limit, int) and value > limit:
            blockers.append({"code": "cross-check-budget-cap-exceeded", "field": key, "limit": limit, "actual": value})
    return blockers


def _resource_cap(value: dict[str, int], *, code: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "budgetCap must be an object")
    result: dict[str, int] = {}
    for key in value:
        if key in MONEY_KEYS:
            raise LifecycleError(code, "budgetCap must not use monetary limits")
        if key not in RESOURCE_CAP_KEYS:
            raise LifecycleError(code, "budgetCap field is unsupported", {"field": key})
        item = value[key]
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise LifecycleError(code, "budgetCap values must be positive integers", {"field": key})
        result[key] = item
    if not result:
        raise LifecycleError(code, "budgetCap must not be empty")
    return dict(sorted(result.items()))


def _budget_usage(value: dict[str, int], *, code: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise LifecycleError(code, "budgetUsage must be an object")
    result: dict[str, int] = {}
    for key in value:
        if key in MONEY_KEYS:
            raise LifecycleError(code, "budgetUsage must not use monetary fields")
        if key not in USAGE_KEYS:
            raise LifecycleError(code, "budgetUsage field is unsupported", {"field": key})
        item = value[key]
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise LifecycleError(code, "budgetUsage values must be non-negative integers", {"field": key})
        result[key] = item
    return {key: result.get(key, 0) for key in sorted(USAGE_KEYS)}


def _validate_resource_cap(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict) or not value:
        blockers.append({"code": "cross-check-budget-cap-invalid"})
        return
    for key, item in value.items():
        if key in MONEY_KEYS:
            blockers.append({"code": "cross-check-money-cap-not-allowed", "field": key})
        elif key not in RESOURCE_CAP_KEYS:
            blockers.append({"code": "cross-check-budget-cap-unsupported", "field": key})
        elif not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            blockers.append({"code": "cross-check-budget-cap-value-invalid", "field": key})


def _validate_budget_usage(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "cross-check-budget-usage-invalid"})
        return
    for key, item in value.items():
        if key in MONEY_KEYS:
            blockers.append({"code": "cross-check-money-usage-not-allowed", "field": key})
        elif key not in USAGE_KEYS:
            blockers.append({"code": "cross-check-budget-usage-unsupported", "field": key})
        elif not isinstance(item, int) or isinstance(item, bool) or item < 0:
            blockers.append({"code": "cross-check-budget-usage-value-invalid", "field": key})


def _required_string(value: Any, *, label: str, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} is required")
    return value


def _string_list(value: Any, *, label: str, code: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(code, f"{label} must be a list of strings")
    return list(value)


def _validate_string_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": code})


def _enum(value: Any, allowed: set[str], *, label: str, code: str) -> str:
    if value not in allowed:
        raise LifecycleError(code, f"{label} is unsupported", {label: value})
    return str(value)


def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, str) or len(value) != 64:
        blockers.append({"code": code})


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool = False) -> None:
    if not isinstance(value, list) or (not allow_empty and not value) or not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": code})


def _check_object_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        blockers.append({"code": code})
