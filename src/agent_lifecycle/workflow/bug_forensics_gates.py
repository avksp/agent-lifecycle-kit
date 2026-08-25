"""Workflow gate helpers for the optional bug-forensics profile."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.proof_validation import validate_fix_impact_receipt
from agent_lifecycle.quality.bug_forensics import (
    build_bug_forensics_profile,
    validate_bug_forensics_profile,
    validate_bug_reproduction_receipt,
    validate_failure_fingerprint,
    validate_hypothesis_ledger,
    validate_regression_proof_receipt,
)
from agent_lifecycle.quality.cross_check import validate_cross_check_receipt
from agent_lifecycle.quality.failure_classification import (
    HIGH_RISK_FAILURE_CLASSES,
    validate_failure_classification_receipt,
)
from agent_lifecycle.quality.security_analysis import (
    build_security_analysis_profile,
    build_security_execution_gate_receipt,
    security_analysis_activated,
    validate_security_analysis_profile,
    validate_security_execution_gate_receipt,
)

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
    failure_classification: dict[str, Any] | None = None,
    flake_signal: dict[str, Any] | None = None,
    hypothesis_ledger: dict[str, Any] | None = None,
    regression_proof: dict[str, Any] | None = None,
    fix_impact_receipt: dict[str, Any] | None = None,
    cross_check_receipt: dict[str, Any] | None = None,
    security_profile: dict[str, Any] | None = None,
    security_execution_receipt: dict[str, Any] | None = None,
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
            failure_classification=failure_classification,
            flake_signal=flake_signal,
            hypothesis_ledger=hypothesis_ledger,
            regression_proof=regression_proof,
            fix_impact_receipt=fix_impact_receipt,
            cross_check_receipt=cross_check_receipt,
        )
        status = "PASS" if not blockers else "FAIL"

    security_evidence: dict[str, Any] | None = None
    if security_analysis_activated(task):
        selected_security_profile = security_profile or build_security_analysis_profile()
        profile_validation = validate_security_analysis_profile(selected_security_profile)
        security_evidence = {"profile": profile_validation}
        if profile_validation.get("status") != "PASS":
            blockers.append({"code": "security-analysis-profile-invalid", "validation": profile_validation})
        if security_execution_receipt is not None:
            execution_validation = validate_security_execution_gate_receipt(security_execution_receipt)
            security_evidence["execution"] = execution_validation
            if execution_validation.get("status") != "PASS":
                blockers.append(
                    {"code": "security-analysis-execution-gate-invalid", "validation": execution_validation}
                )
        elif isinstance(task.get("securityAnalysis"), dict) and task["securityAnalysis"].get("explicitOptIn") is True:
            security_execution_receipt = build_security_execution_gate_receipt(task=task)
            security_evidence["execution"] = validate_security_execution_gate_receipt(security_execution_receipt)
            blockers.append({"code": "security-analysis-execution-authorization-required"})
        if blockers:
            status = "FAIL"

    evidence = {
        "reproduction": _digest_ref(reproduction_receipt, "receiptDigest"),
        "failureFingerprint": _digest_ref(failure_fingerprint, "fingerprintDigest"),
        "failureClassification": _digest_ref(failure_classification, "classificationDigest"),
        "flakeSignal": _flake_signal_summary(flake_signal),
        "hypothesisLedger": _digest_ref(hypothesis_ledger, "ledgerDigest"),
        "regressionProof": _digest_ref(regression_proof, "proofDigest"),
        "fixImpact": _digest_ref(fix_impact_receipt, "impactDigest"),
        "crossCheck": _digest_ref(cross_check_receipt, "receiptDigest"),
        "securityAnalysis": security_evidence,
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
    if not isinstance(receipt.get("blockers"), list) or not all(
        isinstance(item, dict) for item in receipt.get("blockers", [])
    ):
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
        raise LifecycleError(
            "bug-forensics-gate-validation-failed", "bug-forensics gate did not pass", {"validation": validation}
        )
    return validation


def _collect_active_gate_blockers(
    blockers: list[dict[str, Any]],
    validations: dict[str, Any],
    *,
    task: dict[str, Any],
    reproduction_receipt: dict[str, Any] | None,
    failure_fingerprint: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
    flake_signal: dict[str, Any] | None,
    hypothesis_ledger: dict[str, Any] | None,
    regression_proof: dict[str, Any] | None,
    fix_impact_receipt: dict[str, Any] | None,
    cross_check_receipt: dict[str, Any] | None,
) -> None:
    for key, value, validator, missing_code in [
        ("reproduction", reproduction_receipt, validate_bug_reproduction_receipt, "bug-forensics-reproduction-missing"),
        ("failureFingerprint", failure_fingerprint, validate_failure_fingerprint, "bug-forensics-fingerprint-missing"),
        ("hypothesisLedger", hypothesis_ledger, validate_hypothesis_ledger, "bug-forensics-hypothesis-ledger-missing"),
        (
            "regressionProof",
            regression_proof,
            validate_regression_proof_receipt,
            "bug-forensics-regression-proof-missing",
        ),
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
    if _classification_required(task) and failure_classification is None:
        blockers.append({"code": "bug-forensics-failure-classification-missing"})
    if failure_classification is not None:
        validation = validate_failure_classification_receipt(failure_classification)
        validations["failureClassification"] = validation
        if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
            blockers.append({"code": "bug-forensics-failure-classification-invalid", "validation": validation})
    if flake_signal is not None:
        validations["flakeSignal"] = _validate_flake_signal(flake_signal)
        if validations["flakeSignal"]["status"] != "PASS":
            blockers.append({"code": "bug-forensics-flake-signal-invalid", "validation": validations["flakeSignal"]})
    if _cross_check_required(task, failure_classification):
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


def _cross_check_required(task: dict[str, Any], failure_classification: dict[str, Any] | None = None) -> bool:
    if task.get("blockingCrossCheckRequired") is True or task.get("crossCheckRequired") is True:
        return True
    config = task.get("bugForensics")
    if isinstance(config, dict) and config.get("crossCheckRequired") is True:
        return True
    return _high_risk_classification(task, failure_classification)


def _classification_required(task: dict[str, Any]) -> bool:
    config = task.get("bugForensics")
    if isinstance(config, dict) and config.get("requireFailureClassification") is True:
        return True
    return task.get("requireFailureClassification") is True


def _high_risk_classification(task: dict[str, Any], failure_classification: dict[str, Any] | None) -> bool:
    if not isinstance(failure_classification, dict):
        return False
    if failure_classification.get("failureClass") not in HIGH_RISK_FAILURE_CLASSES:
        return False
    risks = task.get("riskFlags", {})
    active_security = (
        bool(risks.get("security"))
        if isinstance(risks, dict)
        else "security" in risks
        if isinstance(risks, list)
        else False
    )
    return task.get("sddTier") == "S2" or active_security


def _digest_ref(value: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"schemaVersion": value.get("schemaVersion"), "digest": value.get(key)}


def _flake_signal_summary(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "status": value.get("status") or value.get("flakeStatus"),
        "runs": value.get("runs"),
        "failures": value.get("failures"),
    }


def _validate_flake_signal(value: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    status = value.get("status") or value.get("flakeStatus")
    if status not in {"stable-fail", "stable-pass", "flaky", "inconclusive"}:
        blockers.append({"code": "flake-signal-status-invalid", "status": status})
    for field in ("runs", "failures"):
        if field in value and (not isinstance(value[field], int) or isinstance(value[field], bool) or value[field] < 0):
            blockers.append({"code": "flake-signal-count-invalid", "field": field})
    body = {
        "schemaVersion": "agent-flake-signal-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "flakeStatus": status if isinstance(status, str) else None,
        "blockers": blockers,
    }
    return {**body, "validationDigest": canonical_digest(body)}


__all__ = [
    "BUG_FORENSICS_GATE_RECEIPT_SCHEMA",
    "bug_forensics_activated",
    "build_bug_forensics_gate_receipt",
    "require_bug_forensics_gate_pass",
    "validate_bug_forensics_gate_receipt",
]
