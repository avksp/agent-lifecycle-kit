"""Validate lifecycle cost reports for resource-disciplined runs."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

COST_REPORT_SCHEMA = "agent-lifecycle-cost-report.v1"
COST_VALIDATION_SCHEMA = "agent-lifecycle-cost-validation.v1"
COST_GENERATION_SCHEMA = "agent-lifecycle-cost-generation.v1"
COST_SUMMARY_SCHEMA = "agent-lifecycle-cost-summary.v1"

COST_CATEGORIES = ("implementation", "productValidation", "pipelineCompliance", "coordination")
USAGE_CONFIDENCE_STATES = ("ATTESTED", "ESTIMATED", "MISSING")

DEFAULT_MODE_LIMITS: dict[str, dict[str, float | int]] = {
    "light": {"maxPipelineTokenShare": 0.20, "maxPipelineStepShare": 0.30, "maxPipelineTokens": 1500, "maxPipelineSteps": 3},
    "standard": {"maxPipelineTokenShare": 0.30, "maxPipelineStepShare": 0.40, "maxPipelineTokens": 6000, "maxPipelineSteps": 6},
    "strict": {"maxPipelineTokenShare": 0.45, "maxPipelineStepShare": 0.55, "maxPipelineTokens": 20000, "maxPipelineSteps": 12},
    "release": {"maxPipelineTokenShare": 0.60, "maxPipelineStepShare": 0.70, "maxPipelineTokens": 50000, "maxPipelineSteps": 24},
}


def validate_lifecycle_cost_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate a lifecycle cost report and return a compact receipt."""

    blockers: list[dict[str, Any]] = []
    if report.get("schemaVersion") != COST_REPORT_SCHEMA:
        blockers.append({"code": "cost-report-schema", "message": "unsupported lifecycle cost report schemaVersion"})
    if report.get("productionPromotionClaimed") is True:
        blockers.append({"code": "cost-report-production-claim", "message": "cost reports must not claim production promotion"})
    mode = report.get("mode")
    if mode not in DEFAULT_MODE_LIMITS:
        blockers.append({"code": "cost-report-mode", "mode": mode})
        mode = None
    entries = report.get("entries")
    if not isinstance(entries, list) or not entries:
        blockers.append({"code": "cost-report-entries", "message": "entries must be a non-empty array"})
        entries = []
    totals = _empty_totals()
    for index, entry in enumerate(entries):
        _add_entry(index, entry, totals, blockers)
    totals["overall"] = {
        "tokens": sum(totals[category]["tokens"] for category in COST_CATEGORIES),
        "steps": sum(totals[category]["steps"] for category in COST_CATEGORIES),
    }
    usage_confidence = summarize_usage_confidence(entries)
    limits = _limits(report.get("limits"), mode)
    ratios = cost_ratios(totals)
    if mode is not None:
        _check_pipeline_limits(totals, ratios, limits, report.get("overLimitReason"), blockers)
    body = {
        "schemaVersion": COST_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "mode": mode,
        "totals": totals,
        "ratios": ratios,
        "usageConfidence": usage_confidence,
        "limits": limits,
        "blockers": blockers,
        "reportDigest": canonical_digest(report),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_lifecycle_cost_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") == "FAIL":
        raise LifecycleError("lifecycle-cost-validation-failed", "lifecycle cost validation failed", {"validation": validation})
    return validation


def _empty_totals() -> dict[str, dict[str, int]]:
    return {category: {"tokens": 0, "steps": 0} for category in COST_CATEGORIES}


def cost_entry_totals(entries: list[Any]) -> dict[str, dict[str, int]]:
    totals = _empty_totals()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        category = entry.get("category")
        tokens = entry.get("tokens")
        steps = entry.get("steps")
        if category in COST_CATEGORIES and isinstance(tokens, int) and isinstance(steps, int):
            totals[category]["tokens"] += max(0, tokens)
            totals[category]["steps"] += max(0, steps)
    totals["overall"] = {
        "tokens": sum(totals[category]["tokens"] for category in COST_CATEGORIES),
        "steps": sum(totals[category]["steps"] for category in COST_CATEGORIES),
    }
    return totals


def _add_entry(index: int, entry: Any, totals: dict[str, dict[str, int]], blockers: list[dict[str, Any]]) -> None:
    if not isinstance(entry, dict):
        blockers.append({"code": "cost-entry-type", "index": index, "message": "entry must be an object"})
        return
    category = entry.get("category")
    if category not in COST_CATEGORIES:
        blockers.append({"code": "cost-entry-category", "index": index, "category": category})
        return
    tokens = _non_negative_int(entry.get("tokens"), field="tokens", index=index, blockers=blockers)
    steps = _non_negative_int(entry.get("steps"), field="steps", index=index, blockers=blockers)
    confidence = entry.get("usageConfidence")
    if confidence is not None and confidence not in USAGE_CONFIDENCE_STATES:
        blockers.append({"code": "cost-entry-usage-confidence", "index": index, "usageConfidence": confidence})
    if tokens is None or steps is None:
        return
    if tokens == 0 and steps == 0:
        blockers.append({"code": "cost-entry-empty", "index": index})
        return
    totals[category]["tokens"] += tokens
    totals[category]["steps"] += steps


def _non_negative_int(value: Any, *, field: str, index: int, blockers: list[dict[str, Any]]) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        blockers.append({"code": "cost-entry-numeric", "index": index, "field": field, "value": value})
        return None
    return value


def summarize_usage_confidence(entries: list[Any]) -> dict[str, int]:
    summary = {
        "attestedEntries": 0,
        "attestedTokens": 0,
        "estimatedEntries": 0,
        "estimatedTokens": 0,
        "missingEntries": 0,
        "missingTokens": 0,
        "unspecifiedEntries": 0,
        "unspecifiedTokens": 0,
    }
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        confidence = entry.get("usageConfidence")
        tokens = entry.get("tokens") if isinstance(entry.get("tokens"), int) else 0
        if confidence == "ATTESTED":
            summary["attestedEntries"] += 1
            summary["attestedTokens"] += max(0, tokens)
        elif confidence == "ESTIMATED":
            summary["estimatedEntries"] += 1
            summary["estimatedTokens"] += max(0, tokens)
        elif confidence == "MISSING":
            summary["missingEntries"] += 1
            summary["missingTokens"] += max(0, tokens)
        else:
            summary["unspecifiedEntries"] += 1
            summary["unspecifiedTokens"] += max(0, tokens)
    return summary


def _limits(raw_limits: Any, mode: str | None) -> dict[str, float | int]:
    if mode is None:
        return {}
    defaults = dict(DEFAULT_MODE_LIMITS[mode])
    if not isinstance(raw_limits, dict):
        return defaults
    override = raw_limits.get(mode)
    if not isinstance(override, dict):
        return defaults
    for key, default in defaults.items():
        value = override.get(key)
        if isinstance(default, float) and isinstance(value, (int, float)) and not isinstance(value, bool):
            defaults[key] = float(value)
        elif isinstance(default, int) and isinstance(value, int) and not isinstance(value, bool):
            defaults[key] = value
    return defaults


def cost_ratios(totals: dict[str, dict[str, int]]) -> dict[str, float]:
    overall_tokens = totals["overall"]["tokens"]
    overall_steps = totals["overall"]["steps"]
    pipeline_tokens = totals["pipelineCompliance"]["tokens"]
    pipeline_steps = totals["pipelineCompliance"]["steps"]
    return {
        "pipelineTokenShare": round(pipeline_tokens / overall_tokens, 6) if overall_tokens else 0.0,
        "pipelineStepShare": round(pipeline_steps / overall_steps, 6) if overall_steps else 0.0,
    }


def _check_pipeline_limits(
    totals: dict[str, dict[str, int]],
    ratios: dict[str, float],
    limits: dict[str, float | int],
    over_limit_reason: Any,
    blockers: list[dict[str, Any]],
) -> None:
    over = []
    if ratios["pipelineTokenShare"] > float(limits["maxPipelineTokenShare"]):
        over.append("maxPipelineTokenShare")
    if ratios["pipelineStepShare"] > float(limits["maxPipelineStepShare"]):
        over.append("maxPipelineStepShare")
    if totals["pipelineCompliance"]["tokens"] > int(limits["maxPipelineTokens"]):
        over.append("maxPipelineTokens")
    if totals["pipelineCompliance"]["steps"] > int(limits["maxPipelineSteps"]):
        over.append("maxPipelineSteps")
    if not over:
        return
    if not isinstance(over_limit_reason, str) or not over_limit_reason.strip():
        blockers.append({"code": "pipeline-compliance-over-limit", "limits": sorted(set(over))})
