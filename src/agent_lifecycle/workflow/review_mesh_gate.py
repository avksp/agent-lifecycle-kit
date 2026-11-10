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
from agent_lifecycle.contracts.review_remedy_schemas import closed, remedy_error, remedy_policy
from agent_lifecycle.review_mesh.remediation import (
    current_remedy_results,
    evidence_value,
    load_remedy_evidence,
    validate_remedy_native_chain,
)
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
    trusted_context: dict[str, Any] | None = None,
    remedy_evidence: dict[str, Any] | None = None,
    trusted_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required = review_mesh_required(config, phase=phase)
    blockers: list[dict[str, Any]] = []
    try:
        policy = remedy_policy(config, phase=phase)
        if policy is not None and policy["mode"] == "required":
            _required_remedy_gate(receipt, policy, config or {}, trusted_context, remedy_evidence, trusted_delta)
    except LifecycleError as exc:
        blockers.append({"code": exc.code, "message": exc.message})
    requirement = independence_requirement
    if requirement is None and isinstance(config, dict) and isinstance(config.get("independenceRequirement"), dict):
        requirement = config["independenceRequirement"]
    independence_validation, independence_blockers = _gate_independence(
        requirement, receipt, independent_evidence, phase=phase
    )
    blockers.extend(independence_blockers)
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
    trusted_context: dict[str, Any] | None = None,
    trusted_delta: dict[str, Any] | None = None,
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
            trusted_context=trusted_context,
        )
    receipt_rel = normalize_repo_path(receipt_path, label="review mesh quorum receipt")
    receipt = read_json_object(root / receipt_rel, label="review mesh quorum receipt")
    evidence = None
    if receipt.get("schemaVersion") == "agent-review-mesh-quorum-receipt.v2":
        evidence_ref = receipt.get("remedy", {}).get("evidenceBundle", {})
        evidence = load_remedy_evidence(root, evidence_ref.get("path", ""))
    return validate_review_mesh_quorum_gate(
        phase=phase,
        config=config,
        receipt=receipt,
        receipt_identity=artifact_identity(root, receipt_rel, receipt),
        independence_requirement=independence_requirement,
        independent_evidence=independent_evidence,
        trusted_context=trusted_context,
        remedy_evidence=evidence,
        trusted_delta=trusted_delta,
    )


def _required_remedy_gate(
    receipt: dict[str, Any] | None,
    policy: dict[str, Any],
    config: dict[str, Any],
    context: dict[str, Any] | None,
    bundle: dict[str, Any] | None,
    delta: dict[str, Any] | None,
) -> None:
    from agent_lifecycle.review_mesh.contracts import require_review_mesh_profile_pass, validate_review_mesh_profile
    from agent_lifecycle.review_mesh.synthesis import synthesize_review_mesh_results

    if receipt is None or receipt.get("schemaVersion") != "agent-review-mesh-quorum-receipt.v2":
        raise remedy_error("required remedy needs a v2 quorum chain")
    section = closed(
        receipt.get("remedy"),
        {
            "synthesisDigest",
            "policyDigest",
            "responseContractDigest",
            "decisionsDigest",
            "evidenceBundle",
            "recheckDigests",
        },
        "quorum remedy",
    )
    if context is None or bundle is None:
        raise remedy_error("required remedy needs trusted native context and bounded evidence")
    profile = receipt.get("subject", {}).get("reviewMeshProfile")
    if not isinstance(profile, dict) or profile.get("remedyProfile") != policy:
        raise remedy_error("quorum profile differs from the frozen required policy")
    require_review_mesh_profile_pass(validate_review_mesh_profile(profile))
    decisions = evidence_value(bundle, "decision", section["decisionsDigest"])
    results = current_remedy_results(bundle, decisions)
    synthesis = synthesize_review_mesh_results(
        profile=profile, results=results, remedy_decisions=decisions, remedy_evidence=bundle
    )
    if synthesis["subject"] != receipt["subject"] or synthesis["unresolvedFindings"]:
        raise remedy_error("quorum subject differs or mandatory findings remain unresolved")
    minimum = config.get("quorumPolicy", {}).get("minReviewers", len(policy["roleScopes"]))
    if type(minimum) is not int or receipt.get("reviewerCount", -1) < minimum:
        raise remedy_error("CLI quorum cannot lower frozen reviewer minimum")
    validate_remedy_native_chain(profile, synthesis, receipt, bundle, context, trusted_delta=delta)
    roles = {result["reviewer"]["role"] for result in results}
    required_roles = set(config.get("quorumPolicy", {}).get("requiredRoles", config.get("requiredRoles", [])))
    if section["recheckDigests"] and context["phase"] != "final-audit":
        required_roles -= {scope["role"] for scope in policy["roleScopes"]}
    if not required_roles.issubset(roles):
        raise remedy_error("qualified reviewers do not cover frozen required roles")


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


def _gate_independence(
    requirement: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    independent_evidence: list[dict[str, Any]] | None,
    *,
    phase: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
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
                validation = _gate_independent_evidence(evidence, requirement, receipt)
                independence_validation.append(validation)
                if requirement.get("required") is True and validation["status"] != "PASS":
                    blockers.append({"code": "review-mesh-independent-evidence-invalid", "validation": validation})
            if requirement.get("required") is True and not any(
                item.get("independenceStatus") == "REQUIRED_PASS" for item in independence_validation
            ):
                blockers.append({"code": "review-mesh-independent-evidence-required", "phase": phase})
    return independence_validation, blockers


def _gate_independent_evidence(
    evidence: dict[str, Any], requirement: dict[str, Any], receipt: dict[str, Any] | None
) -> dict[str, Any]:
    subject = receipt.get("subject", {}) if isinstance(receipt, dict) else {}
    subject = subject if isinstance(subject, dict) else {}
    return validate_independent_evidence(
        evidence,
        requirement=requirement,
        expected_source_revision=subject.get("sourceRevision"),
        expected_source_lineage_digest=subject.get("sourceLineageDigest"),
        primary_producer_class=subject.get("primaryProducerClass"),
        primary_implementation_digest=subject.get("primaryImplementationDigest"),
    )
