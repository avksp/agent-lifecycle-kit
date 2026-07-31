"""Neutral ACP host capability declarations and fail-closed probe receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError

ACP_CAPABILITY_ID = "acp"
HOST_CAPABILITY_SCHEMA_VERSION = "agent-host-capability.v1"
HOST_CAPABILITY_VALIDATION_SCHEMA_VERSION = "agent-host-capability-validation.v1"
ACP_PROBE_RECEIPT_SCHEMA_VERSION = "agent-acp-probe-receipt.v1"
_SUPPORTED_VALUES = {"supported", "unsupported", "unknown"}


def build_acp_capability(
    *,
    adapter_id: str,
    host: str,
    support: str,
    probe_command: list[str] | None = None,
) -> dict[str, Any]:
    """Build a schema-backed ACP capability declaration without provider identity."""

    capability: dict[str, Any] = {
        "schemaVersion": HOST_CAPABILITY_SCHEMA_VERSION,
        "capabilityId": ACP_CAPABILITY_ID,
        "adapterId": adapter_id,
        "host": host,
        "support": support,
        "transport": "acp" if support == "supported" else "unknown",
        "evidencePolicy": "probe-required" if support == "supported" else "not-claimed",
        "providerIdentityUsed": False,
        "probe": None,
        "invocationContract": None,
    }
    if support == "supported":
        capability["probe"] = {
            "required": True,
            "command": list(probe_command or [host, "--help"]),
            "liveCallsStarted": False,
        }
        capability["invocationContract"] = {
            "requestSchema": "agent-host-operation-request.v1",
            "receiptSchema": "agent-host-operation-receipt.v1",
            "unsupportedOperationPolicy": "fail-closed",
        }
    return capability


def validate_host_capabilities(
    capabilities: Any,
    *,
    adapter_id: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Validate optional host capability declarations attached to a descriptor."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(capabilities, list):
        blockers.append({"code": "invalid-host-capabilities", "message": "hostCapabilities must be an array"})
        return _validation_result(0, blockers)
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            blockers.append({"code": "invalid-host-capability", "index": index, "message": "host capability must be an object"})
            continue
        _validate_capability_shape(capability, blockers, index=index, adapter_id=adapter_id, host=host)
    return _validation_result(len(capabilities), blockers)


def validate_no_acp_evidence_for_hosts(capabilities: list[dict[str, Any]], *, excluded_hosts: set[str]) -> dict[str, Any]:
    """Validate that excluded hosts have no positive ACP evidence declarations."""

    blockers: list[dict[str, Any]] = []
    for capability in capabilities:
        if capability.get("capabilityId") != ACP_CAPABILITY_ID:
            continue
        host = capability.get("host")
        if isinstance(host, str) and host in excluded_hosts and capability.get("support") == "supported":
            blockers.append({"code": "excluded-host-acp-evidence", "host": host})
    return _validation_result(len(capabilities), blockers)


def build_acp_probe_receipt(
    capability: dict[str, Any],
    *,
    executable_found: bool,
    probe_passed: bool,
    invocation_contract_valid: bool,
) -> dict[str, Any]:
    """Return a fail-closed ACP probe receipt without starting live model calls."""

    validation = validate_host_capabilities(
        [capability],
        adapter_id=capability.get("adapterId") if isinstance(capability.get("adapterId"), str) else None,
        host=capability.get("host") if isinstance(capability.get("host"), str) else None,
    )
    blockers = list(validation["blockers"])
    support = capability.get("support")
    checks = [
        {"name": "capability-declaration", "status": validation["status"]},
        {"name": "executable-present", "status": "PASS" if executable_found else "FAIL"},
        {"name": "acp-probe", "status": "PASS" if probe_passed else "FAIL"},
        {"name": "invocation-contract", "status": "PASS" if invocation_contract_valid else "FAIL"},
    ]
    if support != "supported":
        return {
            "schemaVersion": ACP_PROBE_RECEIPT_SCHEMA_VERSION,
            "status": "SKIPPED",
            "adapterId": capability.get("adapterId"),
            "host": capability.get("host"),
            "capabilityId": ACP_CAPABILITY_ID,
            "liveCallsStarted": False,
            "checks": checks[:1],
            "blockers": blockers,
        }
    if not executable_found:
        blockers.append({"code": "acp-executable-missing"})
    if not probe_passed:
        blockers.append({"code": "acp-probe-failed"})
    if not invocation_contract_valid:
        blockers.append({"code": "acp-invocation-contract-invalid"})
    return {
        "schemaVersion": ACP_PROBE_RECEIPT_SCHEMA_VERSION,
        "status": "PASS" if not blockers else "FAIL",
        "adapterId": capability.get("adapterId"),
        "host": capability.get("host"),
        "capabilityId": ACP_CAPABILITY_ID,
        "liveCallsStarted": False,
        "checks": checks,
        "blockers": blockers,
    }


def require_host_capabilities_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") == "FAIL":
        raise LifecycleError("host-capability-validation-failed", "host capability validation failed", {"validation": payload})
    return payload


def _validate_capability_shape(
    capability: dict[str, Any],
    blockers: list[dict[str, Any]],
    *,
    index: int,
    adapter_id: str | None,
    host: str | None,
) -> None:
    if capability.get("schemaVersion") != HOST_CAPABILITY_SCHEMA_VERSION:
        blockers.append({"code": "invalid-host-capability-schema", "index": index})
    if capability.get("capabilityId") != ACP_CAPABILITY_ID:
        blockers.append({"code": "unsupported-host-capability", "index": index, "capabilityId": capability.get("capabilityId")})
    if capability.get("support") not in _SUPPORTED_VALUES:
        blockers.append({"code": "invalid-host-capability-support", "index": index})
    if capability.get("providerIdentityUsed") is not False:
        blockers.append({"code": "host-capability-provider-identity", "index": index})
    if adapter_id is not None and capability.get("adapterId") != adapter_id:
        blockers.append({"code": "host-capability-adapter-mismatch", "index": index})
    if host is not None and capability.get("host") != host:
        blockers.append({"code": "host-capability-host-mismatch", "index": index})
    if capability.get("support") == "supported":
        _validate_supported_acp(capability, blockers, index=index)


def _validate_supported_acp(capability: dict[str, Any], blockers: list[dict[str, Any]], *, index: int) -> None:
    if capability.get("transport") != "acp":
        blockers.append({"code": "supported-acp-transport-mismatch", "index": index})
    if capability.get("evidencePolicy") != "probe-required":
        blockers.append({"code": "supported-acp-probe-policy-missing", "index": index})
    probe = capability.get("probe")
    if not isinstance(probe, dict) or probe.get("required") is not True:
        blockers.append({"code": "supported-acp-probe-required", "index": index})
    elif not isinstance(probe.get("command"), list) or not all(isinstance(item, str) and item for item in probe["command"]):
        blockers.append({"code": "supported-acp-probe-command-invalid", "index": index})
    elif probe.get("liveCallsStarted") is not False:
        blockers.append({"code": "supported-acp-probe-live-call-overclaim", "index": index})
    contract = capability.get("invocationContract")
    if not isinstance(contract, dict):
        blockers.append({"code": "supported-acp-invocation-contract-missing", "index": index})
        return
    if contract.get("requestSchema") != "agent-host-operation-request.v1":
        blockers.append({"code": "supported-acp-request-schema", "index": index})
    if contract.get("receiptSchema") != "agent-host-operation-receipt.v1":
        blockers.append({"code": "supported-acp-receipt-schema", "index": index})
    if contract.get("unsupportedOperationPolicy") != "fail-closed":
        blockers.append({"code": "supported-acp-unsupported-policy", "index": index})


def _validation_result(capability_count: int, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemaVersion": HOST_CAPABILITY_VALIDATION_SCHEMA_VERSION,
        "status": "PASS" if not blockers else "FAIL",
        "capabilityCount": capability_count,
        "blockers": blockers,
    }
