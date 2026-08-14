"""Workflow enforcement for model-route usage receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.process_execution_schemas import validate_process_execution_receipt
from agent_lifecycle.model_routing import validate_usage_receipt

UNSAFE_CRITICAL_REVIEW_CLASSES = {"budget", "local-compact"}


def validate_attempt_model_route(task: dict[str, Any]) -> None:
    """Validate that a task route is executable before an attempt starts."""

    route = task.get("modelRoute")
    if not isinstance(route, dict) or not route:
        return
    model_class = _required_route_string(route, "modelClass")
    if model_class == "no-model":
        return
    _required_route_string(route, "operationId")
    _required_route_string(route, "decisionDigest")
    if route.get("requiresUsageReceipt") is False:
        raise LifecycleError(
            "model-usage-receipt-required",
            "model-backed routes must require usage receipts",
        )
    if route.get("criticalReview") is True and model_class in UNSAFE_CRITICAL_REVIEW_CLASSES:
        raise LifecycleError(
            "model-route-critical-downgrade",
            "critical review route cannot use a budget or compact model class",
            {"modelClass": model_class},
        )


def model_usage_receipt_required(task: dict[str, Any]) -> bool:
    route = _attempt_route(task)
    if route is None:
        return False
    model_class = route.get("modelClass")
    if model_class == "no-model":
        return False
    return route.get("requiresUsageReceipt", True) is True


def validate_task_model_usage_receipt(
    state: dict[str, Any],
    task: dict[str, Any],
    receipt: dict[str, Any],
    *,
    budget_targets: dict[str, Any] | None = None,
    fail_on_invalid: bool = True,
) -> dict[str, Any]:
    route = _attempt_route(task)
    if route is None or not model_usage_receipt_required(task):
        raise LifecycleError("unexpected-model-usage-receipt", "task attempt does not require a model usage receipt")
    _require_lineage(state, task, receipt)
    result = validate_usage_receipt(receipt, budget_targets=budget_targets, route_decision=route)
    if result["status"] == "FAIL" and fail_on_invalid:
        raise LifecycleError(
            "model-usage-validation-failed",
            "model usage receipt validation failed",
            {"validation": result},
        )
    return result


def validate_task_process_execution_receipt(
    task: dict[str, Any],
    receipt: dict[str, Any],
    *,
    operation_id: str | None = None,
    attempt_id: str | None = None,
    fail_on_invalid: bool = True,
) -> dict[str, Any]:
    """Validate local process evidence before a host result is accepted."""

    validation = validate_process_execution_receipt(receipt)
    if receipt.get("status") != "PASS" or receipt.get("cleanup", {}).get("status") != "PASS":
        validation["status"] = "FAIL"
        validation.setdefault("blockers", []).append({"code": "process-execution-not-qualified"})
    if operation_id is not None and receipt.get("operationId") != operation_id:
        validation["status"] = "FAIL"
        validation.setdefault("blockers", []).append({"code": "process-execution-operation-mismatch"})
    expected_attempt = attempt_id if attempt_id is not None else str(task.get("attempt", ""))
    if expected_attempt and receipt.get("attemptId") not in {expected_attempt, f"attempt-{expected_attempt}"}:
        validation["status"] = "FAIL"
        validation.setdefault("blockers", []).append({"code": "process-execution-attempt-mismatch"})
    if fail_on_invalid and validation.get("status") != "PASS":
        raise LifecycleError(
            "process-execution-validation-failed",
            "process execution receipt validation failed",
            {"validation": validation},
        )
    return validation


def process_execution_receipt_projection(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the safe subset suitable for a task or host-operation result."""

    return {
        "receiptDigest": receipt.get("receiptDigest"),
        "status": receipt.get("status"),
        "operationId": receipt.get("operationId"),
        "attemptId": receipt.get("attemptId"),
        "timing": receipt.get("timing", {}),
        "resources": receipt.get("resources", {}),
        "cleanup": receipt.get("cleanup", {}),
        "timedOut": bool(receipt.get("timedOut")),
        "cancelled": bool(receipt.get("cancelled")),
    }


def bounded_process_retry_decision(
    receipt: dict[str, Any],
    *,
    attempt: int,
    max_retries: int = 1,
) -> dict[str, Any]:
    """Return one deterministic retry decision; never starts a retry loop."""

    if max_retries < 0:
        raise LifecycleError("invalid-process-retry-cap", "max_retries must not be negative")
    cleanup_status = receipt.get("cleanup", {}).get("status") if isinstance(receipt.get("cleanup"), dict) else None
    if cleanup_status != "PASS":
        return {"decision": "BLOCKED", "retry": False, "reason": "cleanup-unverified", "attempt": attempt, "maxRetries": max_retries}
    if receipt.get("status") == "PASS":
        return {"decision": "ACCEPT", "retry": False, "reason": "process-passed", "attempt": attempt, "maxRetries": max_retries}
    retry = attempt <= max_retries
    reason = "timeout" if receipt.get("timedOut") else "cancelled" if receipt.get("cancelled") else "process-failed"
    return {"decision": "RETRY" if retry else "BLOCKED", "retry": retry, "reason": reason, "attempt": attempt, "maxRetries": max_retries}


def _attempt_route(task: dict[str, Any]) -> dict[str, Any] | None:
    route = task.get("attemptModelRoute")
    if isinstance(route, dict) and route:
        return route
    route = task.get("modelRoute")
    if isinstance(route, dict) and route:
        return route
    return None


def _require_lineage(state: dict[str, Any], task: dict[str, Any], receipt: dict[str, Any]) -> None:
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LifecycleError(
                "model-usage-lineage-mismatch",
                f"model usage receipt {key} mismatch",
            )
    route = _attempt_route(task) or {}
    if receipt.get("routeDecisionDigest") != route.get("decisionDigest"):
        raise LifecycleError(
            "model-usage-lineage-mismatch",
            "model usage receipt routeDecisionDigest mismatch",
        )


def _required_route_string(route: dict[str, Any], key: str) -> str:
    value = route.get(key)
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-model-route", f"modelRoute.{key} is required")
    return value
