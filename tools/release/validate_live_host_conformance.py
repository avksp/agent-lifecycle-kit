from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import file_identity, load_json, write_json

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest


RECEIPT_SCHEMA = "agent-lifecycle-live-host-conformance-receipt.v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--receipt-dir", required=True)
    parser.add_argument("--promoted-hosts", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--probe-plan")
    parser.add_argument("--operation-request")
    args = parser.parse_args()

    profile_path = Path(args.profile)
    baseline_path = Path(args.baseline)
    receipt_dir = Path(args.receipt_dir)
    profile = load_json(profile_path)
    baseline = load_json(baseline_path)
    probe_plan_path = Path(args.probe_plan) if args.probe_plan else None
    probe_plan = load_json(probe_plan_path) if probe_plan_path else None
    promoted_hosts = _split_hosts(args.promoted_hosts)

    blockers: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    receipt_identities: list[dict[str, Any]] = []

    _validate_inputs(profile, baseline, receipt_dir, promoted_hosts, blockers)
    if probe_plan is not None:
        _validate_probe_plan(probe_plan, promoted_hosts, blockers)
    if receipt_dir.is_dir():
        for host in promoted_hosts:
            receipt_path = receipt_dir / f"{host}.json"
            if not receipt_path.is_file():
                blockers.append({"code": "missing-live-host-receipt", "message": f"live host receipt is required for {host}"})
                continue
            receipt = load_json(receipt_path)
            receipt_identities.append(file_identity(receipt_path))
            checks.append(_validate_receipt(host, baseline, receipt, blockers))

    evidence = {
        "schemaVersion": "agent-live-host-conformance-verification.v1",
        "status": "PASS" if not blockers else "FAIL",
        "profile": file_identity(profile_path),
        "baseline": file_identity(baseline_path),
        "adapterProbePlan": file_identity(probe_plan_path) if probe_plan_path else None,
        "promotedHosts": promoted_hosts,
        "receipts": receipt_identities,
        "checks": checks,
        "blockers": blockers,
        "productionPromotionClaimed": False,
        "operationRequest": args.operation_request,
    }
    write_json(Path(args.evidence), evidence)
    return 0 if not blockers else 1


def _validate_inputs(
    profile: dict[str, Any],
    baseline: dict[str, Any],
    receipt_dir: Path,
    promoted_hosts: list[str],
    blockers: list[dict[str, Any]],
) -> None:
    if profile.get("schemaVersion") != "agent-lifecycle-live-calibration-profile.v1":
        blockers.append({"code": "invalid-live-calibration-profile", "message": "unsupported profile schemaVersion"})
    if baseline.get("schemaVersion") != "agent-lifecycle-adapter-baseline.v1":
        blockers.append({"code": "invalid-adapter-baseline", "message": "unsupported adapter baseline schemaVersion"})
    if not receipt_dir.is_dir():
        blockers.append({"code": "missing-live-host-receipt-dir", "message": "live host receipt directory does not exist"})
    if not promoted_hosts:
        blockers.append({"code": "missing-promoted-hosts", "message": "--promoted-hosts must name at least one host"})
    profile_hosts = set(_strings(profile.get("requiredHosts")))
    baseline_hosts = set(_strings(baseline.get("requiredHosts")))
    for host in promoted_hosts:
        if host not in profile_hosts:
            blockers.append({"code": "live-host-not-in-calibration-profile", "message": f"{host} is not in live calibration requiredHosts"})
        if host not in baseline_hosts:
            blockers.append({"code": "live-host-not-in-adapter-baseline", "message": f"{host} is not in adapter baseline requiredHosts"})
    if profile.get("syntheticAcceptedForProductionPromotion") is not False:
        blockers.append({"code": "synthetic-live-host-conformance-allowed", "message": "synthetic receipts must not promote production"})


def _validate_probe_plan(
    probe_plan: dict[str, Any],
    promoted_hosts: list[str],
    blockers: list[dict[str, Any]],
) -> None:
    if probe_plan.get("schemaVersion") != "agent-adapter-probe-plan.v1":
        blockers.append({"code": "invalid-adapter-probe-plan", "message": "unsupported probe plan schemaVersion"})
    if probe_plan.get("status") != "PASS":
        blockers.append({"code": "adapter-probe-plan-not-pass", "message": "probe plan status must be PASS"})
    if probe_plan.get("liveCallsStarted") is not False:
        blockers.append({"code": "adapter-probe-plan-started-live-calls", "message": "probe plan must be declarative"})
    if probe_plan.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "adapter-probe-plan-production-claim", "message": "probe plans must not claim production promotion"})
    if probe_plan.get("maturityChangeClaimed") is not False:
        blockers.append({"code": "adapter-probe-plan-maturity-claim", "message": "probe plans must not claim maturity changes"})
    plan_hosts = {
        item.get("host")
        for item in probe_plan.get("hosts", [])
        if isinstance(item, dict) and isinstance(item.get("host"), str)
    }
    for host in promoted_hosts:
        if host not in plan_hosts:
            blockers.append({"code": "promoted-host-missing-from-probe-plan", "message": f"{host} is not covered by probe plan"})


def _validate_receipt(
    expected_host: str,
    baseline: dict[str, Any],
    receipt: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    host = receipt.get("host")
    required_operations = set(_strings(baseline.get("requiredOperations")))
    operation_checks: list[dict[str, Any]] = []
    passed_operations: set[str] = set()

    if receipt.get("schemaVersion") != RECEIPT_SCHEMA:
        blockers.append({"code": "invalid-live-host-receipt", "message": f"{expected_host} receipt has unsupported schemaVersion"})
    if receipt.get("status") != "PASS":
        blockers.append({"code": "live-host-receipt-not-pass", "message": f"{expected_host} receipt status must be PASS"})
    if host != expected_host:
        blockers.append({"code": "live-host-receipt-host-mismatch", "message": f"receipt for {expected_host} reports {host}"})
    if receipt.get("syntheticReplayUsed") is not False:
        blockers.append({"code": "synthetic-live-host-receipt", "message": f"{expected_host} receipt must not use synthetic replay"})
    if receipt.get("usageAttested") is not True:
        blockers.append({"code": "live-host-usage-unattested", "message": f"{expected_host} receipt must attest usage"})

    operations = receipt.get("operations")
    if not isinstance(operations, list) or not operations:
        blockers.append({"code": "invalid-live-host-operations", "message": f"{expected_host} receipt operations must be a non-empty array"})
        operations = []

    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            blockers.append({"code": "invalid-live-host-operation", "message": f"{expected_host} operation {index} must be an object"})
            continue
        name = operation.get("name")
        if not isinstance(name, str) or not name:
            blockers.append({"code": "invalid-live-host-operation", "message": f"{expected_host} operation {index} has invalid name"})
            continue
        op_blockers_before = len(blockers)
        if operation.get("status") != "PASS":
            blockers.append({"code": "live-host-operation-not-pass", "message": f"{expected_host}/{name} status must be PASS"})
        if operation.get("syntheticReplayUsed") is not False:
            blockers.append({"code": "synthetic-live-host-operation", "message": f"{expected_host}/{name} must not use synthetic replay"})
        _validate_host_protocol_envelopes(expected_host, name, operation, blockers)
        if len(blockers) == op_blockers_before:
            passed_operations.add(name)
        operation_checks.append({"name": name, "status": "PASS" if len(blockers) == op_blockers_before else "FAIL"})

    missing = sorted(required_operations - passed_operations)
    for name in missing:
        blockers.append({"code": "live-host-operation-missing", "message": f"{expected_host}/{name} did not pass live conformance"})

    return {
        "host": host,
        "requiredOperationCount": len(required_operations),
        "passedOperationCount": len(passed_operations),
        "operations": operation_checks,
    }


def _validate_host_protocol_envelopes(
    expected_host: str,
    operation_name: str,
    operation: dict[str, Any],
    blockers: list[dict[str, Any]],
) -> None:
    request_payload = operation.get("hostOperationRequest")
    receipt_payload = operation.get("hostOperationReceipt")
    if not isinstance(request_payload, dict) or not isinstance(receipt_payload, dict):
        blockers.append({"code": "host-protocol-envelope-missing", "message": f"{expected_host}/{operation_name} must include request and receipt envelopes"})
        return
    try:
        request = HostOperationRequest.from_json(request_payload)
        receipt = HostOperationReceipt.from_json(receipt_payload)
    except LifecycleError as error:
        blockers.append({"code": "host-protocol-envelope-invalid", "message": f"{expected_host}/{operation_name}: {error.code}"})
        return
    if request.operation_id != receipt.operation_id:
        blockers.append({"code": "host-protocol-operation-id-mismatch", "message": f"{expected_host}/{operation_name} operationId mismatch"})
    if request.capability != operation_name or receipt.capability != operation_name:
        blockers.append({"code": "host-protocol-capability-mismatch", "message": f"{expected_host}/{operation_name} capability mismatch"})
    if receipt.status != "PASS":
        blockers.append({"code": "host-protocol-receipt-not-pass", "message": f"{expected_host}/{operation_name} receipt status must be PASS"})


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _split_hosts(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
