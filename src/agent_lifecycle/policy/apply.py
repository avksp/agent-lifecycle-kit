"""Explicit write path for approved lifecycle policy proposals."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create

APPLY_RESULT_SCHEMA = "agent-lifecycle-policy-apply-result.v1"
TUNED_POLICY_SCHEMA = "agent-lifecycle-tuned-policy.v1"


def build_tuned_policy(proposal: dict[str, Any]) -> dict[str, Any]:
    if proposal.get("applyAllowed") is not True:
        raise LifecycleError("policy-apply-not-allowed", "policy proposal is not safe to apply", {"proposal": proposal})
    changes = [item for item in proposal.get("candidateChanges", []) if isinstance(item, dict) and item.get("applies") is True]
    body = {
        "schemaVersion": TUNED_POLICY_SCHEMA,
        "status": "PASS",
        "sourceProposalDigest": proposal.get("proposalDigest") or canonical_digest(proposal),
        "changes": changes,
        "rollback": proposal.get("rollback"),
        "qualityConstraints": proposal.get("qualityConstraints"),
        "productionPromotionClaimed": False,
    }
    return {**body, "policyDigest": canonical_digest(body)}


def apply_policy_proposal(proposal: dict[str, Any], output_path: Path) -> dict[str, Any]:
    policy = build_tuned_policy(proposal)
    payload = write_json_create(output_path, policy)
    body = {
        "schemaVersion": APPLY_RESULT_SCHEMA,
        "status": "PASS",
        "outputPath": output_path.as_posix(),
        "outputBytes": len(payload),
        "outputDigest": canonical_digest(policy),
        "proposalDigest": proposal.get("proposalDigest") or canonical_digest(proposal),
        "changed": bool(policy["changes"]),
        "liveCallsStarted": False,
        "productionPromotionClaimed": False,
    }
    return {**body, "applyDigest": canonical_digest(body)}
