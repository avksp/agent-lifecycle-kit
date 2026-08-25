"""Optional Bug Forensics / Defect Repair profile helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, normalize_repo_path
from agent_lifecycle.quality.security_analysis import (
    build_security_analysis_profile,
    validate_security_analysis_profile,
)

BUG_FORENSICS_PROFILE_SCHEMA = "agent-bug-forensics-profile.v1"
BUG_FORENSICS_PROFILE_VALIDATION_SCHEMA = "agent-bug-forensics-profile-validation.v1"
BUG_REPRODUCTION_RECEIPT_SCHEMA = "agent-bug-reproduction-receipt.v1"
BUG_REPRODUCTION_RECEIPT_VALIDATION_SCHEMA = "agent-bug-reproduction-receipt-validation.v1"
FAILURE_FINGERPRINT_SCHEMA = "agent-failure-fingerprint.v1"
FAILURE_FINGERPRINT_VALIDATION_SCHEMA = "agent-failure-fingerprint-validation.v1"
BUG_HYPOTHESIS_LEDGER_SCHEMA = "agent-bug-hypothesis-ledger.v1"
BUG_HYPOTHESIS_LEDGER_VALIDATION_SCHEMA = "agent-bug-hypothesis-ledger-validation.v1"
REGRESSION_PROOF_RECEIPT_SCHEMA = "agent-regression-proof-receipt.v1"
REGRESSION_PROOF_RECEIPT_VALIDATION_SCHEMA = "agent-regression-proof-receipt-validation.v1"

FIX_IMPACT_SCHEMA = "agent-fix-impact-receipt.v1"
CROSS_CHECK_RECEIPT_SCHEMA = "agent-cross-check-receipt.v1"

PROFILE_STATUS = "OPTIONAL"
REPRODUCED_COMMAND_STATUSES = {"FAIL", "ERROR"}
AFTER_FIX_COMMAND_STATUSES = {"PASS"}
RECEIPT_STATUSES = {"PASS", "FAIL", "INCONCLUSIVE"}
HYPOTHESIS_STATUSES = {"ACCEPTED", "REJECTED", "INCONCLUSIVE"}
MONEY_KEYS = {"costUsd", "cost_usd", "usd", "budgetUsd", "maxUsd", "money", "monetary"}

EVIDENCE_CHAIN = (
    "symptom",
    "reproduction",
    "failure-fingerprint",
    "hypothesis-ledger",
    "root-cause",
    "minimal-fix",
    "regression-proof",
    "no-collateral-damage",
)
PHASE1_REQUIRED = (
    "reproduction-before-modification",
    "failure-fingerprint",
    "hypothesis-ledger",
    "minimal-patch-gate",
    "same-fingerprint-regression-proof",
    "fix-impact-reference",
)
PHASE2_DEFERRED = ("suspect-graph", "flake-detector", "bug-class-classifier")
DEFAULT_CONTEXT_BUDGET = {
    "profile": "bug-forensics-compact",
    "maxActivePacketTokens": 9000,
    "maxEvidenceSummaryTokens": 4000,
    "maxHypothesisLedgerEntries": 12,
    "maxArtifactDigestRefs": 20,
    "budgetUnits": "tokens-and-resources",
}
DEFAULT_CROSS_CHECK_POLICY = {
    "requiredByDefault": False,
    "reuseSchemaVersion": CROSS_CHECK_RECEIPT_SCHEMA,
    "blockingRequiresPlanOptIn": True,
    "budgetUnits": "tokens-and-resources",
    "riskTriggers": ["S2", "security-bug", "release-blocker", "high-risk"],
}


def build_bug_forensics_profile(
    *,
    context_budget: dict[str, Any] | None = None,
    cross_check_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the disabled-by-default bug-forensics profile."""

    budget = _context_budget(context_budget or DEFAULT_CONTEXT_BUDGET)
    cross_check = _cross_check_policy(cross_check_policy or DEFAULT_CROSS_CHECK_POLICY)
    body = {
        "schemaVersion": BUG_FORENSICS_PROFILE_SCHEMA,
        "profileId": "bug-forensics",
        "status": PROFILE_STATUS,
        "enabledByDefault": False,
        "activationMode": "explicit-task-trigger",
        "evidenceChain": list(EVIDENCE_CHAIN),
        "phase1Required": list(PHASE1_REQUIRED),
        "phase2Deferred": list(PHASE2_DEFERRED),
        "contextBudget": budget,
        "fixImpactAuthority": {
            "schemaVersion": FIX_IMPACT_SCHEMA,
            "reuseOnly": True,
            "competingSchemaAllowed": False,
        },
        "crossCheckPolicy": cross_check,
        "productionPromotionClaimed": False,
    }
    return {**body, "profileDigest": canonical_digest(body)}


build_security_profile = build_security_analysis_profile
validate_security_profile = validate_security_analysis_profile


def validate_bug_forensics_profile(profile: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        raise LifecycleError("invalid-bug-forensics-profile", "bug-forensics profile must be an object")
    if profile.get("schemaVersion") != BUG_FORENSICS_PROFILE_SCHEMA:
        blockers.append({"code": "bug-forensics-profile-schema-invalid"})
    if profile.get("profileId") != "bug-forensics":
        blockers.append({"code": "bug-forensics-profile-id-invalid"})
    if profile.get("status") != PROFILE_STATUS:
        blockers.append({"code": "bug-forensics-profile-status-invalid"})
    if profile.get("enabledByDefault") is not False:
        blockers.append({"code": "bug-forensics-profile-default-enabled"})
    if profile.get("activationMode") != "explicit-task-trigger":
        blockers.append({"code": "bug-forensics-profile-activation-invalid"})
    _check_contains(profile.get("evidenceChain"), EVIDENCE_CHAIN, "bug-forensics-chain-missing", blockers)
    _check_contains(profile.get("phase1Required"), PHASE1_REQUIRED, "bug-forensics-phase1-missing", blockers)
    _check_contains(profile.get("phase2Deferred"), PHASE2_DEFERRED, "bug-forensics-phase2-scope-missing", blockers)
    _validate_context_budget(profile.get("contextBudget"), blockers)
    fix_impact = profile.get("fixImpactAuthority")
    if not isinstance(fix_impact, dict):
        blockers.append({"code": "bug-forensics-fix-impact-authority-invalid"})
    else:
        if fix_impact.get("schemaVersion") != FIX_IMPACT_SCHEMA:
            blockers.append({"code": "bug-forensics-fix-impact-schema-not-reused"})
        if fix_impact.get("reuseOnly") is not True or fix_impact.get("competingSchemaAllowed") is not False:
            blockers.append({"code": "bug-forensics-fix-impact-competing-schema"})
    _validate_cross_check_policy(profile.get("crossCheckPolicy"), blockers)
    if profile.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "bug-forensics-profile-production-claim"})
    expected_digest = canonical_digest(_without_digest(profile, "profileDigest"))
    if profile.get("profileDigest") != expected_digest:
        blockers.append({"code": "bug-forensics-profile-digest-mismatch"})
    body = {
        "schemaVersion": BUG_FORENSICS_PROFILE_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "profileId": profile.get("profileId") if isinstance(profile.get("profileId"), str) else None,
        "blockers": blockers,
        "profileDigest": profile.get("profileDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_bug_reproduction_receipt(
    *,
    lineage: dict[str, Any],
    symptom: dict[str, Any],
    reproduction_command: list[str],
    command_status: str = "FAIL",
    artifact_digests: list[dict[str, Any]] | None = None,
    evidence_ids: list[str] | None = None,
    before_modification: bool = True,
    live_calls_started: bool = False,
) -> dict[str, Any]:
    """Record that the bug reproduces before any patch is applied."""

    artifacts = _artifact_digests(artifact_digests or [], allow_empty=False)
    status = (
        "PASS"
        if (before_modification and command_status in REPRODUCED_COMMAND_STATUSES and not live_calls_started)
        else "FAIL"
    )
    body = {
        "schemaVersion": BUG_REPRODUCTION_RECEIPT_SCHEMA,
        "status": status,
        "lineage": _object(lineage, "invalid-bug-reproduction-receipt", "lineage"),
        "symptom": _object(symptom, "invalid-bug-reproduction-receipt", "symptom"),
        "reproductionCommand": _string_list(
            reproduction_command, label="reproductionCommand", code="invalid-bug-reproduction-receipt"
        ),
        "commandStatus": _enum(
            command_status,
            {"FAIL", "ERROR", "PASS", "NOT_RUN", "INCONCLUSIVE"},
            label="commandStatus",
            code="invalid-bug-reproduction-receipt",
        ),
        "beforeModification": bool(before_modification),
        "artifactDigests": artifacts,
        "evidenceIds": _string_list(
            evidence_ids or [], label="evidenceIds", code="invalid-bug-reproduction-receipt", allow_empty=True
        ),
        "liveCallsStarted": bool(live_calls_started),
        "productionPromotionClaimed": False,
    }
    return {**body, "receiptDigest": canonical_digest(body)}


def validate_bug_reproduction_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-bug-reproduction-receipt", "bug reproduction receipt must be an object")
    if receipt.get("schemaVersion") != BUG_REPRODUCTION_RECEIPT_SCHEMA:
        blockers.append({"code": "bug-reproduction-schema-invalid"})
    status = receipt.get("status")
    if status not in RECEIPT_STATUSES:
        blockers.append({"code": "bug-reproduction-status-invalid", "status": status})
    if not isinstance(receipt.get("lineage"), dict) or not receipt["lineage"]:
        blockers.append({"code": "bug-reproduction-lineage-invalid"})
    if not isinstance(receipt.get("symptom"), dict) or not receipt["symptom"]:
        blockers.append({"code": "bug-reproduction-symptom-invalid"})
    _check_string_list(
        receipt.get("reproductionCommand"), "bug-reproduction-command-invalid", blockers, allow_empty=False
    )
    if receipt.get("commandStatus") not in {"FAIL", "ERROR", "PASS", "NOT_RUN", "INCONCLUSIVE"}:
        blockers.append({"code": "bug-reproduction-command-status-invalid", "status": receipt.get("commandStatus")})
    if receipt.get("beforeModification") is not True:
        blockers.append({"code": "bug-reproduction-not-before-modification"})
    if receipt.get("commandStatus") not in REPRODUCED_COMMAND_STATUSES:
        blockers.append({"code": "bug-reproduction-not-red", "commandStatus": receipt.get("commandStatus")})
    _check_artifact_digests(receipt.get("artifactDigests"), blockers, allow_empty=False)
    _check_string_list(
        receipt.get("evidenceIds", []), "bug-reproduction-evidence-ids-invalid", blockers, allow_empty=True
    )
    if receipt.get("liveCallsStarted") is not False:
        blockers.append({"code": "bug-reproduction-live-calls-started"})
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "bug-reproduction-production-claim"})
    expected_digest = canonical_digest(_without_digest(receipt, "receiptDigest"))
    if receipt.get("receiptDigest") != expected_digest:
        blockers.append({"code": "bug-reproduction-digest-mismatch"})
    if status != "PASS":
        blockers.append({"code": "bug-reproduction-receipt-not-pass", "status": status})
    body = {
        "schemaVersion": BUG_REPRODUCTION_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "receiptStatus": status if isinstance(status, str) else None,
        "blockers": blockers,
        "receiptDigest": receipt.get("receiptDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_failure_fingerprint(
    *,
    failure: dict[str, Any],
    affected_symbols: list[str] | None = None,
    finding_id: str | None = None,
    root_cause_digest: str | None = None,
    evidence_ids: list[str] | None = None,
    status: str = "PASS",
) -> dict[str, Any]:
    """Build a stable fingerprint from failure traits, not prose."""

    failure_fields = _object(failure, "invalid-failure-fingerprint", "failure")
    fingerprint_fields = {
        "exceptionType": failure_fields.get("exceptionType"),
        "failingAssertion": failure_fields.get("failingAssertion"),
        "logPattern": failure_fields.get("logPattern"),
        "stackTop": failure_fields.get("stackTop"),
        "affectedSymbols": sorted(affected_symbols or []),
    }
    body = {
        "schemaVersion": FAILURE_FINGERPRINT_SCHEMA,
        "status": _enum(status, RECEIPT_STATUSES, label="status", code="invalid-failure-fingerprint"),
        "failure": dict(failure_fields),
        "fingerprintFields": fingerprint_fields,
        "affectedSymbols": _string_list(
            affected_symbols or [], label="affectedSymbols", code="invalid-failure-fingerprint", allow_empty=True
        ),
        "findingId": _optional_string(finding_id),
        "rootCauseDigest": _optional_digest(root_cause_digest, code="invalid-failure-fingerprint"),
        "evidenceIds": _string_list(
            evidence_ids or [], label="evidenceIds", code="invalid-failure-fingerprint", allow_empty=True
        ),
        "productionPromotionClaimed": False,
    }
    return {**body, "fingerprintDigest": canonical_digest(fingerprint_fields)}


def validate_failure_fingerprint(fingerprint: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(fingerprint, dict):
        raise LifecycleError("invalid-failure-fingerprint", "failure fingerprint must be an object")
    if fingerprint.get("schemaVersion") != FAILURE_FINGERPRINT_SCHEMA:
        blockers.append({"code": "failure-fingerprint-schema-invalid"})
    if fingerprint.get("status") not in RECEIPT_STATUSES:
        blockers.append({"code": "failure-fingerprint-status-invalid", "status": fingerprint.get("status")})
    if not isinstance(fingerprint.get("failure"), dict) or not fingerprint["failure"]:
        blockers.append({"code": "failure-fingerprint-failure-invalid"})
    if not isinstance(fingerprint.get("fingerprintFields"), dict) or not fingerprint["fingerprintFields"]:
        blockers.append({"code": "failure-fingerprint-fields-invalid"})
    _check_string_list(
        fingerprint.get("affectedSymbols", []), "failure-fingerprint-symbols-invalid", blockers, allow_empty=True
    )
    if fingerprint.get("findingId") is not None and not isinstance(fingerprint.get("findingId"), str):
        blockers.append({"code": "failure-fingerprint-finding-id-invalid"})
    if fingerprint.get("rootCauseDigest") is not None:
        _check_digest(fingerprint.get("rootCauseDigest"), "failure-fingerprint-root-cause-digest-invalid", blockers)
    _check_string_list(
        fingerprint.get("evidenceIds", []), "failure-fingerprint-evidence-ids-invalid", blockers, allow_empty=True
    )
    if fingerprint.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "failure-fingerprint-production-claim"})
    expected_digest = canonical_digest(
        fingerprint.get("fingerprintFields") if isinstance(fingerprint.get("fingerprintFields"), dict) else {}
    )
    if fingerprint.get("fingerprintDigest") != expected_digest:
        blockers.append({"code": "failure-fingerprint-digest-mismatch"})
    body = {
        "schemaVersion": FAILURE_FINGERPRINT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "fingerprintDigest": fingerprint.get("fingerprintDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_hypothesis_ledger(
    *,
    lineage: dict[str, Any],
    hypotheses: list[dict[str, Any]],
    minimal_patch: dict[str, Any],
    evidence_ids: list[str] | None = None,
    phase2_deferred: list[str] | None = None,
) -> dict[str, Any]:
    """Build the hypothesis ledger and minimal-patch gate receipt."""

    body = {
        "schemaVersion": BUG_HYPOTHESIS_LEDGER_SCHEMA,
        "status": _ledger_status(hypotheses, minimal_patch),
        "lineage": _object(lineage, "invalid-bug-hypothesis-ledger", "lineage"),
        "hypotheses": [_hypothesis(item) for item in hypotheses],
        "minimalPatch": _minimal_patch(minimal_patch),
        "evidenceIds": _string_list(
            evidence_ids or [], label="evidenceIds", code="invalid-bug-hypothesis-ledger", allow_empty=True
        ),
        "phase2Deferred": _string_list(
            list(phase2_deferred or PHASE2_DEFERRED),
            label="phase2Deferred",
            code="invalid-bug-hypothesis-ledger",
            allow_empty=True,
        ),
        "productionPromotionClaimed": False,
    }
    return {**body, "ledgerDigest": canonical_digest(body)}


def validate_hypothesis_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(ledger, dict):
        raise LifecycleError("invalid-bug-hypothesis-ledger", "bug hypothesis ledger must be an object")
    if ledger.get("schemaVersion") != BUG_HYPOTHESIS_LEDGER_SCHEMA:
        blockers.append({"code": "bug-hypothesis-ledger-schema-invalid"})
    status = ledger.get("status")
    if status not in RECEIPT_STATUSES:
        blockers.append({"code": "bug-hypothesis-ledger-status-invalid", "status": status})
    if not isinstance(ledger.get("lineage"), dict) or not ledger["lineage"]:
        blockers.append({"code": "bug-hypothesis-ledger-lineage-invalid"})
    hypotheses = ledger.get("hypotheses")
    if not isinstance(hypotheses, list) or not hypotheses:
        blockers.append({"code": "bug-hypothesis-ledger-empty"})
        hypotheses = []
    hypothesis_statuses = {item.get("status") for item in hypotheses if isinstance(item, dict)}
    if "ACCEPTED" not in hypothesis_statuses:
        blockers.append({"code": "bug-hypothesis-accepted-missing"})
    if "REJECTED" not in hypothesis_statuses:
        blockers.append({"code": "bug-hypothesis-rejected-missing"})
    for index, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            blockers.append({"code": "bug-hypothesis-invalid", "index": index})
            continue
        for key in ("id", "cause", "check", "result"):
            if not isinstance(item.get(key), str) or not item[key]:
                blockers.append({"code": "bug-hypothesis-field-missing", "index": index, "field": key})
        if item.get("status") not in HYPOTHESIS_STATUSES:
            blockers.append({"code": "bug-hypothesis-status-invalid", "index": index, "status": item.get("status")})
    _validate_minimal_patch(ledger.get("minimalPatch"), blockers)
    _check_string_list(ledger.get("evidenceIds", []), "bug-hypothesis-evidence-ids-invalid", blockers, allow_empty=True)
    _check_string_list(ledger.get("phase2Deferred", []), "bug-hypothesis-phase2-invalid", blockers, allow_empty=True)
    if ledger.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "bug-hypothesis-production-claim"})
    expected_digest = canonical_digest(_without_digest(ledger, "ledgerDigest"))
    if ledger.get("ledgerDigest") != expected_digest:
        blockers.append({"code": "bug-hypothesis-ledger-digest-mismatch"})
    if status != "PASS":
        blockers.append({"code": "bug-hypothesis-ledger-not-pass", "status": status})
    body = {
        "schemaVersion": BUG_HYPOTHESIS_LEDGER_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "ledgerStatus": status if isinstance(status, str) else None,
        "blockers": blockers,
        "ledgerDigest": ledger.get("ledgerDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def build_regression_proof_receipt(
    *,
    lineage: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    reproduction_receipt: dict[str, Any],
    fix_impact_receipt: dict[str, Any],
    cross_check_receipt: dict[str, Any] | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build proof that the same failure fingerprint is red before and green after."""

    fix_impact = {
        "schemaVersion": fix_impact_receipt.get("schemaVersion"),
        "impactDigest": fix_impact_receipt.get("impactDigest"),
        "relatedFindingIds": list(fix_impact_receipt.get("relatedFindingIds", [])),
        "rootCauseDigests": list(fix_impact_receipt.get("rootCauseDigests", [])),
    }
    cross_check = None
    if cross_check_receipt is not None:
        cross_check = {
            "schemaVersion": cross_check_receipt.get("schemaVersion"),
            "receiptDigest": cross_check_receipt.get("receiptDigest"),
            "blocking": cross_check_receipt.get("blocking"),
            "budgetUnits": "tokens-and-resources",
        }
    status = "PASS" if _same_fingerprint_red_green(before, after) else "FAIL"
    body = {
        "schemaVersion": REGRESSION_PROOF_RECEIPT_SCHEMA,
        "status": status,
        "lineage": _object(lineage, "invalid-regression-proof-receipt", "lineage"),
        "before": dict(before),
        "after": dict(after),
        "reproductionReceiptDigest": _digest(
            reproduction_receipt.get("receiptDigest"), code="invalid-regression-proof-receipt"
        ),
        "fixImpact": fix_impact,
        "crossCheck": cross_check,
        "evidenceIds": _string_list(
            evidence_ids or [], label="evidenceIds", code="invalid-regression-proof-receipt", allow_empty=True
        ),
        "productionPromotionClaimed": False,
    }
    return {**body, "proofDigest": canonical_digest(body)}


def validate_regression_proof_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(receipt, dict):
        raise LifecycleError("invalid-regression-proof-receipt", "regression proof receipt must be an object")
    if receipt.get("schemaVersion") != REGRESSION_PROOF_RECEIPT_SCHEMA:
        blockers.append({"code": "regression-proof-schema-invalid"})
    status = receipt.get("status")
    if status not in RECEIPT_STATUSES:
        blockers.append({"code": "regression-proof-status-invalid", "status": status})
    if not isinstance(receipt.get("lineage"), dict) or not receipt["lineage"]:
        blockers.append({"code": "regression-proof-lineage-invalid"})
    before = receipt.get("before")
    after = receipt.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        blockers.append({"code": "regression-proof-before-after-invalid"})
        before = {}
        after = {}
    if not _same_fingerprint_red_green(before, after):
        blockers.append({"code": "regression-proof-same-fingerprint-red-green-missing"})
    _check_digest(receipt.get("reproductionReceiptDigest"), "regression-proof-reproduction-digest-invalid", blockers)
    fix_impact = receipt.get("fixImpact")
    if not isinstance(fix_impact, dict) or fix_impact.get("schemaVersion") != FIX_IMPACT_SCHEMA:
        blockers.append({"code": "regression-proof-fix-impact-schema-invalid"})
    else:
        _check_digest(fix_impact.get("impactDigest"), "regression-proof-fix-impact-digest-invalid", blockers)
    cross_check = receipt.get("crossCheck")
    if cross_check is not None:
        if not isinstance(cross_check, dict) or cross_check.get("schemaVersion") != CROSS_CHECK_RECEIPT_SCHEMA:
            blockers.append({"code": "regression-proof-cross-check-schema-invalid"})
        elif cross_check.get("budgetUnits") != "tokens-and-resources":
            blockers.append({"code": "regression-proof-cross-check-budget-units-invalid"})
    _check_string_list(
        receipt.get("evidenceIds", []), "regression-proof-evidence-ids-invalid", blockers, allow_empty=True
    )
    if receipt.get("productionPromotionClaimed") is not False:
        blockers.append({"code": "regression-proof-production-claim"})
    expected_digest = canonical_digest(_without_digest(receipt, "proofDigest"))
    if receipt.get("proofDigest") != expected_digest:
        blockers.append({"code": "regression-proof-digest-mismatch"})
    if status != "PASS":
        blockers.append({"code": "regression-proof-not-pass", "status": status})
    body = {
        "schemaVersion": REGRESSION_PROOF_RECEIPT_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "proofStatus": status if isinstance(status, str) else None,
        "blockers": blockers,
        "fingerprintDigest": before.get("fingerprintDigest") if isinstance(before, dict) else None,
        "proofDigest": receipt.get("proofDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def require_bug_forensics_profile_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS":
        raise LifecycleError(
            "bug-forensics-profile-validation-failed",
            "bug-forensics profile validation failed",
            {"validation": validation},
        )
    return validation


def require_bug_reproduction_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("receiptStatus") != "PASS":
        raise LifecycleError(
            "bug-reproduction-validation-failed", "bug reproduction receipt did not pass", {"validation": validation}
        )
    return validation


def require_hypothesis_ledger_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("ledgerStatus") != "PASS":
        raise LifecycleError(
            "bug-hypothesis-ledger-validation-failed", "bug hypothesis ledger did not pass", {"validation": validation}
        )
    return validation


def require_regression_proof_pass(validation: dict[str, Any]) -> dict[str, Any]:
    if validation.get("status") != "PASS" or validation.get("proofStatus") != "PASS":
        raise LifecycleError(
            "regression-proof-validation-failed", "regression proof receipt did not pass", {"validation": validation}
        )
    return validation


def _same_fingerprint_red_green(before: dict[str, Any], after: dict[str, Any]) -> bool:
    digest = before.get("fingerprintDigest")
    return (
        _is_digest(digest)
        and after.get("fingerprintDigest") == digest
        and (
            before.get("commandStatus") in REPRODUCED_COMMAND_STATUSES
            and after.get("commandStatus") in AFTER_FIX_COMMAND_STATUSES
        )
    )


def _ledger_status(hypotheses: list[dict[str, Any]], minimal_patch: dict[str, Any]) -> str:
    statuses = {item.get("status") for item in hypotheses if isinstance(item, dict)}
    return "PASS" if {"ACCEPTED", "REJECTED"}.issubset(statuses) and minimal_patch.get("status") == "PASS" else "FAIL"


def _hypothesis(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-bug-hypothesis-ledger", "hypothesis must be an object")
    return {
        "id": _required_string(value.get("id"), label="hypothesis.id", code="invalid-bug-hypothesis-ledger"),
        "status": _enum(
            value.get("status"), HYPOTHESIS_STATUSES, label="hypothesis.status", code="invalid-bug-hypothesis-ledger"
        ),
        "cause": _required_string(value.get("cause"), label="hypothesis.cause", code="invalid-bug-hypothesis-ledger"),
        "check": _required_string(value.get("check"), label="hypothesis.check", code="invalid-bug-hypothesis-ledger"),
        "result": _required_string(
            value.get("result"), label="hypothesis.result", code="invalid-bug-hypothesis-ledger"
        ),
    }


def _minimal_patch(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-bug-hypothesis-ledger", "minimalPatch must be an object")
    return {
        "status": _enum(
            value.get("status"), RECEIPT_STATUSES, label="minimalPatch.status", code="invalid-bug-hypothesis-ledger"
        ),
        "changedFiles": [
            normalize_repo_path(item, label="minimalPatch.changedFiles")
            for item in _string_list(
                value.get("changedFiles", []),
                label="minimalPatch.changedFiles",
                code="invalid-bug-hypothesis-ledger",
                allow_empty=True,
            )
        ],
        "suspectScope": [
            normalize_repo_path(item, label="minimalPatch.suspectScope")
            for item in _string_list(
                value.get("suspectScope", []),
                label="minimalPatch.suspectScope",
                code="invalid-bug-hypothesis-ledger",
                allow_empty=True,
            )
        ],
        "outsideSuspectScope": [
            normalize_repo_path(item, label="minimalPatch.outsideSuspectScope")
            for item in _string_list(
                value.get("outsideSuspectScope", []),
                label="minimalPatch.outsideSuspectScope",
                code="invalid-bug-hypothesis-ledger",
                allow_empty=True,
            )
        ],
        "justifications": list(value.get("justifications", []))
        if isinstance(value.get("justifications", []), list)
        else [],
    }


def _validate_minimal_patch(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "bug-minimal-patch-invalid"})
        return
    if value.get("status") != "PASS":
        blockers.append({"code": "bug-minimal-patch-not-pass", "status": value.get("status")})
    changed = value.get("changedFiles")
    if not isinstance(changed, list):
        blockers.append({"code": "bug-minimal-patch-changed-files-invalid"})
        changed = []
    for index, path in enumerate(changed):
        try:
            normalize_repo_path(path, label="minimalPatch.changedFiles")
        except LifecycleError as exc:
            blockers.append({"code": "bug-minimal-patch-path-invalid", "index": index, "reason": exc.code})
    outside = value.get("outsideSuspectScope", [])
    if not isinstance(outside, list):
        blockers.append({"code": "bug-minimal-patch-outside-scope-invalid"})
        outside = []
    justifications = value.get("justifications", [])
    if outside and not justifications:
        blockers.append({"code": "bug-minimal-patch-justification-missing"})
    if not isinstance(justifications, list) or not all(isinstance(item, dict) for item in justifications):
        blockers.append({"code": "bug-minimal-patch-justifications-invalid"})


def _context_budget(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-bug-forensics-profile", "contextBudget must be an object")
    for key in value:
        if key in MONEY_KEYS:
            raise LifecycleError("invalid-bug-forensics-profile", "contextBudget must not include monetary limits")
    budget = dict(value)
    budget.setdefault("budgetUnits", "tokens-and-resources")
    return dict(sorted(budget.items()))


def _validate_context_budget(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict) or not value:
        blockers.append({"code": "bug-forensics-context-budget-invalid"})
        return
    for key, item in value.items():
        if key in MONEY_KEYS:
            blockers.append({"code": "bug-forensics-context-budget-money-field", "field": key})
        elif key == "budgetUnits" and item != "tokens-and-resources":
            blockers.append({"code": "bug-forensics-context-budget-units-invalid"})
        elif key.startswith("max") and (not isinstance(item, int) or isinstance(item, bool) or item <= 0):
            blockers.append({"code": "bug-forensics-context-budget-value-invalid", "field": key})


def _cross_check_policy(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleError("invalid-bug-forensics-profile", "crossCheckPolicy must be an object")
    for key in value:
        if key in MONEY_KEYS:
            raise LifecycleError("invalid-bug-forensics-profile", "crossCheckPolicy must not include monetary limits")
    result = dict(value)
    result.setdefault("reuseSchemaVersion", CROSS_CHECK_RECEIPT_SCHEMA)
    result.setdefault("requiredByDefault", False)
    result.setdefault("blockingRequiresPlanOptIn", True)
    result.setdefault("budgetUnits", "tokens-and-resources")
    return dict(sorted(result.items()))


def _validate_cross_check_policy(value: Any, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, dict):
        blockers.append({"code": "bug-forensics-cross-check-policy-invalid"})
        return
    if value.get("reuseSchemaVersion") != CROSS_CHECK_RECEIPT_SCHEMA:
        blockers.append({"code": "bug-forensics-cross-check-schema-not-reused"})
    if value.get("requiredByDefault") is not False:
        blockers.append({"code": "bug-forensics-cross-check-required-by-default"})
    if value.get("blockingRequiresPlanOptIn") is not True:
        blockers.append({"code": "bug-forensics-cross-check-not-plan-gated"})
    if value.get("budgetUnits") != "tokens-and-resources":
        blockers.append({"code": "bug-forensics-cross-check-budget-units-invalid"})
    for key in value:
        if key in MONEY_KEYS:
            blockers.append({"code": "bug-forensics-cross-check-money-field", "field": key})


def _artifact_digests(value: list[dict[str, Any]], *, allow_empty: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise LifecycleError("invalid-artifact-digests", "artifactDigests must be an array")
    if not value and not allow_empty:
        raise LifecycleError("invalid-artifact-digests", "artifactDigests must not be empty")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise LifecycleError("invalid-artifact-digests", "artifact digest item must be an object")
        result.append(
            {
                "path": normalize_repo_path(item.get("path", ""), label="artifactDigests.path"),
                "sha256": _digest(item.get("sha256"), code="invalid-artifact-digests"),
                "bytes": _non_negative_int(item.get("bytes", 0), code="invalid-artifact-digests"),
            }
        )
    return result


def _check_artifact_digests(value: Any, blockers: list[dict[str, Any]], *, allow_empty: bool) -> None:
    if not isinstance(value, list):
        blockers.append({"code": "bug-artifact-digests-invalid"})
        return
    if not value and not allow_empty:
        blockers.append({"code": "bug-artifact-digests-missing"})
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            blockers.append({"code": "bug-artifact-digest-invalid", "index": index})
            continue
        try:
            normalize_repo_path(item.get("path", ""), label="artifactDigests.path")
        except LifecycleError as exc:
            blockers.append({"code": "bug-artifact-path-invalid", "index": index, "reason": exc.code})
        _check_digest(item.get("sha256"), "bug-artifact-digest-sha-invalid", blockers)
        bytes_value = item.get("bytes")
        if not isinstance(bytes_value, int) or isinstance(bytes_value, bool) or bytes_value < 0:
            blockers.append({"code": "bug-artifact-bytes-invalid", "index": index})


def _check_contains(value: Any, expected: tuple[str, ...], code: str, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(value, list):
        blockers.append({"code": code, "reason": "not-list"})
        return
    missing = sorted(set(expected).difference(item for item in value if isinstance(item, str)))
    if missing:
        blockers.append({"code": code, "missing": missing})


def _object(value: Any, code: str, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise LifecycleError(code, f"{label} must be a non-empty object")
    return dict(value)


def _string_list(value: Any, *, label: str, code: str, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise LifecycleError(code, f"{label} must be an array")
    if not value and not allow_empty:
        raise LifecycleError(code, f"{label} must not be empty")
    if not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(code, f"{label} must contain non-empty strings")
    return list(value)


def _check_string_list(value: Any, code: str, blockers: list[dict[str, Any]], *, allow_empty: bool) -> None:
    if not isinstance(value, list):
        blockers.append({"code": code})
        return
    if not value and not allow_empty:
        blockers.append({"code": code, "reason": "empty"})
    if not all(isinstance(item, str) and item for item in value):
        blockers.append({"code": code, "reason": "item-invalid"})


def _required_string(value: Any, *, label: str, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError(code, f"{label} must be a non-empty string")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-optional-string", "optional string must be non-empty when set")
    return value


def _enum(value: Any, allowed: set[str], *, label: str, code: str) -> str:
    if value not in allowed:
        raise LifecycleError(code, f"{label} is invalid", {"allowed": sorted(allowed), "actual": value})
    return str(value)


def _non_negative_int(value: Any, *, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise LifecycleError(code, "value must be a non-negative integer")
    return value


def _optional_digest(value: Any, *, code: str) -> str | None:
    if value is None:
        return None
    return _digest(value, code=code)


def _digest(value: Any, *, code: str) -> str:
    if not _is_digest(value):
        raise LifecycleError(code, "value must be a lowercase sha256 hex digest")
    return str(value)


def _check_digest(value: Any, code: str, blockers: list[dict[str, Any]]) -> None:
    if not _is_digest(value):
        blockers.append({"code": code})


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _without_digest(value: dict[str, Any], digest_key: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != digest_key}
