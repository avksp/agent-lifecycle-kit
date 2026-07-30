"""Observable completion contract validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.paths import normalize_repo_path

CHECK_KINDS = {"verification", "external-action"}


def validate_completion_check(check: dict[str, Any]) -> dict[str, Any]:
    """Validate an optional specification-level completion check."""

    if not isinstance(check, dict):
        raise LifecycleError("invalid-completion-check", "completionCheck must be an object")
    if check.get("schemaVersion") != "agent-completion-check.v1":
        raise LifecycleError("invalid-completion-check", "completionCheck schemaVersion is unsupported")
    check_id = _required_string(check.get("checkId"), label="completionCheck.checkId")
    kind = check.get("kind")
    if kind not in CHECK_KINDS:
        raise LifecycleError("invalid-completion-check", "completionCheck kind is unsupported")
    _required_string(check.get("description"), label="completionCheck.description")
    receipt_path = normalize_repo_path(check.get("receiptPath"), label="completion check receipt")
    evidence_ids = _string_list(
        check.get("requiredEvidenceIds"),
        label="completionCheck.requiredEvidenceIds",
        error_code="invalid-completion-check",
    )
    if not evidence_ids:
        raise LifecycleError("invalid-completion-check", "completionCheck requiredEvidenceIds are required")
    return {
        "schemaVersion": "agent-completion-check-validation.v1",
        "checkId": check_id,
        "kind": kind,
        "receiptPath": receipt_path,
        "requiredEvidenceIds": evidence_ids,
        "checkDigest": canonical_digest(check),
    }


def validate_completion_check_receipt(
    receipt: dict[str, Any],
    *,
    check: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    """Validate a finalization receipt against the declared completion check."""

    check_validation = validate_completion_check(check)
    if not isinstance(receipt, dict):
        raise LifecycleError("completion-check-receipt-required", "completion check receipt must be an object")
    if receipt.get("schemaVersion") != "agent-completion-check-receipt.v1":
        raise LifecycleError("invalid-completion-check-receipt", "completion check receipt schemaVersion is unsupported")
    if receipt.get("checkId") != check_validation["checkId"]:
        raise LifecycleError("completion-check-receipt-mismatch", "completion check receipt checkId mismatch")
    status = receipt.get("status")
    if status == "FAIL":
        raise LifecycleError("completion-check-not-satisfied", "completion check receipt reports FAIL")
    if status != "PASS":
        raise LifecycleError("invalid-completion-check-receipt", "completion check receipt status is unsupported")
    _require_lineage(receipt, state)
    evidence_ids = _string_list(
        receipt.get("evidenceIds"),
        label="completionCheckReceipt.evidenceIds",
        error_code="invalid-completion-check-receipt",
    )
    missing_evidence = sorted(set(check_validation["requiredEvidenceIds"]) - set(evidence_ids))
    if missing_evidence:
        raise LifecycleError(
            "completion-check-evidence-missing",
            "completion check receipt is missing required evidence",
            {"evidenceIds": missing_evidence},
        )
    verifier = receipt.get("verifier")
    if not isinstance(verifier, dict) or not isinstance(verifier.get("id"), str) or not verifier["id"]:
        raise LifecycleError("invalid-completion-check-receipt", "completion check receipt verifier.id is required")
    if check_validation["kind"] == "external-action":
        _validate_external_action_binding(receipt, state)
    return {
        "schemaVersion": "agent-completion-check-receipt-validation.v1",
        "status": "PASS",
        "checkId": check_validation["checkId"],
        "checkKind": check_validation["kind"],
        "evidenceIds": evidence_ids,
        "receiptDigest": canonical_digest(receipt),
        "checkDigest": check_validation["checkDigest"],
    }


def _require_lineage(receipt: dict[str, Any], state: dict[str, Any]) -> None:
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LifecycleError("completion-check-lineage-mismatch", f"completion check receipt {key} mismatch")


def _validate_external_action_binding(receipt: dict[str, Any], state: dict[str, Any]) -> None:
    expected = state.get("externalActionReceipt")
    if not isinstance(expected, dict):
        raise LifecycleError(
            "completion-check-external-action-missing",
            "external-action completion check requires an externalActionReceipt in workflow state",
        )
    actual = receipt.get("externalActionReceipt")
    if not isinstance(actual, dict):
        raise LifecycleError(
            "completion-check-external-action-missing",
            "completion check receipt must bind externalActionReceipt",
        )
    for key in ("path", "sha256", "bytes"):
        if actual.get(key) != expected.get(key):
            raise LifecycleError(
                "completion-check-external-action-mismatch",
                f"completion check externalActionReceipt {key} mismatch",
            )


def _required_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("invalid-completion-check", f"{label} is required")
    return value


def _string_list(value: Any, *, label: str, error_code: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError(error_code, f"{label} must be a list of non-empty strings")
    return value
