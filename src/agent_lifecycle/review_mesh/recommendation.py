"""Deterministic Review Mesh recommendation advisor."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, sha256_hex
from agent_lifecycle.contracts.review_mesh_recommendation_schemas import (
    REVIEW_MESH_RECOMMENDATION_MODES,
    REVIEW_MESH_RECOMMENDATION_SCHEMA,
)
from agent_lifecycle.contracts.review_mesh_schemas import REVIEW_MESH_MODE_IDS
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES
from agent_lifecycle.quality.cross_check import MONEY_KEYS, RESOURCE_CAP_KEYS
from agent_lifecycle.review_mesh.contracts import build_review_mesh_profile

OFF_MODE = "off"
MODE_LEADER_REVIEW = "leader-draft-multi-review"
MODE_PARALLEL_RESEARCH = "parallel-research-synthesis"
MODE_IMPLEMENTATION_AUDIT = "implementation-audit-panel"

_BUG_MARKERS = (
    "bug",
    "defect",
    "regression",
    "failing",
    "failure",
    "flaky",
    "incident",
    "ошиб",
    "баг",
    "регресс",
    "падает",
    "сбой",
)

_SECURITY_MARKERS = (
    "security",
    "vulnerability",
    "permission",
    "secret",
    "credential",
    "уязвим",
    "безопасн",
    "секрет",
    "ключ",
)

_RESEARCH_MARKERS = (
    "research",
    "investigate",
    "analysis",
    "analyze",
    "analyse",
    "compare",
    "architecture",
    "plan",
    "discovery",
    "исслед",
    "анализ",
    "проанализ",
    "сравн",
    "архитект",
    "план",
)

_IMPLEMENTATION_AUDIT_MARKERS = (
    "implementation audit",
    "audit implementation",
    "review implementation",
    "final audit",
    "task review",
    "проверка реализации",
    "аудит реализации",
    "финальный аудит",
)

_PROVIDER_MODEL_NAME_KEYS = {
    "provider",
    "providerName",
    "providerModel",
    "providerModelName",
    "model",
    "modelName",
    "modelId",
    "accountName",
}

_DEFAULT_CAP = {
    "maxInvocations": 2,
    "maxInputTokens": 12000,
    "maxOutputTokens": 4000,
    "maxWallSeconds": 900,
}

_OFF_CAP = {
    "maxInvocations": 0,
    "maxInputTokens": 0,
    "maxOutputTokens": 0,
    "maxWallSeconds": 0,
}


def recommend_review_mesh_for_text(
    text: str,
    *,
    source_label: str = "inline-task",
    sdd_tier: str | None = None,
    risk_flags: dict[str, bool] | list[str] | None = None,
) -> dict[str, Any]:
    source = {
        "kind": "TEXT",
        "label": source_label,
        "digest": sha256_hex(text.encode("utf-8")),
        "byteCount": len(text.encode("utf-8")),
        "rawTextStored": False,
    }
    return build_review_mesh_recommendation(
        text=text,
        source=source,
        sdd_tier=sdd_tier,
        risk_flags=risk_flags,
    )


def recommend_review_mesh_for_intake(intake_receipt: dict[str, Any]) -> dict[str, Any]:
    if intake_receipt.get("schemaVersion") != "agent-adapter-task-start-receipt.v1":
        raise LifecycleError("review-mesh-intake-schema-invalid", "expected agent-adapter-task-start-receipt.v1")
    input_summary = intake_receipt.get("input") if isinstance(intake_receipt.get("input"), dict) else {}
    source = {
        "kind": "INTAKE_RECEIPT",
        "label": input_summary.get("label") or intake_receipt.get("adapterId") or "adapter-task-intake",
        "digest": intake_receipt.get("receiptDigest") or canonical_digest(intake_receipt),
        "byteCount": input_summary.get("byteCount"),
        "rawTextStored": False,
    }
    return build_review_mesh_recommendation(
        source=source,
        task_shape=intake_receipt.get("detectedTaskShape") if isinstance(intake_receipt.get("detectedTaskShape"), str) else None,
        recommended_quality_profiles=list(intake_receipt.get("recommendedQualityProfiles", []))
        if isinstance(intake_receipt.get("recommendedQualityProfiles"), list)
        else [],
        pre_implementation_analysis=intake_receipt.get("preImplementationAnalysis")
        if isinstance(intake_receipt.get("preImplementationAnalysis"), dict)
        else None,
        status=intake_receipt.get("status") if isinstance(intake_receipt.get("status"), str) else None,
    )


def recommend_review_mesh_for_plan_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schemaVersion") != "agent-plan-manifest.v1":
        raise LifecycleError("review-mesh-plan-schema-invalid", "expected agent-plan-manifest.v1")
    specification = manifest.get("specification") if isinstance(manifest.get("specification"), dict) else {}
    tier_request = specification.get("tierResolutionRequest") if isinstance(specification.get("tierResolutionRequest"), dict) else {}
    source = {
        "kind": "PLAN_MANIFEST",
        "label": _manifest_package_id(manifest),
        "digest": canonical_digest(manifest),
        "byteCount": None,
        "rawTextStored": False,
    }
    return build_review_mesh_recommendation(
        text=_manifest_signal_text(manifest),
        source=source,
        sdd_tier=specification.get("tier") if isinstance(specification.get("tier"), str) else None,
        risk_flags=tier_request.get("riskFlags") if isinstance(tier_request.get("riskFlags"), dict) else None,
        status=manifest.get("status") if isinstance(manifest.get("status"), str) else None,
    )


def build_review_mesh_recommendation(
    *,
    source: dict[str, Any],
    text: str = "",
    task_shape: str | None = None,
    recommended_quality_profiles: list[str] | None = None,
    pre_implementation_analysis: dict[str, Any] | None = None,
    sdd_tier: str | None = None,
    risk_flags: dict[str, bool] | list[str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build an advisory-only Review Mesh recommendation receipt."""

    normalized_flags = _normalize_risk_flags(risk_flags)
    decision = _select_mode(
        text=text,
        task_shape=task_shape,
        recommended_quality_profiles=recommended_quality_profiles or [],
        pre_implementation_analysis=pre_implementation_analysis,
        sdd_tier=sdd_tier,
        risk_flags=normalized_flags,
        status=status,
    )
    model_hints = _model_class_hints(decision["mode"])
    body = {
        "schemaVersion": REVIEW_MESH_RECOMMENDATION_SCHEMA,
        "status": "PASS",
        "recommendedMode": decision["mode"],
        "phaseCoverage": decision["phaseCoverage"],
        "reasons": decision["reasons"],
        "skipRationale": decision["skipRationale"],
        "requiredReviewers": decision["requiredReviewers"],
        "budgetUnits": "tokens-and-resources",
        "budgetCap": _budget_cap(decision["mode"]),
        "providerNeutralModelClassHints": model_hints,
        "modelRoutingClassAvailability": {
            "source": "agent_lifecycle.model_routing.ALLOWED_MODEL_CLASSES",
            "availableClasses": sorted(ALLOWED_MODEL_CLASSES),
            "hintedClasses": model_hints,
        },
        "advisoryOnly": True,
        "requiresOperatorConfirmation": True,
        "blockingGateActivated": False,
        "assignmentsGenerated": False,
        "quorumEnforced": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "source": dict(source),
        "concreteProviderModelNamesInPortableContract": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "recommendationDigest": canonical_digest(body)}


def validate_review_mesh_recommendation(recommendation: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(recommendation, dict):
        raise LifecycleError("review-mesh-recommendation-invalid", "recommendation must be an object")
    if recommendation.get("schemaVersion") != REVIEW_MESH_RECOMMENDATION_SCHEMA:
        blockers.append({"code": "review-mesh-recommendation-schema-invalid"})
    mode = recommendation.get("recommendedMode")
    if mode not in REVIEW_MESH_RECOMMENDATION_MODES:
        blockers.append({"code": "review-mesh-recommendation-mode-invalid", "mode": mode})
    if mode != OFF_MODE and mode not in REVIEW_MESH_MODE_IDS:
        blockers.append({"code": "review-mesh-recommendation-mode-not-canonical"})
    _check_string_list(recommendation.get("phaseCoverage"), "review-mesh-recommendation-phase-coverage-invalid", blockers)
    if not isinstance(recommendation.get("reasons"), list):
        blockers.append({"code": "review-mesh-recommendation-reasons-invalid"})
    if mode == OFF_MODE and not recommendation.get("skipRationale"):
        blockers.append({"code": "review-mesh-recommendation-skip-rationale-missing"})
    if mode != OFF_MODE and recommendation.get("requiredReviewers", 0) < 1:
        blockers.append({"code": "review-mesh-recommendation-reviewer-count-invalid"})
    if recommendation.get("budgetUnits") != "tokens-and-resources":
        blockers.append({"code": "review-mesh-recommendation-budget-units-invalid"})
    _validate_resource_cap(recommendation.get("budgetCap"), blockers)
    _check_model_class_hints(recommendation.get("providerNeutralModelClassHints"), blockers)
    _check_model_class_availability(recommendation.get("modelRoutingClassAvailability"), blockers)
    for field, expected in {
        "advisoryOnly": True,
        "requiresOperatorConfirmation": True,
        "blockingGateActivated": False,
        "assignmentsGenerated": False,
        "quorumEnforced": False,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "concreteProviderModelNamesInPortableContract": False,
        "productionPromotionClaimed": False,
    }.items():
        if recommendation.get(field) is not expected:
            blockers.append({"code": "review-mesh-recommendation-boundary-invalid", "field": field})
    source = recommendation.get("source")
    if not isinstance(source, dict):
        blockers.append({"code": "review-mesh-recommendation-source-invalid"})
    elif source.get("rawTextStored") is not False:
        blockers.append({"code": "review-mesh-recommendation-raw-text-stored"})
    blockers.extend(_money_key_blockers(recommendation))
    blockers.extend(_provider_model_key_blockers(recommendation))
    expected_digest = canonical_digest({key: value for key, value in recommendation.items() if key != "recommendationDigest"})
    if recommendation.get("recommendationDigest") != expected_digest:
        blockers.append({"code": "review-mesh-recommendation-digest-mismatch"})
    body = {
        "schemaVersion": "agent-review-mesh-recommendation-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "recommendedMode": mode if isinstance(mode, str) else None,
        "blockers": blockers,
        "recommendationDigest": recommendation.get("recommendationDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_review_mesh_recommendation_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError("review-mesh-recommendation-validation-failed", "Review Mesh recommendation validation failed", {"validation": validation})
    return validation


def _select_mode(
    *,
    text: str,
    task_shape: str | None,
    recommended_quality_profiles: list[str],
    pre_implementation_analysis: dict[str, Any] | None,
    sdd_tier: str | None,
    risk_flags: set[str],
    status: str | None,
) -> dict[str, Any]:
    lowered = text.lower()
    reasons: list[dict[str, str]] = []
    if _contains_any(lowered, _IMPLEMENTATION_AUDIT_MARKERS):
        reasons.append({"code": "implementation-audit-shaped-input", "message": "implementation evidence or final audit review is requested"})
        return _decision(MODE_IMPLEMENTATION_AUDIT, reasons)
    if "bug-forensics" in recommended_quality_profiles or task_shape == "bugfix" or _contains_any(lowered, _BUG_MARKERS):
        reasons.append({"code": "defect-risk", "message": "defect-shaped work benefits from independent root-cause and regression review"})
        return _decision(MODE_LEADER_REVIEW, reasons)
    if _contains_any(lowered, _SECURITY_MARKERS) or "security" in risk_flags or "security-bug" in risk_flags:
        reasons.append({"code": "security-risk", "message": "security-sensitive work benefits from independent review"})
        return _decision(MODE_LEADER_REVIEW, reasons)
    if sdd_tier == "S2":
        reasons.append({"code": "sdd-tier-s2", "message": "S2 work carries enough coordination risk to justify optional plan review"})
        return _decision(MODE_LEADER_REVIEW, reasons)
    high_risk_flags = risk_flags.intersection({"release", "externalEnvironment", "architecture", "securityRelease", "multiOwner"})
    if high_risk_flags:
        reasons.append({"code": "risk-flags", "message": "risk flags justify optional plan review"})
        return _decision(MODE_LEADER_REVIEW, reasons)
    analysis_required = bool(pre_implementation_analysis and pre_implementation_analysis.get("required"))
    if _contains_any(lowered, _RESEARCH_MARKERS) or task_shape == "analysis-first" or analysis_required:
        reasons.append({"code": "analysis-or-planning-shaped-input", "message": "independent research or planning may improve the decision before implementation"})
        return _decision(MODE_PARALLEL_RESEARCH, reasons)
    reasons.append({"code": "low-risk-single-lifecycle", "message": "no Review Mesh trigger was detected"})
    return _decision(OFF_MODE, reasons)


def _decision(mode: str, reasons: list[dict[str, str]]) -> dict[str, Any]:
    if mode == MODE_PARALLEL_RESEARCH:
        return {
            "mode": mode,
            "phaseCoverage": ["research", "planning"],
            "reasons": reasons,
            "skipRationale": None,
            "requiredReviewers": 2,
        }
    if mode == MODE_IMPLEMENTATION_AUDIT:
        return {
            "mode": mode,
            "phaseCoverage": ["implementation-audit", "final-audit"],
            "reasons": reasons,
            "skipRationale": None,
            "requiredReviewers": 2,
        }
    if mode == MODE_LEADER_REVIEW:
        return {
            "mode": mode,
            "phaseCoverage": ["planning", "plan-review"],
            "reasons": reasons,
            "skipRationale": None,
            "requiredReviewers": 2,
        }
    return {
        "mode": OFF_MODE,
        "phaseCoverage": [],
        "reasons": reasons,
        "skipRationale": "Normal lifecycle is sufficient; extra review would add cost without a matching risk signal.",
        "requiredReviewers": 0,
    }


def _budget_cap(mode: str) -> dict[str, int]:
    if mode == OFF_MODE:
        return dict(_OFF_CAP)
    profile = build_review_mesh_profile(default_mode=mode, budget_cap=_DEFAULT_CAP)
    return dict(profile["budgetCap"])


def _model_class_hints(mode: str) -> list[str]:
    if mode == OFF_MODE:
        return []
    if mode == MODE_PARALLEL_RESEARCH:
        requested = ["standard-code", "local-standard-code", "strong-reasoning"]
    elif mode == MODE_IMPLEMENTATION_AUDIT:
        requested = ["strong-reasoning", "local-strong-review", "specialist-review"]
    else:
        requested = ["strong-reasoning", "local-strong-review"]
    return [item for item in requested if item in ALLOWED_MODEL_CLASSES]


def _normalize_risk_flags(value: dict[str, bool] | list[str] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, dict):
        return {str(key) for key, enabled in value.items() if enabled is True}
    if isinstance(value, list):
        return {str(item) for item in value if isinstance(item, str) and item}
    return set()


def _manifest_signal_text(manifest: dict[str, Any]) -> str:
    pieces: list[str] = []
    package = manifest.get("package")
    if isinstance(package, dict):
        for key in ("title", "id"):
            if isinstance(package.get(key), str):
                pieces.append(package[key])
    specification = manifest.get("specification") if isinstance(manifest.get("specification"), dict) else {}
    requirements = specification.get("requirements")
    if isinstance(requirements, list):
        for item in requirements[:12]:
            if isinstance(item, dict) and isinstance(item.get("description"), str):
                pieces.append(item["description"])
            elif isinstance(item, str):
                pieces.append(item)
    acceptance = manifest.get("acceptanceCriteria")
    if isinstance(acceptance, list):
        for item in acceptance[:8]:
            if isinstance(item, dict) and isinstance(item.get("statement"), str):
                pieces.append(item["statement"])
    return "\n".join(pieces)


def _manifest_package_id(manifest: dict[str, Any]) -> str:
    package = manifest.get("package")
    if isinstance(package, dict) and isinstance(package.get("id"), str):
        return package["id"]
    return "plan-manifest"


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        blockers.append({"code": code})


def _validate_resource_cap(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "review-mesh-recommendation-budget-cap-invalid"})
        return
    missing = sorted(RESOURCE_CAP_KEYS.difference(value))
    if missing:
        blockers.append({"code": "review-mesh-recommendation-budget-cap-missing", "fields": missing})
    for key in RESOURCE_CAP_KEYS.intersection(value):
        amount = value.get(key)
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            blockers.append({"code": "review-mesh-recommendation-budget-cap-value-invalid", "field": key})
    if MONEY_KEYS.intersection(value):
        blockers.append({"code": "review-mesh-recommendation-money-cap-not-allowed"})


def _check_model_class_hints(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list):
        blockers.append({"code": "review-mesh-recommendation-model-class-hints-invalid"})
        return
    unknown = sorted({item for item in value if not isinstance(item, str) or item not in ALLOWED_MODEL_CLASSES})
    if unknown:
        blockers.append({"code": "review-mesh-recommendation-model-class-hints-unknown", "classes": unknown})


def _check_model_class_availability(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "review-mesh-recommendation-model-class-availability-invalid"})
        return
    classes = value.get("availableClasses")
    if not isinstance(classes, list):
        blockers.append({"code": "review-mesh-recommendation-available-classes-invalid"})
        return
    unknown = sorted({item for item in classes if not isinstance(item, str) or item not in ALLOWED_MODEL_CLASSES})
    if unknown:
        blockers.append({"code": "review-mesh-recommendation-available-classes-unknown", "classes": unknown})


def _money_key_blockers(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if key in MONEY_KEYS:
                blockers.append({"code": "review-mesh-recommendation-monetary-field-not-allowed", "field": key_path})
            blockers.extend(_money_key_blockers(item, path=key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blockers.extend(_money_key_blockers(item, path=f"{path}[{index}]"))
    return blockers


def _provider_model_key_blockers(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = f"{path}.{key}" if path else str(key)
            if key in _PROVIDER_MODEL_NAME_KEYS:
                blockers.append({"code": "review-mesh-recommendation-provider-model-name-not-portable", "field": key_path})
            blockers.extend(_provider_model_key_blockers(item, path=key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            blockers.extend(_provider_model_key_blockers(item, path=f"{path}[{index}]"))
    return blockers
