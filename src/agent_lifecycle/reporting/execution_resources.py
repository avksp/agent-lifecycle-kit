"""Local reports for process-execution receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.process_execution_schemas import (
    PROCESS_EXECUTION_RECEIPT_SCHEMA,
    validate_process_execution_receipt,
)
from agent_lifecycle.metrics.workflow_economics import (
    build_workflow_metric_set,
    build_workflow_resource_summary,
    validate_workflow_resource_summary,
)

EXECUTION_RESOURCE_REPORT_SCHEMA = "agent-execution-resource-report.v1"
EXECUTION_RESOURCE_VALIDATION_SCHEMA = "agent-execution-resource-report-validation.v1"


def build_execution_resource_report(
    receipts: list[dict[str, Any]],
    *,
    lineage: dict[str, Any] | None = None,
    enclosing_elapsed_wall: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate bounded receipt projections without retaining host output."""

    if not isinstance(receipts, list) or not receipts:
        raise LifecycleError("execution-resource-receipts-required", "at least one process receipt is required")
    blockers: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    for index, receipt in enumerate(receipts):
        validation = validate_process_execution_receipt(receipt)
        if validation["status"] != "PASS":
            blockers.append({"code": "execution-resource-receipt-invalid", "index": index, "validation": validation})
        if receipt.get("cleanup", {}).get("status") != "PASS":
            blockers.append({"code": "execution-resource-cleanup-blocked", "index": index})
        projections.append(_projection(receipt, index))
    body = {
        "schemaVersion": EXECUTION_RESOURCE_REPORT_SCHEMA,
        "status": "PASS" if not blockers else "BLOCKED",
        "lineage": _safe_lineage(lineage or {}),
        "receiptCount": len(projections),
        "receipts": projections,
        "summary": _summary(projections),
        "workflowEconomics": build_workflow_resource_summary(
            [_workflow_metric_set(item) for item in projections],
            enclosing_elapsed_wall=enclosing_elapsed_wall,
        ),
        "blockers": blockers[:32],
        "rawOutputStored": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "reportDigest": canonical_digest(body)}


def validate_execution_resource_report(report: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if report.get("schemaVersion") != EXECUTION_RESOURCE_REPORT_SCHEMA:
        blockers.append({"code": "execution-resource-report-schema"})
    if report.get("rawOutputStored") is not False or report.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "execution-resource-report-sensitive-state"})
    receipts = report.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        blockers.append({"code": "execution-resource-report-receipts"})
        receipts = []
    if report.get("receiptCount") != len(receipts):
        blockers.append({"code": "execution-resource-report-count"})
    if isinstance(receipts, list):
        for index, item in enumerate(receipts):
            if not isinstance(item, dict):
                blockers.append({"code": "execution-resource-report-projection", "index": index})
                continue
            if item.get("schemaVersion") != PROCESS_EXECUTION_RECEIPT_SCHEMA:
                blockers.append({"code": "execution-resource-report-receipt-schema", "index": index})
    workflow_validation = validate_workflow_resource_summary(report.get("workflowEconomics"))
    if workflow_validation["status"] != "PASS":
        blockers.append({"code": "execution-resource-workflow-economics", "validation": workflow_validation})
    expected = canonical_digest({key: value for key, value in report.items() if key != "reportDigest"})
    if report.get("reportDigest") != expected:
        blockers.append({"code": "execution-resource-report-digest"})
    body = {
        "schemaVersion": EXECUTION_RESOURCE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "reportStatus": report.get("status"),
        "receiptCount": len(receipts),
        "blockers": blockers,
        "reportDigest": report.get("reportDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_execution_resource_report_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "execution-resource-report-invalid",
            "execution resource report validation failed",
            {"validation": validation},
        )
    return validation


def _projection(receipt: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "entryId": f"execution-{index + 1}",
        "schemaVersion": receipt.get("schemaVersion"),
        "status": receipt.get("status"),
        "operationId": receipt.get("operationId"),
        "attemptId": receipt.get("attemptId"),
        "adapterId": receipt.get("adapterId"),
        "receiptDigest": receipt.get("receiptDigest"),
        "timing": receipt.get("timing", {}),
        "resources": receipt.get("resources", {}),
        "cleanup": receipt.get("cleanup", {}),
        "timedOut": bool(receipt.get("timedOut")),
        "cancelled": bool(receipt.get("cancelled")),
        "retry": receipt.get("retry", {}),
        "blockerCount": len(receipt.get("blockers", [])) if isinstance(receipt.get("blockers"), list) else 0,
    }


def _summary(projections: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = 0
    cpu_values: list[float] = []
    memory_values: list[float] = []
    process_values: list[float] = []
    cleanup_blocked = 0
    timed_out = 0
    cancelled = 0
    for item in projections:
        timing = item.get("timing", {})
        if isinstance(timing.get("elapsedMs"), (int, float)):
            elapsed += timing["elapsedMs"]
        resources = item.get("resources", {})
        for key, target in (("cpuMs", cpu_values), ("peakMemoryMb", memory_values), ("processCount", process_values)):
            metric = resources.get(key, {}) if isinstance(resources, dict) else {}
            if (
                isinstance(metric, dict)
                and metric.get("availability") == "ATTESTED"
                and isinstance(metric.get("value"), (int, float))
            ):
                target.append(float(metric["value"]))
        if item.get("cleanup", {}).get("status") != "PASS":
            cleanup_blocked += 1
        timed_out += int(bool(item.get("timedOut")))
        cancelled += int(bool(item.get("cancelled")))
    return {
        "elapsedMs": elapsed,
        "cpuMs": _aggregate(cpu_values),
        "peakMemoryMb": _aggregate(memory_values, maximum=True),
        "peakProcessCount": _aggregate(process_values, maximum=True),
        "cleanupBlocked": cleanup_blocked,
        "timedOut": timed_out,
        "cancelled": cancelled,
    }


def _aggregate(values: list[float], *, maximum: bool = False) -> dict[str, Any]:
    if not values:
        return {"value": None, "availability": "UNAVAILABLE"}
    return {"value": max(values) if maximum else round(sum(values), 3), "availability": "ATTESTED"}


def _workflow_metric_set(projection: dict[str, Any]) -> dict[str, Any]:
    timing = projection.get("timing")
    elapsed = timing.get("elapsedMs") if isinstance(timing, dict) else None
    elapsed_metric = (
        {"status": "MEASURED", "value": elapsed}
        if isinstance(elapsed, int) and not isinstance(elapsed, bool) and elapsed >= 0
        else {"status": "UNAVAILABLE", "value": None}
    )
    return build_workflow_metric_set(
        {
            "toolCalls": {"status": "MEASURED", "value": 1},
            "toolWallMs": elapsed_metric,
            "elapsedWallMs": elapsed_metric,
        }
    )


def _safe_lineage(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"runId", "packageId", "taskId", "operationId", "sourceRevision"}
    return {
        key: value[key] for key in sorted(value) if key in allowed and isinstance(value[key], (str, int, float, bool))
    }
