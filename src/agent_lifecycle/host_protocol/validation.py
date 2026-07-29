"""Adapter descriptor and host-operation validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.host_protocol.contracts import HostOperationReceipt, HostOperationRequest

REQUIRED_DESCRIPTOR_FIELDS = {
    "schemaVersion",
    "adapterId",
    "host",
    "maturity",
    "liveTestedHostRange",
    "contractCompatibility",
    "unsupportedOperationPolicy",
    "coreSemantics",
    "operations",
}
REQUIRED_OPERATION_NAMES = {
    "install",
    "discover",
    "validate-envelope",
    "launch",
    "model-route-execution",
    "wait",
    "cancel",
    "resume",
    "tool-execution",
    "result-collection",
    "usage-attestation",
    "task-audit",
    "final-audit",
}


def validate_adapter_descriptor(
    descriptor: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    requests: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate one host adapter projection without executing host runtime code."""

    blockers: list[dict[str, Any]] = []
    _validate_descriptor_shape(descriptor, blockers)
    if baseline is not None:
        _validate_baseline(descriptor, baseline, blockers)
    request_contracts = [HostOperationRequest.from_json(item) for item in requests or []]
    receipt_contracts = [HostOperationReceipt.from_json(item) for item in receipts or []]
    _validate_request_receipt_pairs(request_contracts, receipt_contracts, blockers)
    status = "PASS" if not blockers else "FAIL"
    return {
        "schemaVersion": "agent-host-adapter-validation.v1",
        "status": status,
        "adapterId": descriptor.get("adapterId"),
        "host": descriptor.get("host"),
        "maturity": descriptor.get("maturity"),
        "operationCount": len(descriptor.get("operations", [])) if isinstance(descriptor.get("operations"), list) else 0,
        "requestCount": len(request_contracts),
        "receiptCount": len(receipt_contracts),
        "blockers": blockers,
        "hostProtocolContracts": [
            HostOperationRequest.schema_version,
            HostOperationReceipt.schema_version,
        ],
    }


def _validate_descriptor_shape(descriptor: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if descriptor.get("schemaVersion") != "agent-lifecycle-host-adapter.v1":
        blockers.append({"code": "invalid-adapter-schema", "message": "unsupported adapter descriptor schemaVersion"})
    missing = sorted(field for field in REQUIRED_DESCRIPTOR_FIELDS if field not in descriptor)
    if missing:
        blockers.append({"code": "invalid-adapter-descriptor", "message": "required adapter descriptor fields are missing", "fields": missing})
    for key in ("adapterId", "host"):
        if not isinstance(descriptor.get(key), str) or not descriptor.get(key):
            blockers.append({"code": "invalid-adapter-descriptor", "message": f"{key} must be a non-empty string"})
    if descriptor.get("maturity") not in {"EXPERIMENTAL", "VERIFIED"}:
        blockers.append({"code": "invalid-adapter-maturity", "message": "adapter maturity must be EXPERIMENTAL or VERIFIED"})
    if descriptor.get("maturity") == "VERIFIED" and not descriptor.get("liveTestedHostRange"):
        blockers.append({"code": "verified-adapter-without-live-evidence", "message": "VERIFIED adapters require liveTestedHostRange evidence"})
    if descriptor.get("unsupportedOperationPolicy") != "fail-closed":
        blockers.append({"code": "adapter-unsupported-operation-policy", "message": "unsupported operations must fail closed"})
    if descriptor.get("coreSemantics") != "delegated-to-agent-lifecycle-core":
        blockers.append({"code": "adapter-core-semantics-overclaim", "message": "adapter must delegate lifecycle semantics to core"})
    operations = descriptor.get("operations")
    if not isinstance(operations, list):
        blockers.append({"code": "invalid-adapter-operations", "message": "operations must be an array"})
        return
    provided = {item.get("name") for item in operations if isinstance(item, dict)}
    missing_operations = sorted(REQUIRED_OPERATION_NAMES.difference(provided))
    if missing_operations:
        blockers.append({"code": "adapter-required-operation-missing", "message": "required operations are missing", "operations": missing_operations})


def _validate_baseline(descriptor: dict[str, Any], baseline: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    rules = baseline.get("maturityRules", {})
    expected_maturity = rules.get("requiredReleaseMaturity")
    if expected_maturity and not _maturity_satisfies_baseline(descriptor, expected_maturity, rules):
        blockers.append({"code": "adapter-baseline-maturity-mismatch", "expected": expected_maturity, "actual": descriptor.get("maturity")})
    expected_policy = baseline.get("maturityRules", {}).get("unsupportedOperationPolicy")
    if expected_policy and descriptor.get("unsupportedOperationPolicy") != expected_policy:
        blockers.append({"code": "adapter-baseline-policy-mismatch", "expected": expected_policy, "actual": descriptor.get("unsupportedOperationPolicy")})
    expected_contract = baseline.get("contractCompatibility")
    if expected_contract and descriptor.get("contractCompatibility") != expected_contract:
        blockers.append({"code": "adapter-contract-compatibility-mismatch", "message": "descriptor contractCompatibility differs from baseline"})
    required = set(baseline.get("requiredOperations", []))
    if required:
        operations = descriptor.get("operations", [])
        provided = {item.get("name") for item in operations if isinstance(item, dict)}
        missing = sorted(required.difference(provided))
        if missing:
            blockers.append({"code": "adapter-baseline-operation-missing", "operations": missing})


def _maturity_satisfies_baseline(
    descriptor: dict[str, Any],
    expected_maturity: str,
    rules: dict[str, Any],
) -> bool:
    actual = descriptor.get("maturity")
    if actual == expected_maturity:
        return True
    return (
        expected_maturity == "EXPERIMENTAL"
        and actual == "VERIFIED"
        and rules.get("verifiedRequiresLiveEvidence") is True
        and bool(descriptor.get("liveTestedHostRange"))
    )


def _validate_request_receipt_pairs(
    requests: list[HostOperationRequest],
    receipts: list[HostOperationReceipt],
    blockers: list[dict[str, Any]],
) -> None:
    requests_by_operation = {item.operation_id: item for item in requests}
    for receipt in receipts:
        request = requests_by_operation.get(receipt.operation_id)
        if request is None:
            blockers.append({"code": "host-receipt-without-request", "operationId": receipt.operation_id})
            continue
        if request.capability != receipt.capability:
            blockers.append(
                {
                    "code": "host-receipt-capability-mismatch",
                    "operationId": receipt.operation_id,
                    "requestCapability": request.capability,
                    "receiptCapability": receipt.capability,
                }
            )


def require_adapter_validation_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("adapter-validation-failed", "adapter validation failed", {"validation": payload})
    return payload
