"""Metrics-specific dispatch helpers for the observability facade."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import canonical_digest, read_json_object, write_json_create
from agent_lifecycle.reporting.execution_resources import (
    build_execution_resource_report,
    validate_execution_resource_report,
)


def _dispatch_execution_report(args: argparse.Namespace) -> dict[str, Any]:
    receipts: list[dict[str, Any]] = []
    for item in args.receipt:
        payload = read_json_object(Path(item), label="process execution receipt")
        candidate = payload.get("processReceipt") if isinstance(payload.get("processReceipt"), dict) else payload
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
