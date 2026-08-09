"""Task result and independent review validation."""

from __future__ import annotations

from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.review_verdict import validate_review_verdict


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
    _validate_attempt_baseline(task, result)
    item_outcomes = result.get("itemOutcomes")
    if not isinstance(item_outcomes, list) or not item_outcomes:
        raise LifecycleError("task-result-invalid", "task result itemOutcomes are required")
    if any(item.get("status") != "COMPLETE" for item in item_outcomes if isinstance(item, dict)):
        raise LifecycleError("task-result-not-complete", "task result has incomplete items")
    _validate_commands(result)
    if not identity["sha256"]:
        raise LifecycleError("task-result-invalid", "task result identity missing")


def _validate_attempt_baseline(task: dict[str, Any], result: dict[str, Any]) -> None:
    attempt_base = task.get("attemptBaseRevision")
    if not isinstance(attempt_base, str) or not attempt_base:
        return
    change_set = result.get("changeSet")
    if not isinstance(change_set, dict) or not isinstance(change_set.get("baselineSha"), str):
        raise LifecycleError("task-result-invalid", "task result changeSet.baselineSha is required")
    actual_base = change_set["baselineSha"]
    if actual_base == attempt_base:
        return
    reconciliation = result.get("reconciliationReceipt")
    if not _valid_reconciliation(reconciliation, task=task, expected=attempt_base, actual=actual_base):
        raise LifecycleError(
            "task-result-stale-baseline",
            "task result baseline does not match attempt base revision",
            {"expectedBaseRevision": attempt_base, "actualBaseRevision": actual_base},
        )


def _valid_reconciliation(
    value: Any,
    *,
    task: dict[str, Any],
    expected: str,
    actual: str,
) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schemaVersion") == "agent-baseline-reconciliation-receipt.v1"
        and value.get("status") == "PASS"
        and value.get("taskId") == task.get("id")
        and value.get("attempt") == task.get("attempt")
        and value.get("expectedBaseRevision") == expected
        and value.get("actualBaseRevision") == actual
        and isinstance(value.get("evidenceIds"), list)
        and bool(value.get("evidenceIds"))
        and all(isinstance(item, str) and item for item in value.get("evidenceIds", []))
    )


def _validate_commands(result: dict[str, Any]) -> None:
    commands = result.get("commands")
    if commands is None:
        return
    if not isinstance(commands, list):
        raise LifecycleError("task-result-invalid", "task result commands must be an array")
    failed = []
    for command in commands:
        if not isinstance(command, dict):
            raise LifecycleError("task-result-invalid", "task result command entries must be objects")
        status = command.get("status")
        exit_code = command.get("exitCode")
        if status in {"FAIL", "FAILED"} or (isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0):
            failed.append(command.get("id") or command.get("command") or "<unknown>")
    if failed:
        raise LifecycleError(
            "task-result-failed-command",
            "task result cannot report completion over failed commands",
            {"commands": failed},
        )


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
    structured_verdict = review.get("reviewVerdict")
    if structured_verdict is not None:
        validation = validate_review_verdict(structured_verdict, findings=findings)
        if validation["status"] == "FAIL":
            raise LifecycleError("task-review-verdict-invalid", "task review structured verdict is invalid", {"validation": validation})
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
