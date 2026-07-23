"""Workflow enforcement for model-route usage receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError
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
) -> dict[str, Any]:
    route = _attempt_route(task)
    if route is None or not model_usage_receipt_required(task):
        raise LifecycleError("unexpected-model-usage-receipt", "task attempt does not require a model usage receipt")
    _require_lineage(state, task, receipt)
    result = validate_usage_receipt(receipt, budget_targets=budget_targets, route_decision=route)
    if result["status"] == "FAIL":
        raise LifecycleError(
            "model-usage-validation-failed",
            "model usage receipt validation failed",
            {"validation": result},
        )
    return result


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
