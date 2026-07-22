"""Task result and independent review validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError


def validate_task_result(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    identity: dict[str, Any],
) -> None:
    expected = {
        "schemaVersion": "agent-task-result.v2",
        "runId": state.get("runId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise LifecycleError(
                "task-result-lineage-mismatch",
                f"task result {key} mismatch",
            )
    packet = task.get("packet")
    if isinstance(packet, dict) and result.get("taskPacketHash") != packet.get("sha256"):
        raise LifecycleError(
            "task-result-lineage-mismatch",
            "task result packet hash mismatch",
        )
    if result.get("blocker") is not None or result.get("contractChangeRequest") is not None:
        raise LifecycleError(
            "task-result-not-acceptable",
            "blocking task result cannot enter review acceptance path",
        )
    item_outcomes = result.get("itemOutcomes")
    if not isinstance(item_outcomes, list) or not item_outcomes:
        raise LifecycleError("task-result-invalid", "task result itemOutcomes are required")
    if any(item.get("status") != "COMPLETE" for item in item_outcomes if isinstance(item, dict)):
        raise LifecycleError("task-result-not-complete", "task result has incomplete items")
    if not identity["sha256"]:
        raise LifecycleError("task-result-invalid", "task result identity missing")


def validate_task_review(
    state: dict[str, Any],
    task: dict[str, Any],
    review: dict[str, Any],
) -> None:
    result = task.get("result")
    if not isinstance(result, dict):
        raise LifecycleError("missing-task-result", "task review requires committed result")
    expected = {
        "schemaVersion": "agent-task-review.v2",
        "runId": state.get("runId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "resultHash": result.get("sha256"),
    }
    for key, value in expected.items():
        if review.get(key) != value:
            raise LifecycleError(
                "task-review-lineage-mismatch",
                f"task review {key} mismatch",
            )
    packet = task.get("packet")
    if isinstance(packet, dict) and review.get("taskPacketHash") != packet.get("sha256"):
        raise LifecycleError(
            "task-review-lineage-mismatch",
            "task review packet hash mismatch",
        )
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("independent") is not True:
        raise LifecycleError("task-review-not-independent", "task review must be independent")
    if review.get("verdict") != "ACCEPTED":
        raise LifecycleError("task-review-not-accepted", "task review verdict is not ACCEPTED")
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise LifecycleError("task-review-invalid", "task review findings must be an array")
    open_medium_plus = [
        finding.get("id")
        for finding in findings
        if isinstance(finding, dict)
        and finding.get("status") == "open"
        and finding.get("severity") in {"BLOCKER", "HIGH", "MEDIUM"}
    ]
    if open_medium_plus:
        raise LifecycleError(
            "task-review-open-findings",
            "task review has unresolved MEDIUM+ findings",
            {"findings": open_medium_plus},
        )
