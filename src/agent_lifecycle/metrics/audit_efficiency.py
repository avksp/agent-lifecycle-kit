"""Quality-preserving efficiency metrics for independent audit evidence."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.audit_optimization_schemas import (
    AUDIT_EFFICIENCY_INPUT_SCHEMA,
    AUDIT_EFFICIENCY_REPORT_SCHEMA,
)

METRIC_STATUSES = ("MEASURED", "ESTIMATED", "TIME_WINDOW_ONLY", "MIXED", "UNAVAILABLE")
_VIEW_NAMES = ("alkProcess", "implementation", "audit", "postAuditRemediation")
_VIEW_METRICS = ("tokens", "elapsedWallMs", "computeMs")
_OUTCOME_METRICS = (
    "confirmedFindings",
    "rejectedFindings",
    "noVerdictSessions",
    "auditSessions",
    "remediationEvents",
)


def build_audit_efficiency_input(
    *,
    release_id: str,
    source_revision: str,
    source_lineage_digest: str,
    quality_floor: str,
    views: dict[str, Any],
    outcomes: dict[str, Any],
    totals: dict[str, Any],
) -> dict[str, Any]:
    """Build a portable accounting input without inventing unavailable values."""

    body = {
        "schemaVersion": AUDIT_EFFICIENCY_INPUT_SCHEMA,
        "releaseId": release_id,
        "sourceRevision": source_revision,
        "sourceLineageDigest": source_lineage_digest,
        "qualityFloor": quality_floor,
        "views": views,
        "outcomes": outcomes,
        "totals": totals,
        "productionPromotionClaimed": False,
    }
    result = {**body, "inputDigest": canonical_digest(body)}
    validation = validate_audit_efficiency_input(result)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "audit-efficiency-input-invalid",
            "audit efficiency input is invalid",
            {"validation": validation},
        )
    return result


def validate_audit_efficiency_input(value: Any) -> dict[str, Any]:
    """Validate metric availability, lineage and the canonical input digest."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(value, dict):
        blockers.append({"code": "audit-efficiency-input-object-invalid"})
        return _input_validation(value, blockers)
    if value.get("schemaVersion") != AUDIT_EFFICIENCY_INPUT_SCHEMA:
        blockers.append({"code": "audit-efficiency-input-schema-invalid"})
    for field in ("releaseId", "sourceRevision", "qualityFloor"):
        if not isinstance(value.get(field), str) or not value[field]:
            blockers.append({"code": "audit-efficiency-input-field-missing", "field": field})
    if not _is_digest(value.get("sourceLineageDigest")):
        blockers.append({"code": "audit-efficiency-source-lineage-invalid"})
    views = value.get("views")
    if not isinstance(views, dict):
        blockers.append({"code": "audit-efficiency-views-invalid"})
    else:
        for view_name in _VIEW_NAMES:
            view = views.get(view_name)
            if not isinstance(view, dict):
                blockers.append({"code": "audit-efficiency-view-missing", "view": view_name})
                continue
            for metric_name in _VIEW_METRICS:
                _validate_metric(
                    view.get(metric_name),
                    blockers,
                    code="audit-efficiency-view-metric-invalid",
                    location=f"views.{view_name}.{metric_name}",
                )
    outcomes = value.get("outcomes")
    if not isinstance(outcomes, dict):
        blockers.append({"code": "audit-efficiency-outcomes-invalid"})
    else:
        for metric_name in _OUTCOME_METRICS:
            _validate_metric(
                outcomes.get(metric_name),
                blockers,
                code="audit-efficiency-outcome-metric-invalid",
                location=f"outcomes.{metric_name}",
                integer=True,
            )
    totals = value.get("totals")
    if not isinstance(totals, dict):
        blockers.append({"code": "audit-efficiency-totals-invalid"})
    else:
        _validate_metric(
            totals.get("elapsedWallMs"),
            blockers,
            code="audit-efficiency-total-metric-invalid",
            location="totals.elapsedWallMs",
        )
    if value.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "audit-efficiency-production-claim"})
    expected = canonical_digest({key: item for key, item in value.items() if key != "inputDigest"})
    if value.get("inputDigest") != expected:
        blockers.append({"code": "audit-efficiency-input-digest-mismatch"})
    return _input_validation(value, blockers)


def build_audit_efficiency_report(
    measurement: dict[str, Any],
    *,
    comparison_measurements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Report audit use without turning one release into a reduction claim."""

    validation = validate_audit_efficiency_input(measurement)
    blockers = list(validation["blockers"])
    comparisons = list(comparison_measurements or [])
    comparison_validations = [validate_audit_efficiency_input(item) for item in comparisons]
    for index, item in enumerate(comparison_validations):
        if item["status"] != "PASS":
            blockers.append({"code": "audit-efficiency-comparison-invalid", "index": index})

    metrics = _efficiency_metrics(measurement) if validation["status"] == "PASS" else _empty_metrics()
    comparison = _comparison(measurement, comparisons, blockers)
    if blockers:
        status = "FAIL"
    elif comparison["sampleCount"] < 2:
        status = "NO_COMPARISON"
    else:
        status = "PASS"
    body = {
        "schemaVersion": AUDIT_EFFICIENCY_REPORT_SCHEMA,
        "status": status,
        "releaseId": measurement.get("releaseId") if isinstance(measurement, dict) else None,
        "qualityFloor": measurement.get("qualityFloor") if isinstance(measurement, dict) else None,
        "qualityFloorPreserved": True,
        "metrics": metrics,
        "comparison": comparison,
        "advisoryOnly": True,
        "autoApply": False,
        "blockers": blockers,
        "inputDigest": measurement.get("inputDigest") if isinstance(measurement, dict) else None,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def validate_audit_efficiency_report(report: Any) -> dict[str, Any]:
    """Validate report integrity and the quality-preserving authority boundary."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(report, dict):
        blockers.append({"code": "audit-efficiency-report-object-invalid"})
        return _report_validation(report, blockers)
    if report.get("schemaVersion") != AUDIT_EFFICIENCY_REPORT_SCHEMA:
        blockers.append({"code": "audit-efficiency-report-schema-invalid"})
    if report.get("status") not in {"PASS", "NO_COMPARISON", "FAIL"}:
        blockers.append({"code": "audit-efficiency-report-status-invalid"})
    if report.get("qualityFloorPreserved") is not True:
        blockers.append({"code": "audit-efficiency-quality-floor-lowered"})
    if report.get("advisoryOnly") is not True or report.get("autoApply") is not False:
        blockers.append({"code": "audit-efficiency-authority-boundary"})
    if report.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "audit-efficiency-production-claim"})
    comparison = report.get("comparison") if isinstance(report.get("comparison"), dict) else {}
    if comparison.get("sampleCount") == 1:
        for field in ("tokenReductionPercent", "wallReductionPercent"):
            metric = comparison.get(field)
            if metric != _unavailable("comparison-sample-required"):
                blockers.append({"code": "audit-efficiency-single-sample-reduction", "field": field})
    expected = canonical_digest({key: item for key, item in report.items() if key != "reportDigest"})
    if report.get("reportDigest") != expected:
        blockers.append({"code": "audit-efficiency-report-digest-mismatch"})
    return _report_validation(report, blockers)


def _efficiency_metrics(measurement: dict[str, Any]) -> dict[str, Any]:
    audit = measurement["views"]["audit"]
    remediation = measurement["views"]["postAuditRemediation"]
    outcomes = measurement["outcomes"]
    totals = measurement["totals"]
    confirmed = outcomes["confirmedFindings"]
    rejected = outcomes["rejectedFindings"]
    no_verdict = outcomes["noVerdictSessions"]
    audit_sessions = outcomes["auditSessions"]
    return {
        "auditTokens": audit["tokens"],
        "auditWallMs": audit["elapsedWallMs"],
        "auditComputeMs": audit["computeMs"],
        "confirmedFindings": confirmed,
        "rejectedFindings": rejected,
        "noVerdictSessions": no_verdict,
        "remediationEvents": outcomes["remediationEvents"],
        "tokensPerConfirmedFinding": _per_unit(audit["tokens"], confirmed, "confirmed-findings-unavailable"),
        "wallMsPerConfirmedFinding": _per_unit(
            audit["elapsedWallMs"], confirmed, "confirmed-findings-unavailable"
        ),
        "noAcceptanceEffectShare": _share(no_verdict, audit_sessions, "audit-outcomes-unavailable"),
        "rejectedFindingShare": _share(
            rejected,
            _sum_metrics(confirmed, rejected),
            "finding-dispositions-unavailable",
        ),
        "postAuditRemediationShare": _share(
            remediation["elapsedWallMs"],
            totals["elapsedWallMs"],
            "remediation-window-unavailable",
        ),
    }


def _comparison(
    measurement: dict[str, Any],
    comparisons: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    sample_count = 1 + len(comparisons)
    unavailable = _unavailable("comparison-sample-required")
    if sample_count < 2 or blockers:
        return {
            "sampleCount": sample_count,
            "tokenReductionPercent": unavailable,
            "wallReductionPercent": unavailable,
            "qualityFloorPreserved": True,
        }
    baseline = comparisons[0]
    if baseline.get("qualityFloor") != measurement.get("qualityFloor"):
        blockers.append({"code": "audit-efficiency-comparison-quality-floor-mismatch"})
        return {
            "sampleCount": sample_count,
            "tokenReductionPercent": _unavailable("quality-floor-mismatch"),
            "wallReductionPercent": _unavailable("quality-floor-mismatch"),
            "qualityFloorPreserved": False,
        }
    unavailable_locations = _comparison_unavailable_locations(measurement, baseline)
    if unavailable_locations:
        blockers.append(
            {
                "code": "audit-efficiency-comparison-telemetry-unavailable",
                "locations": unavailable_locations,
            }
        )
        return {
            "sampleCount": sample_count,
            "tokenReductionPercent": _unavailable("comparison-telemetry-unavailable"),
            "wallReductionPercent": _unavailable("comparison-telemetry-unavailable"),
            "qualityFloorPreserved": True,
        }
    return {
        "sampleCount": sample_count,
        "tokenReductionPercent": _reduction(
            baseline["views"]["audit"]["tokens"], measurement["views"]["audit"]["tokens"]
        ),
        "wallReductionPercent": _reduction(
            baseline["views"]["audit"]["elapsedWallMs"],
            measurement["views"]["audit"]["elapsedWallMs"],
        ),
        "qualityFloorPreserved": True,
    }


def _validate_metric(
    metric: Any,
    blockers: list[dict[str, Any]],
    *,
    code: str,
    location: str,
    integer: bool = False,
) -> None:
    if not isinstance(metric, dict) or metric.get("status") not in METRIC_STATUSES:
        blockers.append({"code": code, "location": location})
        return
    value = metric.get("value")
    if metric["status"] == "UNAVAILABLE":
        if value is not None:
            blockers.append({"code": "audit-efficiency-unavailable-has-value", "location": location})
        return
    valid_number = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    if not valid_number or (integer and not isinstance(value, int)):
        blockers.append({"code": code, "location": location})


def _per_unit(numerator: dict[str, Any], denominator: dict[str, Any], reason: str) -> dict[str, Any]:
    if not _available(numerator) or not _available(denominator) or denominator["value"] <= 0:
        return _unavailable(reason)
    return {
        "status": _derived_status(numerator, denominator),
        "value": round(numerator["value"] / denominator["value"], 6),
    }


def _comparison_unavailable_locations(*measurements: dict[str, Any]) -> list[str]:
    locations: list[str] = []
    for measurement in measurements:
        release_id = measurement.get("releaseId", "unknown")
        for view_name in _VIEW_NAMES:
            for metric_name in ("tokens", "elapsedWallMs"):
                metric = measurement["views"][view_name][metric_name]
                if not _available(metric):
                    locations.append(f"{release_id}:views.{view_name}.{metric_name}")
    return sorted(locations)


def _share(numerator: dict[str, Any], denominator: dict[str, Any], reason: str) -> dict[str, Any]:
    if not _available(numerator) or not _available(denominator) or denominator["value"] <= 0:
        return _unavailable(reason)
    return {
        "status": _derived_status(numerator, denominator),
        "value": round(numerator["value"] / denominator["value"], 6),
    }


def _sum_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not _available(left) or not _available(right):
        return _unavailable("source-metrics-unavailable")
    return {"status": _derived_status(left, right), "value": left["value"] + right["value"]}


def _reduction(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    if not _available(baseline) or not _available(current) or baseline["value"] <= 0:
        return _unavailable("comparison-metric-unavailable")
    value = (baseline["value"] - current["value"]) / baseline["value"] * 100
    return {"status": _derived_status(baseline, current), "value": round(value, 6)}


def _derived_status(*metrics: dict[str, Any]) -> str:
    statuses = {metric.get("status") for metric in metrics}
    for status in ("MIXED", "TIME_WINDOW_ONLY", "ESTIMATED"):
        if status in statuses:
            return status
    return "MEASURED"


def _available(metric: Any) -> bool:
    return (
        isinstance(metric, dict)
        and metric.get("status") != "UNAVAILABLE"
        and isinstance(metric.get("value"), (int, float))
        and not isinstance(metric.get("value"), bool)
    )


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "value": None, "reason": reason}


def _empty_metrics() -> dict[str, Any]:
    return {
        name: _unavailable("input-invalid")
        for name in (
            "auditTokens",
            "auditWallMs",
            "auditComputeMs",
            "confirmedFindings",
            "rejectedFindings",
            "noVerdictSessions",
            "remediationEvents",
            "tokensPerConfirmedFinding",
            "wallMsPerConfirmedFinding",
            "noAcceptanceEffectShare",
            "rejectedFindingShare",
            "postAuditRemediationShare",
        )
    }


def _input_validation(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-audit-efficiency-input-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "releaseId": value.get("releaseId") if isinstance(value, dict) else None,
        "blockers": blockers,
        "inputDigest": value.get("inputDigest") if isinstance(value, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _report_validation(value: Any, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-audit-efficiency-report-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "releaseId": value.get("releaseId") if isinstance(value, dict) else None,
        "blockers": blockers,
        "reportDigest": value.get("reportDigest") if isinstance(value, dict) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "METRIC_STATUSES",
    "build_audit_efficiency_input",
    "build_audit_efficiency_report",
    "validate_audit_efficiency_input",
    "validate_audit_efficiency_report",
]
