"""Quality-first, advisory optimization of repeated independent audits."""

from __future__ import annotations

from statistics import mean
from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.audit_optimization_schemas import (
    AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA,
    AUDIT_OPTIMIZATION_REPORT_SCHEMA,
    AUDIT_OPTIMIZATION_STATISTICS_SCHEMA,
)
from agent_lifecycle.metrics.audit_samples import validate_audit_sample
from agent_lifecycle.metrics.outcome_index import summarize_audit_quality
from agent_lifecycle.metrics.recommendations import (
    audit_recommendation_reason,
    quality_floor_preserved,
)
from agent_lifecycle.metrics.regression_signals import build_audit_regression_signals

DEFAULT_MINIMUM_SAMPLE = 3
DEFAULT_MAX_HOLDOUT_TASKS = 12
DEFAULT_MINIMUM_QUALITY = 0.95
MAX_REVIEWERS = 8
MAX_RETRIES = 4
MAX_TIMEOUT_SECONDS = 14400
MAX_PACKET_TOKENS = 100000


def build_audit_statistics(
    samples: list[dict[str, Any]] | dict[str, Any],
    *,
    minimum_sample: int = DEFAULT_MINIMUM_SAMPLE,
) -> dict[str, Any]:
    """Produce confidence-aware statistics without calling a host or model."""

    rows = _sample_rows(samples)
    blockers: list[dict[str, Any]] = []
    valid: list[dict[str, Any]] = []
    for index, sample in enumerate(rows):
        validation = validate_audit_sample(sample)
        if validation["status"] != "PASS":
            blockers.append({"code": "audit-sample-invalid", "index": index, "validation": validation})
        else:
            valid.append(sample)
    minimum = max(1, int(minimum_sample))
    quality = summarize_audit_quality(valid)
    usage_values = [_number(sample.get("usage", {}).get("wallSeconds")) for sample in valid]
    token_values = [_number(sample.get("usage", {}).get("billableTokens")) for sample in valid]
    cpu_values = _available_metric_values(valid, "cpuMs")
    memory_values = _available_metric_values(valid, "peakMemoryMb")
    process_values = _available_metric_values(valid, "processCount")
    attestation_counts = _attestation_counts(valid)
    signals = {
        "quality": quality,
        "latency": _numeric_summary(usage_values, unit="seconds"),
        "tokens": _numeric_summary(token_values, unit="tokens"),
        "resources": {
            "cpuMs": _numeric_summary(cpu_values, unit="ms"),
            "peakMemoryMb": _numeric_summary(memory_values, unit="MB"),
            "processCount": _numeric_summary(process_values, unit="processes"),
        },
        "attestation": attestation_counts,
        "bottleneck": _bottleneck(quality, usage_values, token_values, attestation_counts),
    }
    sufficient = len(valid) >= minimum
    confidence = _confidence(len(valid), minimum, attestation_counts, quality)
    if not sufficient and not blockers:
        blockers.append({"code": "minimum-sample-not-met", "required": minimum, "actual": len(valid)})
    status = "FAIL" if blockers and any(item.get("code") == "audit-sample-invalid" for item in blockers) else ("PASS" if sufficient else "NO_RECOMMENDATION")
    body = {
        "schemaVersion": AUDIT_OPTIMIZATION_STATISTICS_SCHEMA,
        "status": status,
        "sampleCount": len(valid),
        "confidence": confidence,
        "minimumSample": {"required": minimum, "actual": len(valid), "sufficient": sufficient},
        "signals": signals,
        "regressionSignals": build_audit_regression_signals(valid),
        "blockers": blockers,
    }
    return {**body, "statisticsDigest": canonical_digest(body)}


def evaluate_candidate_profiles(
    candidate_profiles: list[dict[str, Any]] | None,
    *,
    holdout_tasks: list[dict[str, Any]] | None = None,
    reference_tasks: list[dict[str, Any]] | None = None,
    minimum_holdout_tasks_per_shape: int = 3,
    max_holdout_tasks: int = DEFAULT_MAX_HOLDOUT_TASKS,
    minimum_quality: float = DEFAULT_MINIMUM_QUALITY,
) -> dict[str, Any]:
    """Evaluate bounded candidate profiles on one shared holdout pool."""

    profiles = [item for item in (candidate_profiles or []) if isinstance(item, dict)]
    external_tasks = [item for item in (holdout_tasks or []) if isinstance(item, dict)]
    all_tasks: list[dict[str, Any]] = []
    for profile in profiles:
        embedded = profile.get("holdoutTasks") or profile.get("holdoutResults")
        if isinstance(embedded, list):
            for item in embedded:
                if isinstance(item, dict):
                    all_tasks.append({**item, "candidateProfileId": item.get("candidateProfileId") or profile.get("profileId")})
    all_tasks.extend(external_tasks)
    blockers: list[dict[str, Any]] = []
    if len(all_tasks) > max_holdout_tasks:
        blockers.append({"code": "holdout-task-cap-exceeded", "actual": len(all_tasks), "limit": max_holdout_tasks})
    evaluated: list[dict[str, Any]] = []
    for index, profile in enumerate(profiles):
        profile_id = _string(profile.get("profileId"), f"candidate-{index + 1}")
        shape = _string(profile.get("taskShape"), "feature")
        rows = [item for item in all_tasks if _task_profile_id(item) == profile_id]
        if not rows and len(profiles) == 1 and all_tasks and not any(_task_profile_id(item) for item in all_tasks):
            rows = list(all_tasks)
        task_ids = sorted({_string(item.get("taskId"), f"holdout-{index}") for item in rows})
        quality_pass = sum(1 for item in rows if _quality_pass(item))
        false_acceptances = sum(1 for item in rows if item.get("falseAcceptance") is True or item.get("acceptedThenCorrected") is True)
        tokens = [_number(item.get("billableTokens", item.get("tokens"))) for item in rows]
        wall = [_number(item.get("wallSeconds")) for item in rows]
        quality_rate = float(profile.get("qualityRate")) if _number_or_none(profile.get("qualityRate")) is not None else _rate(quality_pass, len(rows))
        false_rate = float(profile.get("falseAcceptanceRate")) if _number_or_none(profile.get("falseAcceptanceRate")) is not None else _rate(false_acceptances, len(rows))
        profile_quality_floor = _string(profile.get("qualityFloor"), "standard")
        row = {
            "profileId": profile_id,
            "taskShape": shape,
            "holdoutCount": len(rows),
            "distinctTaskCount": len(task_ids),
            "taskIds": task_ids,
            "qualityRate": round(quality_rate, 6),
            "falseAcceptanceRate": round(false_rate, 6),
            "averageTokens": _average_or_none(tokens, profile.get("averageTokens")),
            "averageWallSeconds": _average_or_none(wall, profile.get("averageWallSeconds")),
            "qualityFloor": profile_quality_floor,
            "routeClass": _safe_route_class(profile.get("routeClass")),
            "reviewerCountHint": _bounded_int(profile.get("reviewerCountHint"), 1, MAX_REVIEWERS),
            "packetTokenLimit": _bounded_int(profile.get("packetTokenLimit"), 128, MAX_PACKET_TOKENS),
            "timeoutSeconds": _bounded_int(profile.get("timeoutSeconds"), 1, MAX_TIMEOUT_SECONDS),
            "retryLimit": _bounded_int(profile.get("retryLimit"), 0, MAX_RETRIES),
        }
        row["eligible"] = (
            row["distinctTaskCount"] >= max(1, minimum_holdout_tasks_per_shape)
            and row["qualityRate"] >= minimum_quality
            and row["falseAcceptanceRate"] <= 0.0
        )
        if row["distinctTaskCount"] < max(1, minimum_holdout_tasks_per_shape):
            row["eligibilityReason"] = "minimum-holdout-tasks-not-met"
        elif row["qualityRate"] < minimum_quality:
            row["eligibilityReason"] = "quality-floor-not-met"
        elif row["falseAcceptanceRate"] > 0:
            row["eligibilityReason"] = "false-acceptance-increased"
        else:
            row["eligibilityReason"] = "quality-and-holdout-gates-pass"
        evaluated.append(row)
    eligible = [item for item in evaluated if item["eligible"]]
    reasons: list[dict[str, Any]] = []
    if not profiles:
        reasons.append({"code": "candidate-profiles-missing"})
    elif not eligible and not blockers:
        reasons.append({"code": "no-quality-safe-candidate"})
    status = "FAIL" if blockers else ("PASS" if eligible else "NO_RECOMMENDATION")
    body = {
        "schemaVersion": "agent-audit-optimization-evaluation.v1",
        "status": status,
        "candidateCount": len(profiles),
        "referenceTaskCount": len(reference_tasks or []),
        "holdoutTaskCount": len(all_tasks),
        "minimumHoldoutTasksPerShape": max(1, minimum_holdout_tasks_per_shape),
        "maxHoldoutTasks": max_holdout_tasks,
        "minimumQuality": minimum_quality,
        "candidates": sorted(evaluated, key=lambda item: (item["taskShape"], item["profileId"])),
        "eligibleCandidates": sorted(eligible, key=lambda item: (item["taskShape"], item["profileId"])),
        "blockers": blockers,
        "reasons": reasons,
    }
    return {**body, "evaluationDigest": canonical_digest(body)}


def recommend_audit_optimization(
    *,
    statistics: dict[str, Any],
    evaluation: dict[str, Any],
    task_shape: str = "feature",
    quality_floor: str = "standard",
    current_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select a bounded, explicit-review-only candidate profile."""

    current = current_profile if isinstance(current_profile, dict) else {}
    blockers: list[dict[str, Any]] = []
    if statistics.get("schemaVersion") != AUDIT_OPTIMIZATION_STATISTICS_SCHEMA or statistics.get("status") != "PASS":
        blockers.append({"code": "statistics-not-sufficient", "status": statistics.get("status")})
    if statistics.get("confidence") == "LOW":
        blockers.append({"code": "statistics-low-confidence"})
    regression = statistics.get("regressionSignals") if isinstance(statistics.get("regressionSignals"), dict) else {}
    if regression.get("status") in {"FAIL", "BLOCK"}:
        blockers.append({"code": "quality-regression-signals", "status": regression.get("status")})
    if evaluation.get("status") != "PASS":
        blockers.extend(evaluation.get("blockers", []))
    candidates = [item for item in evaluation.get("eligibleCandidates", []) if item.get("taskShape") == task_shape]
    if not candidates:
        blockers.append({"code": "no-eligible-candidate", "taskShape": task_shape})
    selected = None
    if candidates:
        selected = min(candidates, key=lambda item: (-float(item.get("qualityRate", 0)), float(item.get("falseAcceptanceRate", 1)), float(item.get("averageWallSeconds") or 0), float(item.get("averageTokens") or 0), str(item.get("profileId"))))
        if not quality_floor_preserved(str(selected.get("qualityFloor", "standard")), quality_floor):
            blockers.append({"code": "candidate-quality-floor-lowered", "required": quality_floor, "candidate": selected.get("qualityFloor")})
    if blockers:
        body = _no_recommendation(task_shape, quality_floor, statistics, evaluation, blockers)
        return {**body, "recommendationDigest": canonical_digest(body)}
    changes = _changes(selected, current)
    reasons = [
        audit_recommendation_reason("quality-first-selection", qualityRate=selected["qualityRate"]),
        audit_recommendation_reason("false-acceptance-floor", falseAcceptanceRate=selected["falseAcceptanceRate"]),
        audit_recommendation_reason("confidence", value=statistics.get("confidence")),
        audit_recommendation_reason("holdout-evidence", distinctTaskCount=selected["distinctTaskCount"]),
    ]
    body = {
        "schemaVersion": AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA,
        "status": "PASS",
        "taskShape": task_shape,
        "selectedProfileId": selected["profileId"],
        "confidence": statistics.get("confidence", "MEDIUM"),
        "qualityFloor": quality_floor,
        "qualityFloorPreserved": True,
        "advisoryOnly": True,
        "autoApply": False,
        "changes": changes,
        "reasons": reasons,
        "expectedTradeoffs": {
            "qualityRate": selected["qualityRate"],
            "falseAcceptanceRate": selected["falseAcceptanceRate"],
            "averageTokens": selected["averageTokens"],
            "averageWallSeconds": selected["averageWallSeconds"],
            "bottleneck": (statistics.get("signals") or {}).get("bottleneck"),
        },
        "approval": {"required": True, "target": "new-project-profile-or-plan-revision", "frozenPlanMutation": False},
        "rollback": {"strategy": "restore prior profile and re-run the optimizer", "requiresReview": True, "priorProfileDigest": canonical_digest(current) if current else None},
        "statisticsDigest": statistics.get("statisticsDigest"),
        "evaluationDigest": evaluation.get("evaluationDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "recommendationDigest": canonical_digest(body)}


def build_audit_optimization_report(
    samples: list[dict[str, Any]] | dict[str, Any],
    *,
    candidate_profiles: list[dict[str, Any]] | None = None,
    reference_tasks: list[dict[str, Any]] | None = None,
    holdout_tasks: list[dict[str, Any]] | None = None,
    task_shape: str = "feature",
    quality_floor: str = "standard",
    current_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    statistics = build_audit_statistics(samples)
    evaluation = evaluate_candidate_profiles(candidate_profiles, holdout_tasks=holdout_tasks, reference_tasks=reference_tasks)
    recommendation = recommend_audit_optimization(
        statistics=statistics,
        evaluation=evaluation,
        task_shape=task_shape,
        quality_floor=quality_floor,
        current_profile=current_profile,
    )
    status = "PASS" if recommendation.get("status") == "PASS" else ("FAIL" if statistics.get("status") == "FAIL" else "NO_RECOMMENDATION")
    body = {
        "schemaVersion": AUDIT_OPTIMIZATION_REPORT_SCHEMA,
        "status": status,
        "statistics": statistics,
        "evaluation": evaluation,
        "recommendation": recommendation,
        "nextAction": "review the advisory profile and approve a new project profile or plan revision" if status == "PASS" else "collect more attested samples and holdout evidence before tuning",
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def validate_audit_optimization_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(report, dict) or report.get("schemaVersion") != AUDIT_OPTIMIZATION_REPORT_SCHEMA:
        blockers.append({"code": "audit-optimization-report-schema"})
    if isinstance(report, dict):
        if report.get("productionPromotionClaimed") is not False:
            blockers.append({"code": "audit-optimization-production-claim"})
        expected = canonical_digest({key: value for key, value in report.items() if key != "reportDigest"})
        if report.get("reportDigest") != expected:
            blockers.append({"code": "audit-optimization-report-digest"})
        recommendation = report.get("recommendation") if isinstance(report.get("recommendation"), dict) else {}
        if recommendation.get("autoApply") is not False or recommendation.get("advisoryOnly") is not True:
            blockers.append({"code": "audit-optimization-advisory-boundary"})
        if recommendation.get("qualityFloorPreserved") is not True:
            blockers.append({"code": "audit-optimization-quality-floor"})
    body = {
        "schemaVersion": "agent-audit-optimization-report-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "reportStatus": report.get("status") if isinstance(report, dict) else None,
        "blockers": blockers,
        "reportDigest": report.get("reportDigest") if isinstance(report, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def render_audit_optimization_terminal(report: dict[str, Any]) -> str:
    """Render a compact operator view without exposing receipt contents."""

    statistics = report.get("statistics") if isinstance(report.get("statistics"), dict) else {}
    signals = statistics.get("signals") if isinstance(statistics.get("signals"), dict) else {}
    quality = signals.get("quality") if isinstance(signals.get("quality"), dict) else {}
    latency = signals.get("latency") if isinstance(signals.get("latency"), dict) else {}
    tokens = signals.get("tokens") if isinstance(signals.get("tokens"), dict) else {}
    recommendation = report.get("recommendation") if isinstance(report.get("recommendation"), dict) else {}
    lines = [
        f"Audit optimization: {report.get('status', 'UNKNOWN')}",
        f"Samples: {statistics.get('sampleCount', 0)} | confidence: {statistics.get('confidence', 'LOW')}",
        f"Quality: {quality.get('successRate', 0.0):.1%} success | {quality.get('falseAcceptanceRate', 0.0):.1%} false acceptance | {quality.get('correctionRate', 0.0):.1%} correction",
        f"Time: p50={latency.get('p50', '?')}s, p95={latency.get('p95', '?')}s | tokens: p50={tokens.get('p50', '?')}, p95={tokens.get('p95', '?')}",
    ]
    if recommendation.get("status") == "PASS":
        lines.extend(
            [
                f"Suggested profile: {recommendation.get('selectedProfileId')}",
                "Approval: required; changes are advisory and are not applied automatically.",
            ]
        )
    else:
        lines.append(f"Next step: {report.get('nextAction', 'collect more evidence')}")
    return "\n".join(lines)


def _sample_rows(samples: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(samples, dict):
        rows = samples.get("samples")
    else:
        rows = samples
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _confidence(count: int, minimum: int, attestation: dict[str, int], quality: dict[str, Any]) -> str:
    if count < minimum or attestation.get("mixed", 0) > 0:
        return "LOW"
    if count >= minimum * 2 and quality.get("falseAcceptanceRate", 0.0) == 0 and attestation.get("missing", 0) == 0:
        return "HIGH"
    return "MEDIUM"


def _attestation_counts(samples: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"attested": 0, "mixed": 0, "missing": 0, "estimated": 0}
    for sample in samples:
        value = _value_at(sample, "attestation.overall")
        if value == "ATTESTED":
            counts["attested"] += 1
        elif value == "MIXED":
            counts["mixed"] += 1
        elif value == "ESTIMATED":
            counts["estimated"] += 1
        else:
            counts["missing"] += 1
    return counts


def _available_metric_values(samples: list[dict[str, Any]], field: str) -> list[float]:
    values: list[float] = []
    for sample in samples:
        value = _value_at(sample, f"process.{field}.value")
        availability = _value_at(sample, f"process.{field}.availability")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and availability == "ATTESTED":
            values.append(float(value))
    return values


def _numeric_summary(values: list[float], *, unit: str) -> dict[str, Any]:
    if not values:
        return {"count": 0, "unit": unit, "availability": "UNAVAILABLE", "average": None, "p50": None, "p95": None, "minimum": None, "maximum": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "unit": unit,
        "availability": "ATTESTED",
        "average": round(mean(ordered), 6),
        "p50": round(_percentile(ordered, 0.50), 6),
        "p95": round(_percentile(ordered, 0.95), 6),
        "minimum": round(ordered[0], 6),
        "maximum": round(ordered[-1], 6),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _bottleneck(quality: dict[str, Any], wall: list[float], tokens: list[float], attestation: dict[str, int]) -> str:
    if attestation.get("missing", 0) or attestation.get("mixed", 0):
        return "missing-or-mixed-evidence"
    if quality.get("falseAcceptanceRate", 0) > 0:
        return "false-acceptance-risk"
    if quality.get("timeoutRate", 0) > 0:
        return "timeouts"
    if quality.get("retryRate", 0) > 0:
        return "retries"
    if wall and max(wall) > 60:
        return "wall-time"
    if tokens and max(tokens) > 10000:
        return "token-volume"
    return "no-dominant-bottleneck"


def _changes(candidate: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ("packetTokenLimit", "reviewerCountHint", "timeoutSeconds", "retryLimit", "routeClass")
    changes: list[dict[str, Any]] = []
    for field in fields:
        after = candidate.get(field)
        before = current.get(field)
        if after is not None and after != before:
            changes.append({"field": field, "before": before, "after": after, "bounded": True})
    return changes


def _no_recommendation(task_shape: str, quality_floor: str, statistics: dict[str, Any], evaluation: dict[str, Any], blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": AUDIT_OPTIMIZATION_RECOMMENDATION_SCHEMA,
        "status": "NO_RECOMMENDATION",
        "taskShape": task_shape,
        "selectedProfileId": None,
        "confidence": statistics.get("confidence", "LOW"),
        "qualityFloor": quality_floor,
        "qualityFloorPreserved": True,
        "advisoryOnly": True,
        "autoApply": False,
        "changes": [],
        "reasons": [{"code": item.get("code", "optimizer-blocked")} for item in blockers[:12]],
        "expectedTradeoffs": {},
        "approval": {"required": True, "target": "new-project-profile-or-plan-revision", "frozenPlanMutation": False},
        "rollback": {"strategy": "keep current profile", "requiresReview": True},
        "statisticsDigest": statistics.get("statisticsDigest"),
        "evaluationDigest": evaluation.get("evaluationDigest"),
        "productionPromotionClaimed": False,
    }


def _task_profile_id(task: dict[str, Any]) -> str | None:
    for key in ("candidateProfileId", "profileId", "candidate"):
        if isinstance(task.get(key), str) and task[key]:
            return task[key]
    return None


def _quality_pass(task: dict[str, Any]) -> bool:
    if isinstance(task.get("qualityPass"), bool):
        return task["qualityPass"]
    if isinstance(task.get("qualityStatus"), str):
        return task["qualityStatus"] in {"PASS", "ACCEPTED", "READY_FOR_FINALIZATION"}
    return task.get("status") in {"PASS", "ACCEPTED", "READY_FOR_FINALIZATION"}


def _average_or_none(values: list[float], fallback: Any) -> float | None:
    if values:
        return round(mean(values), 6)
    return round(float(fallback), 6) if _number_or_none(fallback) is not None else None


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else 0.0


def _number_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def _bounded_int(value: Any, minimum: int, maximum: int) -> int | None:
    number = _number_or_none(value)
    if number is None:
        return None
    return max(minimum, min(maximum, int(number)))


def _safe_route_class(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return "unknown"
    normalized = value.lower()
    allowed = ("local", "small", "standard", "strong", "reasoning", "code", "review", "research", "release", "general", "unknown")
    return value if any(item in normalized for item in allowed) else "external-neutral"


def _string(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _value_at(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _rate(value: int, total: int) -> float:
    return round(value / total, 6) if total else 0.0


__all__ = [
    "build_audit_optimization_report",
    "build_audit_statistics",
    "evaluate_candidate_profiles",
    "recommend_audit_optimization",
    "render_audit_optimization_terminal",
    "validate_audit_optimization_report",
]
