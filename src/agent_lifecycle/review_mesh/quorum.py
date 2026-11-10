"""Review Mesh quorum receipt helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.review_remedy_schemas import remedy_error
from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_quorum_receipt,
    require_review_mesh_quorum_pass,
    validate_review_mesh_quorum_receipt,
)
from agent_lifecycle.review_mesh.remediation import evidence_values, remedy_quorum_inputs


def build_quorum_from_synthesis(
    *,
    profile: dict[str, Any],
    synthesis: dict[str, Any],
    quorum_policy: dict[str, Any],
    reviewer_roles: list[str] | None = None,
    independence_requirement: dict[str, Any] | None = None,
    independent_evidence: list[dict[str, Any]] | None = None,
    remedy_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate a quorum receipt from synthesized Review Mesh evidence."""

    opted = "remedyProfile" in profile
    remedy_section: dict[str, Any] = {}
    if opted:
        if remedy_evidence is None:
            raise remedy_error("v2 quorum requires exact qualified remedy evidence")
        inputs = remedy_quorum_inputs(profile, synthesis, remedy_evidence)
        reviewer_roles = inputs["roles"]
        rechecks = evidence_values(remedy_evidence, "recheck")
        mandatory = (
            sorted({role for item in rechecks for role in item["requiredRoles"]})
            if rechecks
            else [scope["role"] for scope in profile["remedyProfile"]["roleScopes"]]
        )
        quorum_policy = {
            **quorum_policy,
            "requiredRoles": sorted(set(quorum_policy.get("requiredRoles", []) + mandatory)),
        }
        remedy_section = {
            "synthesisDigest": synthesis["synthesisDigest"],
            "policyDigest": profile["remedyProfile"]["policyDigest"],
            "responseContractDigest": synthesis["remedy"]["responseContractDigest"],
            "decisionsDigest": synthesis["remedy"]["decisionsDigest"],
            "evidenceBundle": remedy_evidence["reference"],
            "recheckDigests": sorted(item["recheckDigest"] for item in evidence_values(remedy_evidence, "recheck")),
        }
    result_count = len(synthesis.get("resultDigests", [])) if isinstance(synthesis.get("resultDigests"), list) else 0
    required_roles = quorum_policy.get("requiredRoles", []) if isinstance(quorum_policy, dict) else []
    roles = set(reviewer_roles or [])
    roles_satisfied = all(role in roles for role in required_roles) if isinstance(required_roles, list) else False
    receipt = build_review_mesh_quorum_receipt(
        profile=profile,
        mode=synthesis["mode"],
        subject=synthesis.get("subject", {}),
        quorum_policy=quorum_policy,
        reviewer_count=result_count,
        required_roles_satisfied=roles_satisfied,
        blocking_findings_unresolved=bool(synthesis.get("unresolvedFindings")),
        independence_requirement=independence_requirement,
        independent_evidence=independent_evidence,
    )
    if opted:
        receipt["schemaVersion"] = "agent-review-mesh-quorum-receipt.v2"
        receipt["remedy"] = remedy_section
        receipt["receiptDigest"] = canonical_digest(
            {key: item for key, item in receipt.items() if key != "receiptDigest"}
        )
    if receipt.get("status") == "PASS":
        require_review_mesh_quorum_pass(validate_review_mesh_quorum_receipt(receipt, profile=profile))
    return receipt
