"""Final-proof integration for proof-integrity receipts."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts.proof_validation import (
    require_proof_integrity_pass,
    validate_proof_integrity_receipt,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest


def proof_integrity_required(state: dict[str, Any], final_audit: dict[str, Any] | None = None) -> bool:
    """Return whether the current run explicitly requires proof-integrity evidence."""

    policy = state.get("proofIntegrityPolicy")
    if state.get("proofIntegrityRequired") is True:
        return True
    if isinstance(policy, dict) and policy.get("mode") in {"required", "bug-forensics", "strict"}:
        return True
    if isinstance(final_audit, dict):
        if final_audit.get("proofIntegrityRequired") is True:
            return True
        evidence = final_audit.get("proofIntegrityEvidence")
        if isinstance(evidence, dict) and evidence.get("required") is True:
            return True
    return False


def validate_final_proof_integrity(
    *,
    state: dict[str, Any],
    final_audit: dict[str, Any],
    receipt: dict[str, Any] | None,
    final_proof: dict[str, Any] | None = None,
    required: bool | None = None,
    new_run: bool = True,
) -> dict[str, Any] | None:
    """Validate optional final-proof integrity evidence and fail closed when required."""

    must_validate = proof_integrity_required(state, final_audit) if required is None else required
    if receipt is None:
        if must_validate:
            raise LifecycleError(
                "proof-integrity-receipt-missing",
                "final proof requires proof-integrity receipt",
            )
        return None
    validation = validate_proof_integrity_receipt(
        receipt,
        state=state,
        final_audit=final_audit,
        final_proof=final_proof,
        new_run=new_run,
    )
    require_proof_integrity_pass(validation)
    if isinstance(final_proof, dict) and isinstance(final_proof.get("proofIntegrity"), dict):
        _validate_embedded_identity(final_proof["proofIntegrity"], receipt)
    return validation


def _validate_embedded_identity(proof_integrity: dict[str, Any], receipt: dict[str, Any]) -> None:
    receipt_identity = proof_integrity.get("receipt")
    if not isinstance(receipt_identity, dict):
        raise LifecycleError("proof-integrity-final-proof-mismatch", "final proof proofIntegrity.receipt must be an object")
    if receipt_identity.get("sha256") != canonical_digest(receipt):
        raise LifecycleError("proof-integrity-final-proof-mismatch", "final proof proofIntegrity receipt digest mismatch")
    validation = proof_integrity.get("validation")
    if not isinstance(validation, dict) or validation.get("receiptDigest") != receipt.get("receiptDigest"):
        raise LifecycleError("proof-integrity-final-proof-mismatch", "final proof proofIntegrity validation mismatch")


__all__ = ["proof_integrity_required", "validate_final_proof_integrity"]
