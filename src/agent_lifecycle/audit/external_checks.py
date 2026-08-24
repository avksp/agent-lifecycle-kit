"""Audit helpers for external verification results."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.external_check_schemas import validate_external_check_result


def audit_external_check_result(
    result: dict[str, Any],
    *,
    descriptor: dict[str, Any],
    invocation: dict[str, Any],
    blocking_required: bool = False,
) -> dict[str, Any]:
    """Return a fail-closed audit decision without granting implementation authority."""

    validation = validate_external_check_result(result, descriptor=descriptor, invocation=invocation)
    blockers = list(validation.get("blockers", []))
    if blocking_required and validation.get("blockingEligible") is not True:
        blockers.append({"code": "external-check-blocking-evidence-unavailable"})
    body = {
        "schemaVersion": "agent-external-check-audit.v1",
        "status": "PASS" if not blockers and result.get("status") == "PASS" else "FAIL",
        "resultStatus": result.get("status") if isinstance(result.get("status"), str) else None,
        "resultDigest": result.get("resultDigest"),
        "descriptorDigest": result.get("descriptorDigest"),
        "sourceSnapshot": result.get("sourceSnapshot"),
        "findingCount": len(result.get("findings", [])) if isinstance(result.get("findings"), list) else 0,
        "blockingRequired": bool(blocking_required),
        "blockingEligible": not blockers and result.get("blockingEligible") is True,
        "blockers": blockers,
        "authorityClaimed": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "auditDigest": canonical_digest(body)}


def require_external_check_audit_pass(audit: dict[str, Any]) -> dict[str, Any]:
    """Require a clean audit while keeping authority outside this receipt."""

    if audit.get("status") != "PASS" or audit.get("blockingEligible") is not True:
        raise LifecycleError("external-check-audit-failed", "external check audit is not eligible", {"audit": audit})
    if audit.get("authorityClaimed") is not False:
        raise LifecycleError("external-check-audit-authority-claimed", "external check audit cannot claim authority")
    return audit


__all__ = ["audit_external_check_result", "require_external_check_audit_pass"]
