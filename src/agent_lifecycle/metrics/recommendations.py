"""Advisory lifecycle mode recommendations from cost reports."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.metrics.costs import (
    COST_CATEGORIES,
    DEFAULT_MODE_LIMITS,
    cost_ratios,
    summarize_usage_confidence,
    validate_lifecycle_cost_report,
)
from agent_lifecycle.policy.quality_floor import max_mode, mode_index, quality_floor_mode

BASELINES_SCHEMA = "agent-lifecycle-baselines.v1"
BASELINE_VALIDATION_SCHEMA = "agent-lifecycle-baselines-validation.v1"
STATISTICS_SCHEMA = "agent-lifecycle-overhead-statistics.v1"
RECOMMENDATION_SCHEMA = "agent-lifecycle-recommendation.v1"
RECOMMENDATION_SUMMARY_SCHEMA = "agent-lifecycle-recommendation-summary.v1"
MODE_ORDER = tuple(DEFAULT_MODE_LIMITS)


def validate_lifecycle_baselines(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if profile.get("schemaVersion") != BASELINES_SCHEMA:
        blockers.append({"code": "baseline-schema", "message": "unsupported lifecycle baseline schemaVersion"})
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "baseline-production-claim", "message": "baseline profile must not claim production promotion"})
    minimum_reports = profile.get("minimumReportsForConfidence")
    if not isinstance(minimum_reports, int) or isinstance(minimum_reports, bool) or minimum_reports < 1:
        blockers.append({"code": "baseline-minimum-reports", "message": "minimumReportsForConfidence must be a positive integer"})
    mode_order = profile.get("modeOrder")
    if "modeOrder" in profile and (not isinstance(mode_order, list) or tuple(mode_order) != MODE_ORDER):
        blockers.append({"code": "baseline-mode-order", "message": "modeOrder must match lifecycle modes"})
    risk_floors = profile.get("riskFloors")
    if not isinstance(risk_floors, dict):
        blockers.append({"code": "baseline-risk-floors", "message": "riskFloors must be an object"})
        risk_floors = {}
    for risk, mode in risk_floors.items():
        if not isinstance(risk, str) or mode not in MODE_ORDER:
            blockers.append({"code": "baseline-risk-floor-mode", "risk": risk, "mode": mode})
    task_shapes = profile.get("taskShapes")
    if not isinstance(task_shapes, dict) or not task_shapes:
        blockers.append({"code": "baseline-task-shapes", "message": "taskShapes must be a non-empty object"})
        task_shapes = {}
    for shape, config in task_shapes.items():
        _validate_shape(shape, config, blockers)
    body = {
        "schemaVersion": BASELINE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "taskShapeCount": len(task_shapes),
        "blockers": blockers,
        "profileDigest": canonical_digest(profile),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_lifecycle_recommendation_pass(recommendation: dict[str, Any]) -> dict[str, Any]:
    if recommendation.get("status") == "FAIL":
        raise LifecycleError(
            "lifecycle-recommendation-failed",
            "lifecycle recommendation failed",
            {"recommendation": recommendation},
        )
    return recommendation


def summarize_lifecycle_overhead(reports: list[dict[str, Any]]) -> dict[str, Any]:
    totals = _empty_totals()
    usage_entries: list[dict[str, Any]] = []
    report_digests: list[str] = []
    blockers: list[dict[str, Any]] = []
    for index, report in enumerate(reports):
        validation = validate_lifecycle_cost_report(report)
        if validation["status"] != "PASS":
            blockers.append({"code": "cost-report-invalid", "index": index, "validation": validation})
        report_digests.append(validation["reportDigest"])
        for category in COST_CATEGORIES:
            totals[category]["tokens"] += validation["totals"][category]["tokens"]
            totals[category]["steps"] += validation["totals"][category]["steps"]
        entries = report.get("entries")
        if isinstance(entries, list):
            usage_entries.extend(item for item in entries if isinstance(item, dict))
    totals["overall"] = {
        "tokens": sum(totals[category]["tokens"] for category in COST_CATEGORIES),
        "steps": sum(totals[category]["steps"] for category in COST_CATEGORIES),
    }
    ratios = cost_ratios(totals)
    body = {
        "schemaVersion": STATISTICS_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "reportCount": len(reports),
        "reportDigests": sorted(report_digests),
        "totals": totals,
        "ratios": ratios,
        "usageConfidence": summarize_usage_confidence(usage_entries),
        "averageProductValidationSteps": _average(totals["productValidation"]["steps"], len(reports)),
        "blockers": blockers,
    }
    return {**body, "statisticsDigest": canonical_digest(body)}


def recommend_lifecycle_mode(
    *,
    reports: list[dict[str, Any]],
    baseline_profile: dict[str, Any],
    task_shape: str = "feature",
    current_mode: str | None = None,
    sdd_tier: str | None = None,
    risk_flags: list[str] | None = None,
) -> dict[str, Any]:
    baseline_validation = validate_lifecycle_baselines(baseline_profile)
    stats = summarize_lifecycle_overhead(reports)
    blockers = list(baseline_validation["blockers"])
    if stats["status"] != "PASS":
        blockers.extend(stats["blockers"])
    shape = _task_shape(baseline_profile, task_shape, blockers)
    if baseline_validation["status"] != "PASS" or stats["status"] != "PASS" or shape is None:
        body = _failed_recommendation(task_shape, current_mode, baseline_validation, stats, blockers)
        return {**body, "recommendationDigest": canonical_digest(body)}

    floor = quality_floor_mode(
        task_shape=task_shape,
        baseline_profile=baseline_profile,
        sdd_tier=sdd_tier,
        risk_flags=risk_flags or [],
    )
    warnings = _warnings(stats, shape, baseline_profile)
    weak_data = _weak_data(stats, baseline_profile)
    confidence = _confidence(stats, weak_data=weak_data, warning_count=len(warnings))
    recommended = _recommended_mode(shape, floor=floor, current_mode=current_mode, confidence=confidence, warnings=warnings)
    body = {
        "schemaVersion": RECOMMENDATION_SCHEMA,
        "status": "PASS",
        "taskShape": task_shape,
        "currentMode": current_mode,
        "recommendedMode": recommended,
        "confidence": confidence,
        "advisoryOnly": True,
        "autoApply": False,
        "qualityFloor": floor,
        "qualityFloorPreserved": mode_index(recommended) >= mode_index(floor),
        "warnings": warnings,
        "reasons": _reasons(confidence, recommended, floor, weak_data, warnings),
        "statistics": stats,
        "baselineValidation": baseline_validation,
        "productionPromotionClaimed": False,
    }
    body["compactSummary"] = build_lifecycle_recommendation_summary(body)
    return {**body, "recommendationDigest": canonical_digest(body)}


def build_lifecycle_recommendation_summary(recommendation: dict[str, Any]) -> dict[str, Any]:
    stats = recommendation.get("statistics") if isinstance(recommendation.get("statistics"), dict) else {}
    ratios = stats.get("ratios") if isinstance(stats.get("ratios"), dict) else {}
    warnings = recommendation.get("warnings") if isinstance(recommendation.get("warnings"), list) else []
    return {
        "schemaVersion": RECOMMENDATION_SUMMARY_SCHEMA,
        "latestUserIntent": "Choose the lightest lifecycle mode that preserves the required quality floor.",
        "activeDecisions": [
            f"taskShape={recommendation.get('taskShape')}",
            f"recommendedMode={recommendation.get('recommendedMode')}",
            f"confidence={recommendation.get('confidence')}",
            f"pipelineTokenShare={ratios.get('pipelineTokenShare', 0.0)}",
        ],
        "openBlockers": [],
        "acceptedEvidence": [
            {
                "id": "lifecycle-recommendation",
                "status": recommendation.get("status"),
                "warningCount": len(warnings),
            }
        ],
        "changedFiles": [],
        "nextRequiredAction": "review advisory recommendation before changing lifecycle mode",
        "doNotDo": [
            "Do not auto-apply recommendations.",
            "Do not lower required validation for high-risk task classes.",
        ],
        "recommendedMode": recommendation.get("recommendedMode"),
        "confidence": recommendation.get("confidence"),
        "warnings": warnings[:8],
        "qualityFloorPreserved": recommendation.get("qualityFloorPreserved") is True,
    }


def _validate_shape(shape: str, config: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(config, dict):
        blockers.append({"code": "baseline-shape-config", "taskShape": shape})
        return
    for key in ("defaultMode", "minMode"):
        if config.get(key) not in MODE_ORDER:
            blockers.append({"code": "baseline-shape-mode", "taskShape": shape, "field": key})
    for key in ("overheadWarningShare", "coordinationWarningShare"):
        value = config.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0 or value > 1:
            blockers.append({"code": "baseline-shape-share", "taskShape": shape, "field": key})
    threshold = config.get("reviewStepWarningThreshold")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 0:
        blockers.append({"code": "baseline-shape-review-threshold", "taskShape": shape})
    if mode_index(str(config.get("defaultMode"))) < mode_index(str(config.get("minMode"))):
        blockers.append({"code": "baseline-shape-default-below-min", "taskShape": shape})


def _empty_totals() -> dict[str, dict[str, int]]:
    return {category: {"tokens": 0, "steps": 0} for category in COST_CATEGORIES}


def _average(value: int, count: int) -> float:
    return round(value / count, 6) if count else 0.0


def _task_shape(profile: dict[str, Any], task_shape: str, blockers: list[dict[str, Any]]) -> dict[str, Any] | None:
    shapes = profile.get("taskShapes")
    if not isinstance(shapes, dict) or not isinstance(shapes.get(task_shape), dict):
        blockers.append({"code": "baseline-task-shape-missing", "taskShape": task_shape})
        return None
    return shapes[task_shape]


def _warnings(stats: dict[str, Any], shape: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    ratios = stats.get("ratios", {})
    pipeline_share = float(ratios.get("pipelineTokenShare", 0.0))
    coordination_share = _coordination_share(stats)
    if pipeline_share > float(shape["overheadWarningShare"]):
        warnings.append({"code": "pipeline-token-share-high", "value": pipeline_share, "limit": shape["overheadWarningShare"]})
    if coordination_share > float(shape["coordinationWarningShare"]):
        warnings.append({"code": "coordination-token-share-high", "value": coordination_share, "limit": shape["coordinationWarningShare"]})
    if stats.get("averageProductValidationSteps", 0) > shape["reviewStepWarningThreshold"]:
        warnings.append({"code": "review-step-cost-high", "value": stats["averageProductValidationSteps"], "limit": shape["reviewStepWarningThreshold"]})
    confidence = stats.get("usageConfidence", {})
    if confidence.get("missingEntries", 0) > 0:
        warnings.append({"code": "missing-usage", "entries": confidence["missingEntries"]})
    if stats.get("reportCount", 0) < int(profile.get("minimumReportsForConfidence", 2)):
        warnings.append({"code": "weak-statistics", "reportCount": stats.get("reportCount", 0)})
    if stats.get("status") != "PASS":
        warnings.append({"code": "invalid-cost-report", "blockerCount": len(stats.get("blockers", []))})
    return warnings


def _coordination_share(stats: dict[str, Any]) -> float:
    totals = stats.get("totals", {})
    overall = totals.get("overall", {}).get("tokens", 0)
    coordination = totals.get("coordination", {}).get("tokens", 0)
    return round(coordination / overall, 6) if overall else 0.0


def _weak_data(stats: dict[str, Any], profile: dict[str, Any]) -> bool:
    usage = stats.get("usageConfidence", {})
    minimum = int(profile.get("minimumReportsForConfidence", 2))
    return stats.get("reportCount", 0) < minimum or usage.get("missingEntries", 0) > 0 or stats.get("status") != "PASS"


def _confidence(stats: dict[str, Any], *, weak_data: bool, warning_count: int) -> str:
    if weak_data:
        return "LOW"
    if stats.get("reportCount", 0) >= 3 and warning_count == 0:
        return "HIGH"
    return "MEDIUM"


def _recommended_mode(
    shape: dict[str, Any],
    *,
    floor: str,
    current_mode: str | None,
    confidence: str,
    warnings: list[dict[str, Any]],
) -> str:
    current = current_mode if current_mode in MODE_ORDER else None
    if confidence == "LOW":
        return max_mode(current or str(shape["defaultMode"]), floor)
    if shape.get("highRisk") is True:
        return max_mode(current or str(shape["defaultMode"]), floor)
    overhead_warning = any(item["code"] in {"pipeline-token-share-high", "coordination-token-share-high"} for item in warnings)
    target = str(shape["minMode"] if overhead_warning else shape["defaultMode"])
    return max_mode(target, floor)


def _reasons(confidence: str, recommended: str, floor: str, weak_data: bool, warnings: list[dict[str, Any]]) -> list[str]:
    reasons = [f"recommendedMode={recommended}", f"qualityFloor={floor}", f"confidence={confidence}"]
    if weak_data:
        reasons.append("statistics are weak or incomplete, so the safer current/floor mode is retained")
    for warning in warnings:
        reasons.append(f"warning:{warning['code']}")
    return reasons


def _failed_recommendation(
    task_shape: str,
    current_mode: str | None,
    baseline_validation: dict[str, Any],
    stats: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schemaVersion": RECOMMENDATION_SCHEMA,
        "status": "FAIL",
        "taskShape": task_shape,
        "currentMode": current_mode,
        "recommendedMode": current_mode if current_mode in MODE_ORDER else "standard",
        "confidence": "LOW",
        "advisoryOnly": True,
        "autoApply": False,
        "qualityFloor": "standard",
        "qualityFloorPreserved": True,
        "warnings": [{"code": "recommendation-blocked", "blockerCount": len(blockers)}],
        "reasons": ["baseline profile is invalid or task shape is unknown"],
        "statistics": stats,
        "baselineValidation": baseline_validation,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
