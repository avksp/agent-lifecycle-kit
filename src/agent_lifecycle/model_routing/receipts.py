"""Usage receipt validation for model-backed route decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.model_routing.profiles import ALLOWED_MODEL_CLASSES, SDD_TIERS

USAGE_METRICS = {
    "inputTokens",
    "outputTokens",
    "billableTokens",
    "cumulativeContextBytes",
    "toolCalls",
    "wallSeconds",
}


def validate_usage_receipt(
    receipt: dict[str, Any],
    *,
    budget_targets: dict[str, Any] | None = None,
    route_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_shape(receipt)
    checks = [_attestation_check(receipt)]
    if route_decision is not None:
        checks.extend(_route_binding_checks(receipt, route_decision))
    checks.extend(_budget_checks(receipt, budget_targets=budget_targets, route_decision=route_decision))
    status = "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL"
    payload = {
        "schemaVersion": "agent-lifecycle-model-usage-validation.v1",
        "status": status,
        "operationId": receipt["operationId"],
        "host": receipt["host"],
        "modelClass": receipt["modelClass"],
        "receiptDigest": canonical_digest(receipt),
        "checks": checks,
    }
    if route_decision is not None:
        payload["routeDecisionDigest"] = canonical_digest(route_decision)
    return payload


def _validate_shape(receipt: dict[str, Any]) -> None:
    if receipt.get("schemaVersion") != "agent-lifecycle-model-usage-receipt.v1":
        raise LifecycleError("invalid-model-usage-receipt", "unsupported model usage receipt schema")
    for key in ("operationId", "host", "modelClass", "providerModelHash"):
        if not isinstance(receipt.get(key), str) or not receipt.get(key):
            raise LifecycleError("invalid-model-usage-receipt", f"{key} is required")
    if receipt["modelClass"] not in ALLOWED_MODEL_CLASSES - {"no-model"}:
        raise LifecycleError("invalid-model-usage-receipt", "modelClass is unsupported")
    usage = receipt.get("usage")
    if not isinstance(usage, dict):
        raise LifecycleError("invalid-model-usage-receipt", "usage object is required")
    missing = sorted(metric for metric in USAGE_METRICS if not isinstance(usage.get(metric), int) or isinstance(usage.get(metric), bool))
    if missing:
        raise LifecycleError("invalid-model-usage-receipt", "usage metrics must be integers", {"missing": missing})
    negative = sorted(metric for metric in USAGE_METRICS if usage[metric] < 0)
    if negative:
        raise LifecycleError("invalid-model-usage-receipt", "usage metrics must be non-negative", {"metrics": negative})
    attestation = receipt.get("attestation")
    if not isinstance(attestation, dict):
        raise LifecycleError("invalid-model-usage-receipt", "attestation object is required")


def _attestation_check(receipt: dict[str, Any]) -> dict[str, Any]:
    attestation = receipt["attestation"]
    status = "PASS" if attestation.get("source") == "host" and attestation.get("status") == "ATTESTED" else "FAIL"
    return {
        "id": "host-usage-attestation",
        "status": status,
        "source": attestation.get("source"),
        "attestationStatus": attestation.get("status"),
    }


def _route_binding_checks(receipt: dict[str, Any], decision: dict[str, Any]) -> list[dict[str, Any]]:
    expected_digest = decision.get("decisionDigest", canonical_digest(decision))
    receipt_digest = receipt.get("routeDecisionDigest")
    return [
        {
            "id": "operation-id-binding",
            "status": "PASS" if receipt.get("operationId") == decision.get("operationId") else "FAIL",
            "expected": decision.get("operationId"),
            "actual": receipt.get("operationId"),
        },
        {
            "id": "model-class-binding",
            "status": "PASS" if receipt.get("modelClass") == decision.get("modelClass") else "FAIL",
            "expected": decision.get("modelClass"),
            "actual": receipt.get("modelClass"),
        },
        {
            "id": "route-decision-digest-binding",
            "status": "PASS" if receipt_digest in (None, expected_digest) else "FAIL",
            "expected": expected_digest,
            "actual": receipt_digest,
        },
    ]


def _budget_checks(
    receipt: dict[str, Any],
    *,
    budget_targets: dict[str, Any] | None,
    route_decision: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    usage = receipt["usage"]
    if route_decision is not None and isinstance(route_decision.get("maxBillableTokens"), int):
        limit = route_decision["maxBillableTokens"]
        checks.append({
            "id": "route-max-billable-tokens",
            "status": "PASS" if usage["billableTokens"] <= limit else "FAIL",
            "value": usage["billableTokens"],
            "limit": limit,
        })
    if budget_targets is None:
        return checks
    tier = receipt.get("sddTier") or (route_decision or {}).get("sddTier")
    if tier not in SDD_TIERS:
        checks.append({"id": "budget-tier-binding", "status": "FAIL", "tier": tier})
        return checks
    hard = budget_targets.get("hardCeilings", {}).get(tier)
    if not isinstance(hard, dict):
        checks.append({"id": "budget-target-present", "status": "FAIL", "tier": tier})
        return checks
    for metric in ("billableTokens", "cumulativeContextBytes", "toolCalls", "wallSeconds"):
        limit = hard.get(metric)
        if isinstance(limit, int):
            checks.append({
                "id": f"hard-ceiling-{metric}",
                "status": "PASS" if usage[metric] <= limit else "FAIL",
                "value": usage[metric],
                "limit": limit,
                "tier": tier,
            })
    return checks
