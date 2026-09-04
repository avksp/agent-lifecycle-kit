"""Shared workflow resource metrics with explicit availability semantics."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

WORKFLOW_RESOURCE_SUMMARY_SCHEMA = "agent-workflow-resource-summary.v1"
SOURCE_AVAILABILITY_STATUSES = (
    "MEASURED",
    "ESTIMATED",
    "TIME_WINDOW_ONLY",
    "UNAVAILABLE",
)
DERIVED_AGGREGATE_STATUSES = ("MIXED", "PARTIAL")
WORKFLOW_METRIC_KEYS = (
    "modelInputTokens",
    "modelCachedInputTokens",
    "modelOutputTokens",
    "modelTurns",
    "toolCalls",
    "toolWallMs",
    "toolOutputBytes",
    "packetBytes",
    "controllerTransitions",
    "requiredGateCount",
    "passedGateCount",
    "failedGateCount",
    "elapsedWallMs",
    "parallelComputeMs",
)
MAX_WORKFLOW_METRIC_VALUE = (1 << 63) - 1

_TIME_WINDOW_METRICS = {"elapsedWallMs", "toolWallMs"}


def build_workflow_metric_set(
    values: dict[str, Any] | None = None,
    *,
    inferred_measured: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Normalize one complete source metric set without inventing zero values."""

    supplied = {} if values is None else values
    if not isinstance(supplied, dict):
        raise LifecycleError("workflow-metrics-invalid", "workflow metrics must be an object")
    unknown = set(supplied).difference(WORKFLOW_METRIC_KEYS)
    if unknown:
        raise LifecycleError(
            "workflow-metrics-invalid",
            "workflow metrics contain unsupported fields",
            {"fields": sorted(unknown)},
        )
    inferred = {} if inferred_measured is None else inferred_measured
    if not isinstance(inferred, dict) or set(inferred).difference(WORKFLOW_METRIC_KEYS):
        raise LifecycleError("workflow-metrics-invalid", "inferred workflow metrics are invalid")
    result: dict[str, dict[str, Any]] = {}
    for key in WORKFLOW_METRIC_KEYS:
        if key in supplied:
            raw_metric = supplied[key]
        elif key in inferred:
            raw_metric = {"status": "MEASURED", "value": inferred[key]}
        else:
            raw_metric = {"status": "UNAVAILABLE", "value": None}
        result[key] = _source_metric(raw_metric, key)
    return result


def build_workflow_resource_summary(
    metric_sets: list[dict[str, Any]],
    *,
    enclosing_elapsed_wall: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate additive metrics while keeping enclosing wall time separate."""

    if not isinstance(metric_sets, list):
        raise LifecycleError("workflow-metrics-invalid", "workflow metric sets must be an array")
    normalized = [build_workflow_metric_set(item) for item in metric_sets]
    raw_enclosing = (
        {"status": "UNAVAILABLE", "value": None} if enclosing_elapsed_wall is None else enclosing_elapsed_wall
    )
    enclosing = _source_metric(raw_enclosing, "elapsedWallMs")
    metrics = {key: _aggregate_metric(key, normalized, enclosing) for key in WORKFLOW_METRIC_KEYS}
    body = {
        "schemaVersion": WORKFLOW_RESOURCE_SUMMARY_SCHEMA,
        "status": "PASS",
        "sourceAvailabilityStatuses": list(SOURCE_AVAILABILITY_STATUSES),
        "derivedAggregateStatuses": list(DERIVED_AGGREGATE_STATUSES),
        "sourceCount": len(normalized),
        "enclosingElapsedWall": enclosing,
        "metrics": metrics,
        "productionPromotionClaimed": False,
    }
    return {**body, "summaryDigest": canonical_digest(body)}


def validate_workflow_resource_summary(summary: Any) -> dict[str, Any]:
    """Validate status separation, bounded values and summary integrity."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(summary, dict):
        return _validation(summary, [{"code": "workflow-resource-summary-object-invalid"}])
    if summary.get("schemaVersion") != WORKFLOW_RESOURCE_SUMMARY_SCHEMA:
        blockers.append({"code": "workflow-resource-summary-schema-invalid"})
    if summary.get("status") != "PASS":
        blockers.append({"code": "workflow-resource-summary-status-invalid"})
    if summary.get("sourceAvailabilityStatuses") != list(SOURCE_AVAILABILITY_STATUSES):
        blockers.append({"code": "workflow-resource-source-statuses-invalid"})
    if summary.get("derivedAggregateStatuses") != list(DERIVED_AGGREGATE_STATUSES):
        blockers.append({"code": "workflow-resource-derived-statuses-invalid"})
    source_count = summary.get("sourceCount")
    if not isinstance(source_count, int) or isinstance(source_count, bool) or source_count < 0:
        blockers.append({"code": "workflow-resource-source-count-invalid"})
    _validate_metric(summary.get("enclosingElapsedWall"), "elapsedWallMs", blockers, aggregate=False)
    metrics = summary.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != set(WORKFLOW_METRIC_KEYS):
        blockers.append({"code": "workflow-resource-metric-set-invalid"})
    else:
        for key in WORKFLOW_METRIC_KEYS:
            _validate_metric(metrics[key], key, blockers, aggregate=True)
    if summary.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "workflow-resource-production-claim"})
    expected = canonical_digest({key: value for key, value in summary.items() if key != "summaryDigest"})
    if summary.get("summaryDigest") != expected:
        blockers.append({"code": "workflow-resource-summary-digest-mismatch"})
    return _validation(summary, blockers)


def _source_metric(value: Any, name: str) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    _validate_metric(value, name, blockers, aggregate=False)
    if blockers:
        raise LifecycleError(
            "workflow-metric-invalid",
            f"{name} workflow metric is invalid",
            {"blockers": blockers},
        )
    return {"status": value["status"], "value": value["value"]}


def _validate_metric(value: Any, name: str, blockers: list[dict[str, Any]], *, aggregate: bool) -> None:
    allowed = set(SOURCE_AVAILABILITY_STATUSES)
    if aggregate:
        allowed.update(DERIVED_AGGREGATE_STATUSES)
    if not isinstance(value, dict) or set(value) != {"status", "value"} or value.get("status") not in allowed:
        blockers.append({"code": "workflow-metric-shape-invalid", "metric": name})
        return
    status = value["status"]
    metric_value = value["value"]
    if not aggregate and status in DERIVED_AGGREGATE_STATUSES:
        blockers.append({"code": "workflow-metric-derived-source-status", "metric": name})
    if status == "TIME_WINDOW_ONLY" and name not in _TIME_WINDOW_METRICS:
        blockers.append({"code": "workflow-metric-time-window-invalid", "metric": name})
    if status == "UNAVAILABLE":
        if metric_value is not None:
            blockers.append({"code": "workflow-metric-unavailable-value", "metric": name})
    elif (
        not isinstance(metric_value, int)
        or isinstance(metric_value, bool)
        or metric_value < 0
        or metric_value > MAX_WORKFLOW_METRIC_VALUE
    ):
        blockers.append({"code": "workflow-metric-value-invalid", "metric": name})


def _aggregate_metric(
    name: str,
    metric_sets: list[dict[str, dict[str, Any]]],
    enclosing: dict[str, Any],
) -> dict[str, Any]:
    if name == "elapsedWallMs":
        if enclosing["status"] != "UNAVAILABLE":
            return dict(enclosing)
        if len(metric_sets) == 1:
            return dict(metric_sets[0][name])
        return {"status": "UNAVAILABLE", "value": None}
    source_metrics = [item[name] for item in metric_sets]
    known = [item for item in source_metrics if item["status"] != "UNAVAILABLE"]
    if not known:
        return {"status": "UNAVAILABLE", "value": None}
    statuses = {item["status"] for item in known}
    if len(known) != len(source_metrics):
        status = "PARTIAL"
    elif len(statuses) > 1:
        status = "MIXED"
    else:
        status = next(iter(statuses))
    total = sum(item["value"] for item in known)
    if total > MAX_WORKFLOW_METRIC_VALUE:
        raise LifecycleError(
            "workflow-metric-aggregate-overflow",
            f"{name} aggregate exceeds the workflow metric limit",
            {"metric": name, "maxValue": MAX_WORKFLOW_METRIC_VALUE},
        )
    return {"status": status, "value": total}


def _validation(summary: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-workflow-resource-summary-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "summaryDigest": summary.get("summaryDigest") if isinstance(summary, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


__all__ = [
    "DERIVED_AGGREGATE_STATUSES",
    "MAX_WORKFLOW_METRIC_VALUE",
    "SOURCE_AVAILABILITY_STATUSES",
    "WORKFLOW_METRIC_KEYS",
    "WORKFLOW_RESOURCE_SUMMARY_SCHEMA",
    "build_workflow_metric_set",
    "build_workflow_resource_summary",
    "validate_workflow_resource_summary",
]
