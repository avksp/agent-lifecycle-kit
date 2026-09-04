"""Metrics-specific dispatch helpers for the observability facade."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.metrics import require_lifecycle_recommendation_pass
from agent_lifecycle.metrics.recommendations import recommend_from_workflow_comparison
from agent_lifecycle.metrics.regression_signals import (
    compare_workflow_economics,
    validate_workflow_economics_comparison_view,
    workflow_comparison_context_from_fixture,
)
from agent_lifecycle.reporting.execution_resources import (
    build_execution_resource_report,
    validate_execution_resource_report,
)


def _dispatch_execution_report(args: argparse.Namespace) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    for item in args.receipt:
        payload = read_json_object(Path(item), label="process execution receipt")
        raw_receipt = payload.get("processReceipt")
        candidate = raw_receipt if isinstance(raw_receipt, dict) else payload
        receipts.append(candidate)
    lineage = {"operationId": args.operation_id} if args.operation_id else None
    report = build_execution_resource_report(receipts, lineage=lineage)
    validation = validate_execution_resource_report(report)
    write_json_create(Path(args.out), report)
    return {
        "schemaVersion": "agent-execution-resource-report-generation.v1",
        "status": validation["status"],
        "reportPath": args.out,
        "reportDigest": canonical_digest(report),
        "validation": validation,
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }


def _dispatch_workflow_compare(args: argparse.Namespace) -> dict[str, Any]:
    before = workflow_comparison_context_from_fixture(
        read_json_object(Path(args.before), label="workflow comparison before fixture")
    )
    after = workflow_comparison_context_from_fixture(
        read_json_object(Path(args.after), label="workflow comparison after fixture")
    )
    comparison_pair = (
        read_json_object(Path(args.comparison_pair), label="workflow comparison pair") if args.comparison_pair else None
    )
    comparison = compare_workflow_economics(before, after, comparison_pair=comparison_pair)
    validation = validate_workflow_economics_comparison_view(comparison)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "workflow-comparison-invalid",
            "workflow economics comparison failed validation",
            {"validation": validation},
        )
    write_json_create(Path(args.out), comparison)
    return comparison


def _dispatch_workflow_recommend(args: argparse.Namespace) -> dict[str, Any]:
    comparison = read_json_object(Path(args.comparison), label="workflow economics comparison")
    validation = validate_workflow_economics_comparison_view(comparison)
    if validation["status"] != "PASS":
        raise LifecycleError(
            "workflow-comparison-invalid",
            "workflow economics comparison failed validation",
            {"validation": validation},
        )
    recommendation = recommend_from_workflow_comparison(
        comparison=comparison,
        task_shape=args.task_shape,
        current_mode=args.current_mode,
        required_mode=args.required_mode,
        protected_work=args.protected_work,
    )
    require_lifecycle_recommendation_pass(recommendation)
    write_json_create(Path(args.out), recommendation)
    return recommendation
