"""Workflow gate helpers for optional Review Mesh quorum evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.independent_evidence_schemas import (
    validate_independence_requirement,
    validate_independent_evidence,
)
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.workflow.artifacts import artifact_identity


def review_mesh_required(config: dict[str, Any] | None, *, phase: str) -> bool:
    if not isinstance(config, dict) or config.get("required") is not True:
        return False
    phases = config.get("phases", [])
    return not isinstance(phases, list) or not phases or phase in phases


def validate_review_mesh_quorum_gate(
    *,
    phase: str,
    config: dict[str, Any] | None,
    receipt: dict[str, Any] | None = None,
    receipt_identity: dict[str, Any] | None = None,
    independence_requirement: dict[str, Any] | None = None,
    independent_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    required = review_mesh_required(config, phase=phase)
    blockers: list[dict[str, Any]] = []
    requirement = independence_requirement
    if requirement is None and isinstance(config, dict) and isinstance(config.get("independenceRequirement"), dict):
        requirement = config["independenceRequirement"]
    independence_validation: list[dict[str, Any]] = []
    if requirement is not None:
        requirement_validation = validate_independence_requirement(requirement)
        if requirement_validation["status"] != "PASS":
            blockers.append(
                {"code": "review-mesh-independence-requirement-invalid", "validation": requirement_validation}
            )
        else:
            values = independent_evidence
            if values is None and isinstance(receipt, dict) and isinstance(receipt.get("independentEvidence"), list):
                values = receipt["independentEvidence"]
            values = list(values or [])
            for evidence in values:
                validation = validate_independent_evidence(
                    evidence,
                    requirement=requirement,
                    expected_source_revision=receipt.get("subject", {}).get("sourceRevision")
                    if isinstance(receipt, dict) and isinstance(receipt.get("subject"), dict)
                    else None,
                    expected_source_lineage_digest=receipt.get("subject", {}).get("sourceLineageDigest")
                    if isinstance(receipt, dict) and isinstance(receipt.get("subject"), dict)
                    else None,
                    primary_producer_class=receipt.get("subject", {}).get("primaryProducerClass")
                    if isinstance(receipt, dict) and isinstance(receipt.get("subject"), dict)
                    else None,
                    primary_implementation_digest=receipt.get("subject", {}).get("primaryImplementationDigest")
                    if isinstance(receipt, dict) and isinstance(receipt.get("subject"), dict)
                    else None,
                )
                independence_validation.append(validation)
                if requirement.get("required") is True and validation["status"] != "PASS":
                    blockers.append({"code": "review-mesh-independent-evidence-invalid", "validation": validation})
            if requirement.get("required") is True and not any(
                item.get("independenceStatus") == "REQUIRED_PASS" for item in independence_validation
            ):
                blockers.append({"code": "review-mesh-independent-evidence-required", "phase": phase})
    if receipt is None:
        if required:
            blockers.append({"code": "review-mesh-quorum-receipt-missing", "phase": phase})
        return _gate_receipt(
            phase=phase,
            required=required,
            receipt_identity=receipt_identity,
            blockers=blockers,
            independence=independence_validation,
        )
    from agent_lifecycle.review_mesh.contracts import validate_review_mesh_quorum_receipt

    validation = validate_review_mesh_quorum_receipt(receipt)
    if validation["status"] != "PASS":
        blockers.append({"code": "review-mesh-quorum-validation-failed", "validation": validation})
    if required:
        expected_profile_digest = config.get("profileDigest") if isinstance(config, dict) else None
        if expected_profile_digest and receipt.get("profileDigest") != expected_profile_digest:
            blockers.append({"code": "review-mesh-quorum-profile-digest-mismatch"})
        if receipt.get("status") != "PASS" or receipt.get("quorumSatisfied") is not True:
            blockers.append({"code": "review-mesh-quorum-not-satisfied", "receiptStatus": receipt.get("status")})
    return _gate_receipt(
        phase=phase,
        required=required,
        receipt_identity=receipt_identity,
        blockers=blockers,
        validation=validation,
        independence=independence_validation,
    )


def require_review_mesh_quorum_gate_pass(gate: dict[str, Any]) -> dict[str, Any]:
    if gate.get("status") == "FAIL":
        raise LifecycleError(
            "review-mesh-quorum-required", "required Review Mesh quorum evidence is missing or failed", {"gate": gate}
        )
    return gate


def validate_review_mesh_quorum_path(
    *,
    root: Path,
    phase: str,
    config: dict[str, Any] | None,
    receipt_path: str | None,
    independence_requirement: dict[str, Any] | None = None,
    independent_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if receipt_path is None:
        configured = config.get("quorumReceiptPath") if isinstance(config, dict) else None
        receipt_path = configured if isinstance(configured, str) and configured else None
    if receipt_path is None:
        return validate_review_mesh_quorum_gate(
            phase=phase,
            config=config,
            independence_requirement=independence_requirement,
            independent_evidence=independent_evidence,
        )
    receipt_rel = normalize_repo_path(receipt_path, label="review mesh quorum receipt")
    receipt = read_json_object(root / receipt_rel, label="review mesh quorum receipt")
    return validate_review_mesh_quorum_gate(
        phase=phase,
        config=config,
        receipt=receipt,
        receipt_identity=artifact_identity(root, receipt_rel, receipt),
        independence_requirement=independence_requirement,
        independent_evidence=independent_evidence,
    )


def _gate_receipt(
    *,
    phase: str,
    required: bool,
    receipt_identity: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    validation: dict[str, Any] | None = None,
    independence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    body = {
        "schemaVersion": "agent-review-mesh-gate-validation.v1",
        "status": "FAIL" if blockers else "PASS",
        "phase": phase,
        "required": required,
        "receipt": receipt_identity,
        "validation": validation,
        "independence": list(independence or []),
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}
