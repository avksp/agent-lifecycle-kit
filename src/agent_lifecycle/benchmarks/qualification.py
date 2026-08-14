"""Quality-first qualification over externally supplied benchmark receipts."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from agent_lifecycle.benchmarks.contracts import LoadedSuite, validate_benchmark_run_receipt
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.benchmark_schemas import (
    QUALIFICATION_SCHEMA,
    QUALIFICATION_VALIDATION_SCHEMA,
)


DEFAULT_MINIMUMS: dict[str, Any] = {
    "minDistinctTasksPerRoute": 5,
    "minCompletedRunsPerTaskPerRoute": 2,
    "minDistinctStrataPerRoute": 5,
    "minCompletedRunsPerStratumPerRoute": 2,
    "insufficientEvidenceDecision": "NO_RECOMMENDATION",
}


def qualify_benchmark_runs(
    receipts: Iterable[dict[str, Any]],
    *,
    sample: dict[str, Any] | None = None,
    suite: LoadedSuite | None = None,
    minimums: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded qualification report without comparing resources first."""

    limits = {**DEFAULT_MINIMUMS, **(minimums or {})}
    rows = [dict(item) for item in receipts]
    blockers: list[dict[str, Any]] = []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_ids = _selected_task_ids(sample)
    for index, receipt in enumerate(rows):
        validation = validate_benchmark_run_receipt(receipt, suite=suite)
        if validation["status"] != "PASS":
            blockers.append({"code": "benchmark-run-receipt-invalid", "index": index, "details": validation["blockers"]})
            continue
        if selected_ids and receipt["taskId"] not in selected_ids:
            blockers.append({"code": "benchmark-run-outside-sample", "taskId": receipt["taskId"]})
            continue
        route = receipt.get("route", {})
        route_digest = route.get("routeDigest") if isinstance(route, dict) else None
        if not isinstance(route_digest, str):
            blockers.append({"code": "benchmark-route-digest-missing", "index": index})
            continue
        groups[route_digest].append(receipt)

    route_reports = [_route_report(route_digest, route_rows, limits) for route_digest, route_rows in sorted(groups.items())]
    insufficient = [
        {
            "code": "benchmark-qualification-insufficient-evidence",
            "routeDigest": report["routeDigest"],
            "gaps": report["gaps"],
        }
        for report in route_reports
        if report["status"] != "QUALIFIED"
    ]
    blockers.extend(insufficient)
    if not route_reports:
        status = "BLOCKED" if blockers else "NO_RECOMMENDATION"
    elif any(item.get("code") == "benchmark-run-receipt-invalid" for item in blockers):
        status = "BLOCKED"
    elif insufficient:
        status = "NO_RECOMMENDATION"
    else:
        status = "QUALIFIED"
    body = {
        "schemaVersion": QUALIFICATION_SCHEMA,
        "status": status,
        "decision": {
            "qualityFirst": True,
            "qualityEvidenceComplete": status == "QUALIFIED",
            "resourceComparisonAllowed": status == "QUALIFIED",
            "automaticRouteAdoptionEligible": False,
            "advisoryOnly": True,
        },
        "sample": _sample_summary(sample),
        "minimums": limits,
        "routes": route_reports,
        "qualityFirst": True,
        "blockers": blockers,
        "modelCallsStarted": False,
        "hostLaunchStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "qualificationDigest": canonical_digest(body)}


def validate_qualification_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if report.get("schemaVersion") != QUALIFICATION_SCHEMA:
        blockers.append({"code": "benchmark-qualification-schema"})
    if report.get("status") not in {"QUALIFIED", "NO_RECOMMENDATION", "BLOCKED", "INCOMPARABLE"}:
        blockers.append({"code": "benchmark-qualification-status"})
    if report.get("qualityFirst") is not True:
        blockers.append({"code": "benchmark-qualification-quality-order"})
    if report.get("modelCallsStarted") is not False or report.get("hostLaunchStarted") is not False:
        blockers.append({"code": "benchmark-qualification-side-effect"})
    if report.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "benchmark-qualification-production-claim"})
    if not isinstance(report.get("routes"), list):
        blockers.append({"code": "benchmark-qualification-routes"})
    if not isinstance(report.get("blockers"), list):
        blockers.append({"code": "benchmark-qualification-blockers"})
    decision = report.get("decision") if isinstance(report.get("decision"), dict) else {}
    if decision.get("automaticRouteAdoptionEligible") is True:
        blockers.append({"code": "benchmark-qualification-auto-adoption"})
    expected = canonical_digest({key: value for key, value in report.items() if key != "qualificationDigest"})
    if report.get("qualificationDigest") != expected:
        blockers.append({"code": "benchmark-qualification-digest"})
    body = {
        "schemaVersion": QUALIFICATION_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "qualificationStatus": report.get("status") if isinstance(report.get("status"), str) else None,
        "blockers": blockers,
        "qualificationDigest": report.get("qualificationDigest"),
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _route_report(route_digest: str, receipts: list[dict[str, Any]], minimums: dict[str, Any]) -> dict[str, Any]:
    task_counts: dict[str, int] = defaultdict(int)
    stratum_counts: dict[str, int] = defaultdict(int)
    false_acceptances = 0
    criteria_total = 0
    criteria_passed = 0
    quality_gaps: list[str] = []
    environment_digests: set[str] = set()
    scorer_digests: set[str] = set()
    usage_confidences: set[str] = set()
    resource_totals = {"tokens": 0, "elapsedMilliseconds": 0, "retries": 0, "remediations": 0}
    route_identity: dict[str, Any] = {}
    for receipt in receipts:
        task_counts[receipt["taskId"]] += 1
        stratum_counts[_stratum_key(receipt)] += 1
        quality = receipt["quality"]
        criteria_total += quality["criteriaTotal"]
        criteria_passed += quality["criteriaPassed"]
        if quality["falseAcceptance"]:
            false_acceptances += 1
        quality_gaps.extend(quality["measurementGap"])
        environment_digests.add(receipt["environment"]["environmentDigest"])
        scorer_digests.add(receipt["scorer"]["scorerDigest"])
        route_identity = dict(receipt["route"])
        measurements = receipt.get("measurements", {})
        confidence = measurements.get("usageConfidence")
        if isinstance(confidence, str):
            usage_confidences.add(confidence)
        for output_key, input_key in (
            ("tokens", "tokens"),
            ("elapsedMilliseconds", "elapsedMilliseconds"),
            ("retries", "retries"),
            ("remediations", "remediations"),
        ):
            value = measurements.get(input_key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                resource_totals[output_key] += value
    gaps: list[dict[str, Any]] = []
    distinct_tasks = len(task_counts)
    distinct_strata = len(stratum_counts)
    required_task_count = _minimum(minimums, "minDistinctTasksPerRoute")
    required_runs_per_task = _minimum(minimums, "minCompletedRunsPerTaskPerRoute")
    required_strata = _minimum(minimums, "minDistinctStrataPerRoute")
    required_runs_per_stratum = _minimum(minimums, "minCompletedRunsPerStratumPerRoute")
    if distinct_tasks < required_task_count:
        gaps.append({"code": "distinct-task-count", "actual": distinct_tasks, "required": required_task_count})
    if any(count < required_runs_per_task for count in task_counts.values()) or len(task_counts) < required_task_count:
        gaps.append({"code": "runs-per-task", "actual": dict(task_counts), "required": required_runs_per_task})
    if distinct_strata < required_strata:
        gaps.append({"code": "distinct-stratum-count", "actual": distinct_strata, "required": required_strata})
    if any(count < required_runs_per_stratum for count in stratum_counts.values()) or len(stratum_counts) < required_strata:
        gaps.append({"code": "runs-per-stratum", "actual": dict(stratum_counts), "required": required_runs_per_stratum})
    if quality_gaps:
        gaps.append({"code": "quality-measurement-gap", "fields": sorted(set(quality_gaps))})
    if false_acceptances:
        gaps.append({"code": "false-acceptance", "count": false_acceptances})
    if not all(receipt.get("completed") is True for receipt in receipts):
        gaps.append({"code": "incomplete-run"})
    if len(usage_confidences) > 1:
        gaps.append({"code": "mixed-usage-attestation", "values": sorted(usage_confidences)})
    if len(environment_digests) > 1:
        gaps.append({"code": "mixed-environment-attestation", "values": sorted(environment_digests)})
    if len(scorer_digests) > 1:
        gaps.append({"code": "mixed-scorer-attestation", "values": sorted(scorer_digests)})
    return {
        "status": "QUALIFIED" if not gaps else "NO_RECOMMENDATION",
        "routeDigest": route_digest,
        "route": route_identity,
        "runCount": len(receipts),
        "distinctTaskCount": distinct_tasks,
        "distinctStratumCount": distinct_strata,
        "taskRunCounts": dict(sorted(task_counts.items())),
        "stratumRunCounts": dict(sorted(stratum_counts.items())),
        "environmentDigests": sorted(environment_digests),
        "scorerDigests": sorted(scorer_digests),
        "quality": {
            "criteriaTotal": criteria_total,
            "criteriaPassed": criteria_passed,
            "falseAcceptanceCount": false_acceptances,
            "measurementGapCount": len(quality_gaps),
        },
        "resources": resource_totals if not gaps else None,
        "gaps": gaps,
    }


def _selected_task_ids(sample: dict[str, Any] | None) -> set[str]:
    if not isinstance(sample, dict):
        return set()
    values = sample.get("selectedTaskIds")
    return {item for item in values if isinstance(item, str)} if isinstance(values, list) else set()


def _sample_summary(sample: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(sample, dict):
        return None
    return {
        "suite": sample.get("suite"),
        "sampleDigest": sample.get("sampleDigest"),
        "selectedTaskIds": list(sample.get("selectedTaskIds", [])),
        "omittedTaskIds": list(sample.get("omittedTaskIds", [])),
        "strata": list(sample.get("strata", [])),
    }


def _stratum_key(receipt: dict[str, Any]) -> str:
    return f"{receipt['family']}|{receipt['tier']}|{receipt['shape']}"


def _minimum(values: dict[str, Any], key: str) -> int:
    value = values.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else int(DEFAULT_MINIMUMS[key])
