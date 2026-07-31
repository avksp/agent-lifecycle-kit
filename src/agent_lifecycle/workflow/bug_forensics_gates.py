"""Workflow gate helpers for the optional bug-forensics profile."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.audit.proof_integrity import validate_fix_impact_receipt
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.quality.bug_forensics import (
    build_bug_forensics_profile,
    validate_bug_forensics_profile,
    validate_bug_reproduction_receipt,
    validate_failure_fingerprint,
    validate_hypothesis_ledger,
    validate_regression_proof_receipt,
)
from agent_lifecycle.quality.cross_check import validate_cross_check_receipt

BUG_FORENSICS_GATE_RECEIPT_SCHEMA = "agent-bug-forensics-gate-receipt.v1"
BUG_FORENSICS_GATE_VALIDATION_SCHEMA = "agent-bug-forensics-gate-validation.v1"


def bug_forensics_activated(task: dict[str, Any]) -> bool:
    """Return true only when the task explicitly enables the optional profile."""

    if not isinstance(task, dict):
        return False
    if task.get("qualityProfile") == "bug-forensics":
        return True
    profiles = task.get("qualityProfiles")
    if isinstance(profiles, list) and "bug-forensics" in profiles:
        return True
    config = task.get("bugForensics")
    return isinstance(config, dict) and config.get("enabled") is True


def build_bug_forensics_gate_receipt(
    *,
    task: dict[str, Any],
    profile: dict[str, Any] | None = None,
    reproduction_receipt: dict[str, Any] | None = None,
    failure_fingerprint: dict[str, Any] | None = None,
    hypothesis_ledger: dict[str, Any] | None = None,
    regression_proof: dict[str, Any] | None = None,
    fix_impact_receipt: dict[str, Any] | None = None,
    cross_check_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a gate receipt for an optional bug-forensics run."""

    selected_profile = profile or build_bug_forensics_profile()
    activated = bug_forensics_activated(task)
    blockers: list[dict[str, Any]] = []
    validations: dict[str, Any] = {"profile": validate_bug_forensics_profile(selected_profile)}
    if validations["profile"]["status"] != "PASS":
        blockers.append({"code": "bug-forensics-profile-invalid", "validation": validations["profile"]})

    if not activated:
        status = "SKIPPED"
    else:
        _collect_active_gate_blockers(
            blockers,
            validations,
            task=task,
            reproduction_receipt=reproduction_receipt,
            failure_fingerprint=failure_fingerprint,
            hypothesis_ledger=hypothesis_ledger,
            regression_proof=regression_proof,
            fix_impact_receipt=fix_impact_receipt,
            cross_check_receipt=cross_check_receipt,
        )
        status = "PASS" if not blockers else "FAIL"

    evidence = {
        "reproduction": _digest_ref(reproduction_receipt, "receiptDigest"),
        "failureFingerprint": _digest_ref(failure_fingerprint, "fingerprintDigest"),
        "hypothesisLedger": _digest_ref(hypothesis_ledger, "ledgerDigest"),
        "regressionProof": _digest_ref(regression_proof, "proofDigest"),
        "fixImpact": _digest_ref(fix_impact_receipt, "impactDigest"),
        "crossCheck": _digest_ref(cross_check_receipt, "receiptDigest"),
        "validations": validations,
    }
    body = {
        "schemaVersion": BUG_FORENSICS_GATE_RECEIPT_SCHEMA,
        "status": status,
        "taskId": task.get("taskId") or task.get("id"),
        "profileId": selected_profile.get("profileId", "bug-forensics"),
        "activated": activated,
        "chainVerified": activated and status == "PASS",
        "evidence": evidence,
        "blockers": blockers,
        "phase2Deferred": list(selected_profile.get("phase2Deferred", [])),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_bug_forensics_gate_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-bug-forensics-gate-receipt", "bug-forensics gate receipt must be an object")
    if receipt.get("schemaVersion") != BUG_FORENSICS_GATE_RECEIPT_SCHEMA:
        blockers.append({"code": "bug-forensics-gate-schema-invalid"})
    gate_status = receipt.get("status")
    if gate_status not in {"PASS", "FAIL", "SKIPPED"}:
        blockers.append({"code": "bug-forensics-gate-status-invalid", "status": gate_status})
    if not isinstance(receipt.get("profileId"), str) or not receipt["profileId"]:
        blockers.append({"code": "bug-forensics-gate-profile-id-invalid"})
    if not isinstance(receipt.get("activated"), bool):
        blockers.append({"code": "bug-forensics-gate-activation-invalid"})
    if not isinstance(receipt.get("chainVerified"), bool):
        blockers.append({"code": "bug-forensics-gate-chain-invalid"})
    if receipt.get("activated") is True and gate_status == "PASS" and receipt.get("chainVerified") is not True:
        blockers.append({"code": "bug-forensics-gate-chain-not-verified"})
    if receipt.get("activated") is True and gate_status == "SKIPPED":
        blockers.append({"code": "bug-forensics-gate-skipped-while-activated"})
    if not isinstance(receipt.get("evidence"), dict):
        blockers.append({"code": "bug-forensics-gate-evidence-invalid"})
    if not isinstance(receipt.get("blockers"), list) or not all(isinstance(item, dict) for item in receipt.get("blockers", [])):
        blockers.append({"code": "bug-forensics-gate-blockers-invalid"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "bug-forensics-gate-production-claim"})
    expected_digest = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "bug-forensics-gate-digest-mismatch"})
    if gate_status == "FAIL" and not receipt.get("blockers"):
        blockers.append({"code": "bug-forensics-gate-fail-without-blockers"})
    body = {
        "schemaVersion": BUG_FORENSICS_GATE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "gateStatus": gate_status if isinstance(gate_status, str) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_bug_forensics_gate_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("gateStatus") not in {"PASS", "SKIPPED"}:
        raise LifecycleError("bug-forensics-gate-validation-failed", "bug-forensics gate did not pass", {"validation": validation})
    return validation


def _collect_active_gate_blockers(
    blockers: list[dict[str, Any]],
    validations: dict[str, Any],
    *,
    task: dict[str, Any],
    reproduction_receipt: dict[str, Any] | None,
    failure_fingerprint: dict[str, Any] | None,
    hypothesis_ledger: dict[str, Any] | None,
    regression_proof: dict[str, Any] | None,
    fix_impact_receipt: dict[str, Any] | None,
    cross_check_receipt: dict[str, Any] | None,
) -> None:
    for key, value, validator, missing_code in [
        ("reproduction", reproduction_receipt, validate_bug_reproduction_receipt, "bug-forensics-reproduction-missing"),
        ("failureFingerprint", failure_fingerprint, validate_failure_fingerprint, "bug-forensics-fingerprint-missing"),
        ("hypothesisLedger", hypothesis_ledger, validate_hypothesis_ledger, "bug-forensics-hypothesis-ledger-missing"),
        ("regressionProof", regression_proof, validate_regression_proof_receipt, "bug-forensics-regression-proof-missing"),
    ]:
        if value is None:
            blockers.append({"code": missing_code})
            continue
        validation = validator(value)
        validations[key] = validation
        if validation.get("status") != "PASS":
            blockers.append({"code": f"{key}-invalid", "validation": validation})
    if fix_impact_receipt is None:
        blockers.append({"code": "bug-forensics-fix-impact-missing"})
    else:
        validation = validate_fix_impact_receipt(fix_impact_receipt)
        validations["fixImpact"] = validation
        if validation.get("status") != "PASS":
            blockers.append({"code": "bug-forensics-fix-impact-invalid", "validation": validation})
    if failure_fingerprint is not None and regression_proof is not None:
        before = regression_proof.get("before") if isinstance(regression_proof, dict) else {}
        if isinstance(before, dict) and before.get("fingerprintDigest") != failure_fingerprint.get("fingerprintDigest"):
            blockers.append({"code": "bug-forensics-fingerprint-regression-mismatch"})
    if _cross_check_required(task):
        if cross_check_receipt is None:
            blockers.append({"code": "bug-forensics-cross-check-missing"})
        else:
            validation = validate_cross_check_receipt(cross_check_receipt)
            validations["crossCheck"] = validation
            if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
                blockers.append({"code": "bug-forensics-cross-check-invalid", "validation": validation})
    elif cross_check_receipt is not None:
        validation = validate_cross_check_receipt(cross_check_receipt)
        validations["crossCheck"] = validation
        if validation.get("status") != "PASS":
            blockers.append({"code": "bug-forensics-cross-check-invalid", "validation": validation})


def _cross_check_required(task: dict[str, Any]) -> bool:
    if task.get("blockingCrossCheckRequired") is True or task.get("crossCheckRequired") is True:
        return True
    config = task.get("bugForensics")
    if isinstance(config, dict) and config.get("crossCheckRequired") is True:
        return True
    return False


def _digest_ref(value: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"schemaVersion": value.get("schemaVersion"), "digest": value.get(key)}


__all__ = [
    "BUG_FORENSICS_GATE_RECEIPT_SCHEMA",
    "build_bug_forensics_gate_receipt",
    "bug_forensics_activated",
    "require_bug_forensics_gate_pass",
    "validate_bug_forensics_gate_receipt",
]
