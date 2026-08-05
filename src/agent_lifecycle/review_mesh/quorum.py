"""Review Mesh quorum receipt helpers."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.review_mesh.contracts import (
    build_review_mesh_quorum_receipt,
    require_review_mesh_quorum_pass,
    validate_review_mesh_quorum_receipt,
)


def build_quorum_from_synthesis(
    *,
    profile: dict[str, Any],
    synthesis: dict[str, Any],
    quorum_policy: dict[str, Any],
    reviewer_roles: list[str] | None = None,
) -> dict[str, Any]:
    """Build and validate a quorum receipt from synthesized Review Mesh evidence."""

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
    )
    if receipt.get("status") == "PASS":
        require_review_mesh_quorum_pass(validate_review_mesh_quorum_receipt(receipt, profile=profile))
    return receipt
