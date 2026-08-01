"""Runtime policy receipts for enforceable or advisory host decisions."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest

RUNTIME_POLICY_RECEIPT_SCHEMA = "agent-runtime-policy-receipt.v1"
RUNTIME_POLICY_RECEIPT_VALIDATION_SCHEMA = "agent-runtime-policy-receipt-validation.v1"

RUNTIME_ACTIONS = {"ALLOW", "DENY", "ASK"}
ENFORCEMENT_MODES = {"enforced", "advisory"}


def build_runtime_policy_receipt(
    *,
    policy_id: str,
    action: str,
    subject: dict[str, Any],
    adapter_evidence: dict[str, Any],
    enforcement_mode: str = "advisory",
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a receipt without claiming enforcement unless evidence proves it."""

    mode = _enum(enforcement_mode, ENFORCEMENT_MODES, label="enforcementMode")
    body = {
        "schemaVersion": RUNTIME_POLICY_RECEIPT_SCHEMA,
        "status": "PASS",
        "policyId": _required_string(policy_id, label="policyId"),
        "action": _enum(action, RUNTIME_ACTIONS, label="action"),
        "subject": _object(subject, label="subject"),
        "adapterEvidence": _object(adapter_evidence, label="adapterEvidence"),
        "enforcementMode": mode,
        "enforcementClaimed": mode == "enforced",
        "advisoryOnly": mode == "advisory",
        "decisionRecordedBeforeExecution": adapter_evidence.get("decisionRecordedBeforeExecution") is True,
        "evidenceIds": _string_list(evidence_ids or [], label="evidenceIds", allow_empty=True),
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    blockers = _runtime_policy_blockers(body)
    body["status"] = "PASS" if not blockers else "FAIL"
    body["blockers"] = blockers
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_runtime_policy_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-runtime-policy-receipt", "runtime policy receipt must be an object")
    blockers: list[dict[str, Any]] = []
    if receipt.get("schemaVersion") != RUNTIME_POLICY_RECEIPT_SCHEMA:
        blockers.append({"code": "runtime-policy-receipt-schema-invalid"})
    if receipt.get("status") not in {"PASS", "FAIL"}:
        blockers.append({"code": "runtime-policy-receipt-status-invalid"})
    if not isinstance(receipt.get("policyId"), str) or not receipt["policyId"]:
        blockers.append({"code": "runtime-policy-id-missing"})
    if receipt.get("action") not in RUNTIME_ACTIONS:
        blockers.append({"code": "runtime-policy-action-invalid", "action": receipt.get("action")})
    if not isinstance(receipt.get("subject"), dict) or not receipt["subject"]:
        blockers.append({"code": "runtime-policy-subject-invalid"})
    if not isinstance(receipt.get("adapterEvidence"), dict) or not receipt["adapterEvidence"]:
        blockers.append({"code": "runtime-policy-adapter-evidence-invalid"})
    if receipt.get("enforcementMode") not in ENFORCEMENT_MODES:
        blockers.append({"code": "runtime-policy-enforcement-mode-invalid"})
    if not isinstance(receipt.get("enforcementClaimed"), bool):
        blockers.append({"code": "runtime-policy-enforcement-claim-invalid"})
    if not isinstance(receipt.get("advisoryOnly"), bool):
        blockers.append({"code": "runtime-policy-advisory-flag-invalid"})
    if not isinstance(receipt.get("decisionRecordedBeforeExecution"), bool):
        blockers.append({"code": "runtime-policy-decision-timing-invalid"})
    if not isinstance(receipt.get("evidenceIds", []), list) or not all(
        isinstance(item, str) and item for item in receipt.get("evidenceIds", [])
    ):
        blockers.append({"code": "runtime-policy-evidence-ids-invalid"})
    if not isinstance(receipt.get("blockers", []), list) or not all(
        isinstance(item, dict) for item in receipt.get("blockers", [])
    ):
        blockers.append({"code": "runtime-policy-blockers-invalid"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "runtime-policy-production-claim"})
    semantic_blockers = _runtime_policy_blockers(receipt) if not blockers else []
    if not blockers:
        if receipt.get("blockers", []) != semantic_blockers:
            blockers.append({"code": "runtime-policy-blockers-mismatch"})
        blockers.extend(semantic_blockers)
        expected_status = "PASS" if not semantic_blockers else "FAIL"
        if receipt.get("status") != expected_status:
            blockers.append({"code": "runtime-policy-status-mismatch"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "runtime-policy-receipt-digest-mismatch"})
    body = {
        "schemaVersion": RUNTIME_POLICY_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": receipt.get("status") if isinstance(receipt.get("status"), str) else None,
        "policyId": receipt.get("policyId") if isinstance(receipt.get("policyId"), str) else None,
        "action": receipt.get("action") if isinstance(receipt.get("action"), str) else None,
        "enforcementMode": receipt.get("enforcementMode") if isinstance(receipt.get("enforcementMode"), str) else None,
        "enforcementClaimed": receipt.get("enforcementClaimed") if isinstance(receipt.get("enforcementClaimed"), bool) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest") if isinstance(receipt.get("receiptDigest"), str) else None,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_runtime_policy_receipt_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
        raise LifecycleError("runtime-policy-receipt-validation-failed", "runtime policy receipt did not pass", {"validation": validation})
    return validation


def _runtime_policy_blockers(receipt: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    mode = receipt.get("enforcementMode")
    enforcement_claimed = receipt.get("enforcementClaimed") is True
    advisory_only = receipt.get("advisoryOnly") is True
    evidence = receipt.get("adapterEvidence") if isinstance(receipt.get("adapterEvidence"), dict) else {}
    pre_execution = evidence.get("preExecutionEnforcement") is True
    decision_before_execution = receipt.get("decisionRecordedBeforeExecution") is True
    if mode == "enforced" and not enforcement_claimed:
        blockers.append({"code": "runtime-policy-enforcement-flag-mismatch"})
    if mode == "advisory" and not advisory_only:
        blockers.append({"code": "runtime-policy-advisory-flag-mismatch"})
    if enforcement_claimed and advisory_only:
        blockers.append({"code": "runtime-policy-enforcement-and-advisory"})
    if enforcement_claimed and not pre_execution:
        blockers.append({"code": "runtime-policy-enforcement-unproven"})
    if enforcement_claimed and not decision_before_execution:
        blockers.append({"code": "runtime-policy-decision-not-pre-execution"})
    if not enforcement_claimed and mode == "enforced":
        blockers.append({"code": "runtime-policy-mode-unproven"})
    if mode == "advisory" and evidence.get("postFactumOnly") is True and enforcement_claimed:
        blockers.append({"code": "runtime-policy-post-factum-enforcement-claim"})
    return blockers


def _object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise LifecycleError("invalid-runtime-policy-receipt", f"{label} must be a non-empty object")
    return dict(value)


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-runtime-policy-receipt", f"{label} is required")
    return value


def _string_list(value: Any, *, label: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("invalid-runtime-policy-receipt", f"{label} must be a list of strings")
    return list(value)


def _enum(value: Any, allowed: set[str], *, label: str) -> str:
    if value not in allowed:
        raise LifecycleError("invalid-runtime-policy-receipt", f"{label} is unsupported", {label: value})
    return str(value)
