"""Validate independent review envelopes."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_text import require_review_text
from agent_lifecycle.contracts.review_verdict import open_blocking_finding_ids
from agent_lifecycle.review.provenance import validate_native_reviewer_provenance


def require_supported_review_provenance(review: dict[str, Any], *, native_phase: str) -> None:
    """Keep ordinary declarations; refuse caller-supplied native authority."""
    candidates = [review]
    if "auditor" in review:
        candidates.append({**review, "reviewer": review["auditor"]})
    for candidate in candidates:
        validation = validate_native_reviewer_provenance(candidate, native_phase=native_phase)
        if validation["status"] == "FAIL" or (
            "reviewerProvenance" in review and review["reviewerProvenance"] is None
        ):
            raise LifecycleError(
                "review-provenance-invalid", "review provenance claim is malformed or unverified",
                {"validation": validation},
            )
    supplied = review.get("reviewerProvenance")
    if isinstance(supplied, dict) and supplied.get("guarantee") == "ATTESTED":
        raise LifecycleError(
            "review-provenance-unsupported", "native ATTESTED reviewer provenance is unavailable",
            {"validation": validation},
        )


def validate_independent_review(review: dict[str, Any]) -> dict[str, Any]:
    require_review_text(review)
    require_supported_review_provenance(review, native_phase="freeze")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("independent") is not True:
        raise LifecycleError("review-not-independent", "reviewer must be independent")
    verdict = review.get("verdict")
    if verdict not in {"READY_TO_FREEZE", "ACCEPTED", "CHANGES_REQUIRED", "BLOCKED"}:
        raise LifecycleError("invalid-review", "review verdict is invalid")
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        raise LifecycleError("invalid-review", "findings must be an array")
    open_blocking = open_blocking_finding_ids(findings)
    if verdict in {"READY_TO_FREEZE", "ACCEPTED"} and open_blocking:
        raise LifecycleError("review-open-findings", "review has unresolved blocking findings")
    return {"schemaVersion": "agent-review-validation.v1", "verdict": verdict, "openBlocking": open_blocking}
