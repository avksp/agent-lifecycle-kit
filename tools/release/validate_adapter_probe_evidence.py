from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from release_common import canonical_bytes, file_identity, load_json, sha256_hex, write_json

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.host_protocol import HostOperationReceipt, HostOperationRequest


PLAN_SCHEMA = "agent-adapter-probe-plan.v1"
VALIDATION_SCHEMA = "agent-adapter-probe-evidence-validation.v1"
RECEIPT_SCHEMA = "agent-lifecycle-live-host-conformance-receipt.v1"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--receipt-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan)
    receipt_dir = Path(args.receipt_dir)
    plan = load_json(plan_path)
    blockers: list[dict[str, Any]] = []
    _validate_plan(plan, blockers)
    if not receipt_dir.is_dir():
        blockers.append({"code": "adapter-probe-receipt-dir-missing", "path": receipt_dir.as_posix()})
    checks: list[dict[str, Any]] = []
    if receipt_dir.is_dir():
        for host_plan in _host_plans(plan):
            checks.append(_validate_host_evidence(host_plan, receipt_dir, blockers))
    body = {
        "schemaVersion": VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "plan": file_identity(plan_path),
        "receiptDir": receipt_dir.as_posix(),
        "hostCount": len(_host_plans(plan)),
        "checks": checks,
        "driftDetected": bool(blockers),
        "blockers": blockers,
        "promotionDecision": "NOT_EVALUATED",
        "maturityChangeClaimed": False,
        "productionPromotionClaimed": False,
    }
    write_json(Path(args.out), {**body, "validationDigest": sha256_hex(canonical_bytes(body))})
    return 0 if not blockers else 1


def _validate_plan(plan: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if plan.get("schemaVersion") != PLAN_SCHEMA:
        blockers.append({"code": "adapter-probe-plan-schema-invalid"})
    if plan.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "adapter-probe-plan-production-claim"})
    if plan.get("maturityChangeClaimed") is not False:
        blockers.append({"code": "adapter-probe-plan-maturity-claim"})
    if plan.get("promotionDecision") != "NOT_EVALUATED":
        blockers.append({"code": "adapter-probe-plan-promotion-decision-invalid"})
    hosts = plan.get("hosts")
    if not isinstance(hosts, list) or not hosts:
        blockers.append({"code": "adapter-probe-plan-hosts-invalid"})


def _validate_host_evidence(host_plan: dict[str, Any], receipt_dir: Path, blockers: list[dict[str, Any]]) -> dict[str, Any]:
    host = host_plan.get("host")
    adapter_id = host_plan.get("adapterId")
    before = len(blockers)
    receipt_path = receipt_dir / f"{host}.json"
    planned = _planned_probe_names(host_plan)
    check: dict[str, Any] = {
        "adapterId": adapter_id,
        "host": host,
        "plannedOperationCount": len(planned),
        "passedOperationCount": 0,
        "receipt": file_identity(receipt_path) if receipt_path.is_file() else None,
        "operations": [],
    }
    if not isinstance(host, str) or not host:
        blockers.append({"code": "adapter-probe-host-invalid", "adapterId": adapter_id})
        check["status"] = "FAIL"
        return check
    if not receipt_path.is_file():
        blockers.append({"code": "adapter-probe-receipt-missing", "host": host, "path": receipt_path.as_posix()})
        check["status"] = "FAIL"
        return check
    receipt = load_json(receipt_path)
    _validate_receipt_header(host, receipt, blockers)
    operations = _receipt_operations(receipt, host, blockers)
    passed = 0
    for probe in planned:
        op_check = _validate_operation(host, probe, operations.get(probe["name"]), blockers)
        if op_check["status"] == "PASS":
            passed += 1
        check["operations"].append(op_check)
    check["passedOperationCount"] = passed
    check["status"] = "PASS" if len(blockers) == before else "FAIL"
    return check


def _validate_receipt_header(host: str, receipt: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    if receipt.get("schemaVersion") != RECEIPT_SCHEMA:
        blockers.append({"code": "adapter-probe-receipt-schema-invalid", "host": host})
    if receipt.get("host") != host:
        blockers.append({"code": "adapter-probe-receipt-host-mismatch", "host": host, "actual": receipt.get("host")})
    if receipt.get("status") != "PASS":
        blockers.append({"code": "adapter-probe-receipt-not-pass", "host": host})
    if receipt.get("syntheticReplayUsed") is not False:
        blockers.append({"code": "adapter-probe-synthetic-receipt", "host": host})
    if receipt.get("usageAttested") is not True:
        blockers.append({"code": "adapter-probe-usage-unattested", "host": host})
    if receipt.get("productionPromotionClaimed") is True:
        blockers.append({"code": "adapter-probe-receipt-production-claim", "host": host})


def _validate_operation(
    host: str,
    probe: dict[str, Any],
    operation: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    name = probe["name"]
    before = len(blockers)
    if operation is None:
        blockers.append({"code": "adapter-probe-operation-missing", "host": host, "operation": name})
        return {"name": name, "status": "FAIL", "liveEvidenceRequired": probe["liveEvidenceRequired"]}
    if operation.get("status") != "PASS":
        blockers.append({"code": "adapter-probe-operation-not-pass", "host": host, "operation": name})
    if probe.get("liveEvidenceRequired") is True and operation.get("syntheticReplayUsed") is not False:
        blockers.append({"code": "adapter-probe-operation-synthetic", "host": host, "operation": name})
    _validate_host_protocol_envelopes(host, name, operation, blockers)
    return {"name": name, "status": "PASS" if len(blockers) == before else "FAIL", "liveEvidenceRequired": probe["liveEvidenceRequired"]}


def _validate_host_protocol_envelopes(host: str, operation_name: str, operation: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    request_payload = operation.get("hostOperationRequest")
    receipt_payload = operation.get("hostOperationReceipt")
    if not isinstance(request_payload, dict) or not isinstance(receipt_payload, dict):
        blockers.append({"code": "adapter-probe-host-protocol-missing", "host": host, "operation": operation_name})
        return
    try:
        request = HostOperationRequest.from_json(request_payload)
        receipt = HostOperationReceipt.from_json(receipt_payload)
    except LifecycleError as error:
        blockers.append({"code": "adapter-probe-host-protocol-invalid", "host": host, "operation": operation_name, "error": error.code})
        return
    if request.operation_id != receipt.operation_id:
        blockers.append({"code": "adapter-probe-operation-id-mismatch", "host": host, "operation": operation_name})
    if request.capability != operation_name or receipt.capability != operation_name:
        blockers.append({"code": "adapter-probe-capability-mismatch", "host": host, "operation": operation_name})
    if receipt.status != "PASS":
        blockers.append({"code": "adapter-probe-host-receipt-not-pass", "host": host, "operation": operation_name})


def _receipt_operations(receipt: dict[str, Any], host: str, blockers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    operations = receipt.get("operations")
    if not isinstance(operations, list) or not operations:
        blockers.append({"code": "adapter-probe-operations-invalid", "host": host})
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in operations:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            blockers.append({"code": "adapter-probe-operation-invalid", "host": host})
            continue
        result[item["name"]] = item
    return result


def _host_plans(plan: dict[str, Any]) -> list[dict[str, Any]]:
    hosts = plan.get("hosts")
    if not isinstance(hosts, list):
        return []
    return [item for item in hosts if isinstance(item, dict)]


def _planned_probe_names(host_plan: dict[str, Any]) -> list[dict[str, Any]]:
    probes = host_plan.get("probes")
    if not isinstance(probes, list):
        return []
    return [
        {"name": item["name"], "liveEvidenceRequired": item.get("liveEvidenceRequired") is True}
        for item in probes
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]


if __name__ == "__main__":
    raise SystemExit(main())
