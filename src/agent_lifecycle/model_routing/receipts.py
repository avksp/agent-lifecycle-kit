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
    if isinstance(receipt.get("normalizer"), dict):
        checks.append(_normalizer_qualification_check(receipt))
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
    if _has_sidecar_binding(receipt):
        _validate_sidecar_binding(receipt)


def _attestation_check(receipt: dict[str, Any]) -> dict[str, Any]:
    attestation = receipt["attestation"]
    status = "PASS" if attestation.get("source") == "host" and attestation.get("status") == "ATTESTED" else "FAIL"
    return {
        "id": "host-usage-attestation",
        "status": status,
        "source": attestation.get("source"),
        "attestationStatus": attestation.get("status"),
    }


def _normalizer_qualification_check(receipt: dict[str, Any]) -> dict[str, Any]:
    normalizer = receipt["normalizer"]
    attestation = receipt["attestation"]
    accepted = (
        normalizer.get("contract") == "adapter-local-usage-normalizer.v1"
        and normalizer.get("status") == "QUALIFIED"
        and normalizer.get("acceptedForS1S2") is True
        and attestation.get("acceptedForS1S2") is True
        and attestation.get("source") == "host"
        and attestation.get("status") == "ATTESTED"
    )
    return {
        "id": "host-usage-normalizer-qualified",
        "status": "PASS" if accepted else "FAIL",
        "normalizerStatus": normalizer.get("status"),
        "acceptedForS1S2": normalizer.get("acceptedForS1S2"),
    }


def _route_binding_checks(receipt: dict[str, Any], decision: dict[str, Any]) -> list[dict[str, Any]]:
    expected_digest = decision.get("decisionDigest", canonical_digest(decision))
    receipt_digest = receipt.get("routeDecisionDigest")
    route_bound = receipt_digest == expected_digest if _has_sidecar_binding(receipt) else receipt_digest in (None, expected_digest)
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
            "status": "PASS" if route_bound else "FAIL",
            "expected": expected_digest,
            "actual": receipt_digest,
        },
    ]


def _has_sidecar_binding(receipt: dict[str, Any]) -> bool:
    fields = ("adapterId", "sourceArtifact", "normalizer", "receiptDigest")
    return any(field in receipt for field in fields)


def _validate_sidecar_binding(receipt: dict[str, Any]) -> None:
    for key in ("adapterId", "routeDecisionDigest", "sourceArtifact", "normalizer", "receiptDigest"):
        if key not in receipt:
            raise LifecycleError("invalid-model-usage-receipt", f"normalized sidecar requires {key}")
    for key in ("adapterId", "host"):
        if not isinstance(receipt.get(key), str) or not receipt[key]:
            raise LifecycleError("invalid-model-usage-receipt", f"{key} is required for adapter-local sidecars")
    for key in ("providerModelHash", "routeDecisionDigest", "receiptDigest"):
        if not _is_digest(receipt.get(key)):
            raise LifecycleError("invalid-model-usage-receipt", f"{key} must be a SHA-256 digest")
    source = receipt.get("sourceArtifact")
    if not isinstance(source, dict):
        raise LifecycleError("invalid-model-usage-receipt", "sourceArtifact must be an object")
    if any("path" in str(key).lower() for key in source):
        raise LifecycleError("invalid-model-usage-receipt", "sourceArtifact must not contain paths")
    if not _is_digest(source.get("sha256")):
        raise LifecycleError("invalid-model-usage-receipt", "sourceArtifact.sha256 must be a digest")
    if not isinstance(source.get("bytes"), int) or isinstance(source.get("bytes"), bool) or source["bytes"] < 0:
        raise LifecycleError("invalid-model-usage-receipt", "sourceArtifact.bytes must be non-negative")
    if not isinstance(source.get("format"), str) or not source["format"]:
        raise LifecycleError("invalid-model-usage-receipt", "sourceArtifact.format is required")
    normalizer = receipt.get("normalizer")
    if not isinstance(normalizer, dict):
        raise LifecycleError("invalid-model-usage-receipt", "normalizer must be an object")
    if normalizer.get("contract") != "adapter-local-usage-normalizer.v1":
        raise LifecycleError("invalid-model-usage-receipt", "normalizer contract is unsupported")
    status = normalizer.get("status")
    if status not in {"UNSUPPORTED", "FIXTURE_ONLY", "QUALIFIED"}:
        raise LifecycleError("invalid-model-usage-receipt", "normalizer status is unsupported")
    accepted = normalizer.get("acceptedForS1S2")
    if not isinstance(accepted, bool) or accepted is not (status == "QUALIFIED"):
        raise LifecycleError("invalid-model-usage-receipt", "normalizer qualification is inconsistent")
    if not _is_digest(normalizer.get("digest")):
        raise LifecycleError("invalid-model-usage-receipt", "normalizer.digest must be a SHA-256 digest")
    expected_receipt_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt["receiptDigest"] != expected_receipt_digest:
        raise LifecycleError("invalid-model-usage-receipt", "receiptDigest does not match sidecar content")


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value.lower())


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
