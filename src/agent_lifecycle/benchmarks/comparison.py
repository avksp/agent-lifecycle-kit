"""Quality-first comparison of deterministic reference-task evaluations."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.benchmarks.contracts import LoadedSuite
from agent_lifecycle.benchmarks.qualification import qualify_benchmark_runs
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.benchmark_schemas import (
    ROUTE_COMPARISON_SCHEMA,
    ROUTE_COMPARISON_VALIDATION_SCHEMA,
)

COMPARISON_SCHEMA = "agent-reference-task-comparison.v1"
COMPARISON_VALIDATION_SCHEMA = "agent-reference-task-comparison-validation.v1"


def compare_reference_task_evaluations(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """Compare one candidate only after quality and lineage are comparable."""

    blockers = [*_evaluation_blockers(baseline, "baseline"), *_evaluation_blockers(candidate, "candidate")]
    lineage = _lineage_comparison(baseline, candidate)
    blockers.extend(lineage["blockers"])
    quality = _quality_comparison(baseline, candidate)
    blockers.extend(quality["blockers"])
    resources = _resource_comparison(baseline, candidate)
    quality_pass = not lineage["blockers"] and not quality["blockers"]
    exact_adoption = (
        quality_pass
        and quality["candidateFalseAcceptances"] == 0
        and resources["exactSavingsClaimed"]
        and resources["resourceRegressionFree"]
        and resources["measurementComplete"]
    )
    body = {
        "schemaVersion": COMPARISON_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "lineage": lineage,
        "quality": quality,
        "resources": resources,
        "decision": {
            "qualityFirst": True,
            "qualityRegressionTolerance": 0,
            "falseAcceptanceTolerance": 0,
            "exactSavingsSupported": quality_pass and resources["comparableAttestedUsage"],
            "automaticStrategyAdoptionEligible": exact_adoption,
            "advisoryOnly": not exact_adoption,
        },
        "sourceEvaluationDigests": {
            "baseline": baseline.get("evaluationDigest"),
            "candidate": candidate.get("evaluationDigest"),
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "comparisonDigest": canonical_digest(body)}


def validate_reference_task_comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if comparison.get("schemaVersion") != COMPARISON_SCHEMA:
        blockers.append({"code": "comparison-schema-invalid"})
    embedded = comparison.get("blockers")
    if not isinstance(embedded, list) or not all(isinstance(item, dict) for item in embedded):
        blockers.append({"code": "comparison-blockers-invalid"})
        embedded = []
    status = comparison.get("status")
    if status == "PASS" and embedded:
        blockers.append({"code": "comparison-pass-with-blockers"})
    if status == "FAIL" and not embedded:
        blockers.append({"code": "comparison-fail-without-blockers"})
    if status not in {"PASS", "FAIL"}:
        blockers.append({"code": "comparison-status-invalid"})
    decision = comparison.get("decision") if isinstance(comparison.get("decision"), dict) else {}
    resources = comparison.get("resources") if isinstance(comparison.get("resources"), dict) else {}
    if decision.get("automaticStrategyAdoptionEligible") is True and resources.get("comparableAttestedUsage") is not True:
        blockers.append({"code": "comparison-auto-adoption-without-attested-usage"})
    if decision.get("automaticStrategyAdoptionEligible") is True and (
        resources.get("exactSavingsClaimed") is not True
        or resources.get("resourceRegressionFree") is not True
        or resources.get("measurementComplete") is not True
    ):
        blockers.append({"code": "comparison-auto-adoption-without-complete-efficiency-proof"})
    if decision.get("qualityFirst") is not True:
        blockers.append({"code": "comparison-quality-first-missing"})
    for field in ("modelCallsStarted", "hostLaunchStarted", "productionPromotionClaimed"):
        if comparison.get(field) is not False:
            blockers.append({"code": "comparison-side-effect-claim", "field": field})
    expected = canonical_digest({key: value for key, value in comparison.items() if key != "comparisonDigest"})
    if comparison.get("comparisonDigest") != expected:
        blockers.append({"code": "comparison-digest-mismatch"})
    body = {
        "schemaVersion": COMPARISON_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "comparisonStatus": status if status in {"PASS", "FAIL"} else None,
        "blockers": blockers,
        "comparisonDigest": comparison.get("comparisonDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def compare_qualified_routes(
    baseline_receipts: list[dict[str, Any]],
    candidate_receipts: list[dict[str, Any]],
    *,
    sample: dict[str, Any] | None = None,
    suite: LoadedSuite | None = None,
    minimums: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare two qualified route pools while reporting changed axes."""

    baseline = qualify_benchmark_runs(baseline_receipts, sample=sample, suite=suite, minimums=minimums)
    candidate = qualify_benchmark_runs(candidate_receipts, sample=sample, suite=suite, minimums=minimums)
    blockers: list[dict[str, Any]] = []
    if baseline["status"] != "QUALIFIED":
        blockers.append({"code": "baseline-not-qualified", "status": baseline["status"]})
    if candidate["status"] != "QUALIFIED":
        blockers.append({"code": "candidate-not-qualified", "status": candidate["status"]})
    base_tasks = {receipt.get("taskId") for receipt in baseline_receipts}
    candidate_tasks = {receipt.get("taskId") for receipt in candidate_receipts}
    if base_tasks != candidate_tasks:
        blockers.append({"code": "comparison-task-pool-mismatch"})
    base_environment = _axis_values(baseline_receipts, "environment", "environmentDigest")
    candidate_environment = _axis_values(candidate_receipts, "environment", "environmentDigest")
    base_scorer = _axis_values(baseline_receipts, "scorer", "scorerDigest")
    candidate_scorer = _axis_values(candidate_receipts, "scorer", "scorerDigest")
    changed_axes = []
    if base_environment != candidate_environment:
        changed_axes.append("environment")
    if base_scorer != candidate_scorer:
        changed_axes.append("scorer")
    if changed_axes:
        blockers.append({"code": "comparison-axis-mismatch", "axes": changed_axes})
    base_route = _first_axis(baseline_receipts, "route", "routeDigest")
    candidate_route = _first_axis(candidate_receipts, "route", "routeDigest")
    if base_route == candidate_route:
        blockers.append({"code": "comparison-route-not-distinct"})
    base_quality = _aggregate_quality(baseline)
    candidate_quality = _aggregate_quality(candidate)
    quality_blockers: list[dict[str, Any]] = []
    if candidate_quality["falseAcceptanceCount"] > base_quality["falseAcceptanceCount"]:
        quality_blockers.append({"code": "comparison-new-false-acceptance"})
    if candidate_quality["criteriaPassed"] < base_quality["criteriaPassed"]:
        quality_blockers.append({"code": "comparison-quality-regression"})
    blockers.extend(quality_blockers)
    base_resources = _aggregate_resources(baseline)
    candidate_resources = _aggregate_resources(candidate)
    resource_deltas = {
        key: candidate_resources[key] - base_resources[key]
        for key in base_resources
    }
    body = {
        "schemaVersion": ROUTE_COMPARISON_SCHEMA,
        "status": "PASS" if not blockers else ("INCOMPARABLE" if any(item["code"].startswith("comparison-") for item in blockers) else "NO_RECOMMENDATION"),
        "lineage": {
            "taskIds": sorted(item for item in base_tasks if isinstance(item, str)),
            "baselineEnvironmentDigests": sorted(base_environment),
            "candidateEnvironmentDigests": sorted(candidate_environment),
            "baselineScorerDigests": sorted(base_scorer),
            "candidateScorerDigests": sorted(candidate_scorer),
            "changedAxes": changed_axes,
        },
        "quality": {
            "qualityFirst": True,
            "baseline": base_quality,
            "candidate": candidate_quality,
            "blockers": quality_blockers,
        },
        "resources": {
            "baseline": base_resources,
            "candidate": candidate_resources,
            "deltas": resource_deltas if not blockers else None,
            "attestation": {
                "baseline": _attestation(baseline_receipts),
                "candidate": _attestation(candidate_receipts),
            },
            "availableOnlyAfterQuality": True,
        },
        "decision": {
            "qualityFirst": True,
            "changedAxes": changed_axes,
            "automaticRouteAdoptionEligible": False,
            "advisoryOnly": True,
        },
        "sourceQualificationDigests": {
            "baseline": baseline.get("qualificationDigest"),
            "candidate": candidate.get("qualificationDigest"),
        },
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "comparisonDigest": canonical_digest(body)}


def validate_qualified_route_comparison(comparison: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if comparison.get("schemaVersion") != ROUTE_COMPARISON_SCHEMA:
        blockers.append({"code": "benchmark-route-comparison-schema"})
    if comparison.get("status") not in {"PASS", "INCOMPARABLE", "NO_RECOMMENDATION", "BLOCKED"}:
        blockers.append({"code": "benchmark-route-comparison-status"})
    if comparison.get("modelCallsStarted") is not False or comparison.get("hostLaunchStarted") is not False:
        blockers.append({"code": "benchmark-route-comparison-side-effect"})
    if comparison.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "benchmark-route-comparison-production-claim"})
    if not isinstance(comparison.get("blockers"), list):
        blockers.append({"code": "benchmark-route-comparison-blockers"})
    expected = canonical_digest({key: value for key, value in comparison.items() if key != "comparisonDigest"})
    if comparison.get("comparisonDigest") != expected:
        blockers.append({"code": "benchmark-route-comparison-digest"})
    body = {
        "schemaVersion": ROUTE_COMPARISON_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "comparisonStatus": comparison.get("status") if isinstance(comparison.get("status"), str) else None,
        "blockers": blockers,
        "comparisonDigest": comparison.get("comparisonDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _axis_values(receipts: list[dict[str, Any]], container: str, field: str) -> set[str]:
    return {
        value
        for receipt in receipts
        if isinstance(receipt.get(container), dict)
        for value in [receipt[container].get(field)]
        if isinstance(value, str)
    }


def _first_axis(receipts: list[dict[str, Any]], container: str, field: str) -> str | None:
    values = sorted(_axis_values(receipts, container, field))
    return values[0] if values else None


def _aggregate_quality(report: dict[str, Any]) -> dict[str, int]:
    totals = {"criteriaTotal": 0, "criteriaPassed": 0, "falseAcceptanceCount": 0, "measurementGapCount": 0}
    for route in report.get("routes", []):
        quality = route.get("quality", {}) if isinstance(route, dict) else {}
        for key in totals:
            value = quality.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    return totals


def _aggregate_resources(report: dict[str, Any]) -> dict[str, int]:
    totals = {"tokens": 0, "elapsedMilliseconds": 0, "retries": 0, "remediations": 0}
    for route in report.get("routes", []):
        resources = route.get("resources") if isinstance(route, dict) else None
        if not isinstance(resources, dict):
            continue
        for key in totals:
            value = resources.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    return totals


def _attestation(receipts: list[dict[str, Any]]) -> str:
    values = {
        receipt.get("measurements", {}).get("usageConfidence")
        for receipt in receipts
        if isinstance(receipt.get("measurements"), dict)
    }
    values.discard(None)
    if len(values) == 1:
        return next(iter(values))
    if len(values) > 1:
        return "MIXED"
    return "MISSING"


def _evaluation_blockers(evaluation: dict[str, Any], label: str) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if evaluation.get("schemaVersion") != "agent-reference-task-evaluation.v1":
        blockers.append({"code": "comparison-evaluation-schema", "side": label})
    expected = canonical_digest({key: value for key, value in evaluation.items() if key != "evaluationDigest"})
    if evaluation.get("evaluationDigest") != expected:
        blockers.append({"code": "comparison-evaluation-digest", "side": label})
    return blockers


def _lineage_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    base_suite = baseline.get("suite") if isinstance(baseline.get("suite"), dict) else {}
    candidate_suite = candidate.get("suite") if isinstance(candidate.get("suite"), dict) else {}
    base_task = baseline.get("task") if isinstance(baseline.get("task"), dict) else {}
    candidate_task = candidate.get("task") if isinstance(candidate.get("task"), dict) else {}
    for field in ("id", "version", "digest"):
        if base_suite.get(field) != candidate_suite.get(field):
            blockers.append({"code": "comparison-suite-lineage-mismatch", "field": field})
    for field in ("id", "version", "taskDigest", "oracleDigest"):
        if base_task.get(field) != candidate_task.get(field):
            blockers.append({"code": "comparison-task-lineage-mismatch", "field": field})
    return {
        "status": "PASS" if not blockers else "FAIL",
        "suite": {field: base_suite.get(field) for field in ("id", "version", "digest")},
        "task": {field: base_task.get(field) for field in ("id", "version", "taskDigest", "oracleDigest")},
        "blockers": blockers,
    }


def _quality_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    base_summary = baseline.get("summary") if isinstance(baseline.get("summary"), dict) else {}
    candidate_summary = candidate.get("summary") if isinstance(candidate.get("summary"), dict) else {}
    base_measurements = _measurements(baseline)
    candidate_measurements = _measurements(candidate)
    base_false = _integer(base_summary.get("falseAcceptanceCount"))
    candidate_false = _integer(candidate_summary.get("falseAcceptanceCount"))
    if candidate_false > base_false:
        blockers.append({"code": "comparison-new-false-acceptance", "baseline": base_false, "candidate": candidate_false})
    base_passed = _integer(_nested(base_measurements, "quality", "criteriaPassed"))
    candidate_passed = _integer(_nested(candidate_measurements, "quality", "criteriaPassed"))
    base_total = _integer(_nested(base_measurements, "quality", "criteriaTotal"))
    candidate_total = _integer(_nested(candidate_measurements, "quality", "criteriaTotal"))
    if base_total != candidate_total:
        blockers.append({"code": "comparison-oracle-count-mismatch", "baseline": base_total, "candidate": candidate_total})
    if candidate_passed < base_passed:
        blockers.append({"code": "comparison-oracle-regression", "baseline": base_passed, "candidate": candidate_passed})
    lost = sorted(_passed_oracle_codes(baseline).difference(_passed_oracle_codes(candidate)))
    if lost:
        blockers.append({"code": "comparison-oracle-check-lost", "checks": lost})
    return {
        "status": "PASS" if not blockers else "FAIL",
        "baselineFalseAcceptances": base_false,
        "candidateFalseAcceptances": candidate_false,
        "baselineCriteriaPassed": base_passed,
        "candidateCriteriaPassed": candidate_passed,
        "lostOracleChecks": lost,
        "blockers": blockers,
    }


def _resource_comparison(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    base = _measurements(baseline)
    current = _measurements(candidate)
    base_tokens = _token_headline(base)
    candidate_tokens = _token_headline(current)
    attested = (
        base_tokens.get("confidence") == "ATTESTED"
        and candidate_tokens.get("confidence") == "ATTESTED"
        and _is_integer(base_tokens.get("total"))
        and _is_integer(candidate_tokens.get("total"))
    )
    comparable_estimate = (
        base_tokens.get("confidence") == candidate_tokens.get("confidence") == "ESTIMATED"
        and _is_integer(base_tokens.get("total"))
        and _is_integer(candidate_tokens.get("total"))
    )
    exact_token_delta = candidate_tokens["total"] - base_tokens["total"] if attested else None
    estimated_token_delta = candidate_tokens["total"] - base_tokens["total"] if comparable_estimate else None
    observed = {
        "invocations": _delta(base, current, "invocations", "count"),
        "retries": _delta(base, current, "retries", "count"),
        "remediations": _delta(base, current, "remediations", "count"),
        "elapsedMilliseconds": _delta(base, current, "elapsed", "milliseconds"),
    }
    regressions = sorted(field for field, delta in observed.items() if _is_integer(delta) and delta > 0)
    measurement_gaps = {
        "baseline": list(base.get("measurementGaps", [])),
        "candidate": list(current.get("measurementGaps", [])),
    }
    measurement_complete = not any(measurement_gaps.values()) and all(
        isinstance(value, int) and not isinstance(value, bool) for value in observed.values()
    )
    return {
        "comparableAttestedUsage": attested,
        "tokenConfidence": {
            "baseline": base_tokens.get("confidence", "MISSING"),
            "candidate": candidate_tokens.get("confidence", "MISSING"),
        },
        "exactDeltas": {
            "tokens": exact_token_delta,
            **observed,
        }
        if attested
        else None,
        "observedDeltas": observed,
        "advisoryEstimatedTokenDelta": estimated_token_delta,
        "measurementGaps": measurement_gaps,
        "measurementComplete": measurement_complete,
        "observedRegressionFields": regressions,
        "resourceRegressionFree": not regressions,
        "exactSavingsClaimed": attested and exact_token_delta is not None and exact_token_delta < 0,
        "advisoryOnly": not attested,
    }


def _measurements(evaluation: dict[str, Any]) -> dict[str, Any]:
    value = evaluation.get("measurements")
    return value if isinstance(value, dict) else {}


def _token_headline(measurements: dict[str, Any]) -> dict[str, Any]:
    tokens = measurements.get("tokens") if isinstance(measurements.get("tokens"), dict) else {}
    headline = tokens.get("headline")
    return headline if isinstance(headline, dict) else {"confidence": "MISSING", "total": None}


def _passed_oracle_codes(evaluation: dict[str, Any]) -> set[str]:
    oracle = evaluation.get("oracle") if isinstance(evaluation.get("oracle"), dict) else {}
    checks = oracle.get("checks") if isinstance(oracle.get("checks"), list) else []
    return {
        str(item["code"])
        for item in checks
        if isinstance(item, dict) and item.get("passed") is True and isinstance(item.get("code"), str)
    }


def _delta(baseline: dict[str, Any], candidate: dict[str, Any], group: str, field: str) -> int | None:
    before = _nested(baseline, group, field)
    after = _nested(candidate, group, field)
    return after - before if _is_integer(before) and _is_integer(after) else None


def _nested(value: dict[str, Any], group: str, field: str) -> Any:
    row = value.get(group)
    return row.get(field) if isinstance(row, dict) else None


def _integer(value: Any) -> int:
    return value if _is_integer(value) else 0


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
