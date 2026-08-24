"""Shared construction and validation primitives for compiler output contracts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest


def build_output_contract(
    *,
    schema_version: str,
    task_id: str | None,
    result_schema_version: str,
    allowed_statuses: list[str],
    required_fields: list[str],
    write_scope: dict[str, Any],
    validation: dict[str, Any],
    production_promotion_claimed: bool = False,
) -> dict[str, Any]:
    """Build the common, digest-bound portion of a compiler output contract."""

    body = {
        "schemaVersion": schema_version,
        "taskId": task_id,
        "requiredSchemaVersion": result_schema_version,
        "allowedStatuses": list(allowed_statuses),
        "requiredFields": list(required_fields),
        "writeScope": dict(write_scope),
        "writeScopeDigest": canonical_digest(write_scope),
        "validation": dict(validation),
        "productionPromotionClaimed": production_promotion_claimed,
    }
    return {**body, "contractDigest": canonical_digest(body)}


def validate_output_contract(
    output: dict[str, Any],
    contract: dict[str, Any],
    *,
    contract_schema_version: str,
    output_schema_version: str,
) -> list[dict[str, Any]]:
    """Return deterministic common contract failures without accepting output."""

    blockers: list[dict[str, Any]] = []
    if contract.get("schemaVersion") != contract_schema_version:
        blockers.append({"code": "output-contract-schema"})
    if output.get("schemaVersion") != output_schema_version:
        blockers.append({"code": "output-schema"})
    for field in contract.get("requiredFields", []):
        if field not in output:
            blockers.append({"code": "output-field-missing", "field": field})
    if output.get("taskId") != contract.get("taskId"):
        blockers.append({"code": "output-task-mismatch", "taskId": output.get("taskId")})
    if output.get("status") not in contract.get("allowedStatuses", []):
        blockers.append({"code": "output-status", "status": output.get("status")})
    if output.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "output-production-claim"})
    if output.get("writeScopeDigest") != contract.get("writeScopeDigest"):
        blockers.append({"code": "output-write-scope-digest"})
    if output.get("outputContractDigest") != contract.get("contractDigest"):
        blockers.append({"code": "output-contract-digest"})
    return blockers


__all__ = ["build_output_contract", "validate_output_contract"]
