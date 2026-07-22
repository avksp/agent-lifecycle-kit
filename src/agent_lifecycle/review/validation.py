"""Validate independent review envelopes."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError


def validate_independent_review(review: dict[str, Any]) -> dict[str, Any]:
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("independent") is not True:
        raise LifecycleError("review-not-independent", "reviewer must be independent")
    verdict = review.get("verdict")
    if verdict not in {"READY_TO_FREEZE", "ACCEPTED", "CHANGES_REQUIRED", "BLOCKED"}:
        raise LifecycleError("invalid-review", "review verdict is invalid")
    findings = review.get("findings", [])
    if not isinstance(findings, list):
        raise LifecycleError("invalid-review", "findings must be an array")
    open_blocking = [
        item.get("id")
        for item in findings
        if isinstance(item, dict)
        and item.get("status") == "open"
        and item.get("severity") in {"BLOCKER", "HIGH", "MEDIUM"}
    ]
    if verdict in {"READY_TO_FREEZE", "ACCEPTED"} and open_blocking:
        raise LifecycleError("review-open-findings", "review has unresolved blocking findings")
    return {"schemaVersion": "agent-review-validation.v1", "verdict": verdict, "openBlocking": open_blocking}
