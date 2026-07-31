"""Audit helpers for bug-forensics gate evidence."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.workflow.bug_forensics_gates import validate_bug_forensics_gate_receipt

BUG_FORENSICS_AUDIT_SCHEMA = "agent-bug-forensics-audit.v1"
BUG_FORENSICS_AUDIT_VALIDATION_SCHEMA = "agent-bug-forensics-audit-validation.v1"


def build_bug_forensics_audit(*, gate_receipt: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
    """Audit that an accepted bug-forensics gate covers the required chain."""

    gate_validation = validate_bug_forensics_gate_receipt(gate_receipt)
    blockers: list[dict[str, Any]] = []
    gate_status = gate_validation.get("gateStatus")
    if gate_validation.get("status") != "PASS":
        blockers.append({"code": "bug-forensics-gate-invalid", "validation": gate_validation})
    if gate_receipt.get("activated") is True and gate_status != "PASS":
        blockers.append({"code": "bug-forensics-active-gate-not-pass", "gateStatus": gate_status})
    evidence = gate_receipt.get("evidence") if isinstance(gate_receipt.get("evidence"), dict) else {}
    coverage = {
        "reproductionBeforeModification": evidence.get("reproduction") is not None,
        "failureFingerprint": evidence.get("failureFingerprint") is not None,
        "hypothesisLedger": evidence.get("hypothesisLedger") is not None,
        "regressionProof": evidence.get("regressionProof") is not None,
        "fixImpactReceiptReused": evidence.get("fixImpact") is not None,
        "crossCheckReceiptReused": evidence.get("crossCheck") is not None,
        "phase2Deferred": list(gate_receipt.get("phase2Deferred", [])),
    }
    status = "SKIPPED" if gate_status == "SKIPPED" else ("PASS" if not blockers else "FAIL")
    body = {
        "schemaVersion": BUG_FORENSICS_AUDIT_SCHEMA,
        "status": status,
        "taskId": task_id or gate_receipt.get("taskId"),
        "gateReceiptDigest": gate_receipt.get("receiptDigest"),
        "coverage": coverage,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "auditDigest": canonical_digest(body)}


def validate_bug_forensics_audit(audit: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(audit, dict):
        raise LifecycleError("invalid-bug-forensics-audit", "bug-forensics audit must be an object")
    if audit.get("schemaVersion") != BUG_FORENSICS_AUDIT_SCHEMA:
        blockers.append({"code": "bug-forensics-audit-schema-invalid"})
    audit_status = audit.get("status")
    if audit_status not in {"PASS", "FAIL", "SKIPPED"}:
        blockers.append({"code": "bug-forensics-audit-status-invalid", "status": audit_status})
    if audit.get("gateReceiptDigest") is not None and not _is_digest(audit.get("gateReceiptDigest")):
        blockers.append({"code": "bug-forensics-audit-gate-digest-invalid"})
    if not isinstance(audit.get("coverage"), dict):
        blockers.append({"code": "bug-forensics-audit-coverage-invalid"})
    if not isinstance(audit.get("blockers"), list) or not all(isinstance(item, dict) for item in audit.get("blockers", [])):
        blockers.append({"code": "bug-forensics-audit-blockers-invalid"})
    if audit.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "bug-forensics-audit-production-claim"})
    expected_digest = canonical_digest({key: value for key, value in audit.items() if key != "auditDigest"})
    if audit.get("auditDigest") != expected_digest:
        blockers.append({"code": "bug-forensics-audit-digest-mismatch"})
    if audit_status == "FAIL" and not audit.get("blockers"):
        blockers.append({"code": "bug-forensics-audit-fail-without-blockers"})
    body = {
        "schemaVersion": BUG_FORENSICS_AUDIT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "auditStatus": audit_status if isinstance(audit_status, str) else None,
        "blockers": blockers,
        "auditDigest": audit.get("auditDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_bug_forensics_audit_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("auditStatus") not in {"PASS", "SKIPPED"}:
        raise LifecycleError("bug-forensics-audit-validation-failed", "bug-forensics audit did not pass", {"validation": validation})
    return validation


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


__all__ = [
    "BUG_FORENSICS_AUDIT_SCHEMA",
    "build_bug_forensics_audit",
    "require_bug_forensics_audit_pass",
    "validate_bug_forensics_audit",
]
