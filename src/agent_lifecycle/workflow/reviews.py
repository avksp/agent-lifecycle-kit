"""Task result and independent review validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.changesets import capture_task_change_set, require_current_task_change_set
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.review_verdict import validate_review_verdict
from agent_lifecycle.workflow.artifacts import require_artifact_identity


def _read_committed_result(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    result_identity = task.get("result")
    if not isinstance(result_identity, dict) or not isinstance(result_identity.get("path"), str):
        raise LifecycleError("missing-task-result", "task acceptance requires committed result")
    return require_artifact_identity(root, result_identity, label="task result")


def task_result_freshness_required(state: dict[str, Any]) -> bool:
    """Return whether state is bound to a complete adopted packet set."""

    packet_set = state.get("packetSet")
    return isinstance(packet_set, dict) and all(
        isinstance(packet_set.get(key), str) and packet_set[key]
        for key in ("manifestDigest", "packetSetHash", "planLockSha256")
    )


def validate_task_result(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    identity: dict[str, Any],
    *,
    repository_root: Path | None = None,
    require_freshness: bool = False,
    allow_non_accepting_outcome: bool = False,
) -> dict[str, Any] | None:
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
    if not allow_non_accepting_outcome and (
        result.get("blocker") is not None or result.get("contractChangeRequest") is not None
    ):
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
    if repository_root is None:
        if require_freshness:
            raise LifecycleError("task-result-freshness-context-missing", "repository root is required")
        return None
    change_set = result.get("changeSet")
    if not require_freshness and (not isinstance(change_set, dict) or change_set.get("provider") != "git-worktree-v2"):
        return None
    evidence = capture_task_change_set(
        repository_root,
        baseline=str(state.get("sourceRevision") or ""),
        write_paths=[path for path in task.get("writes", []) if isinstance(path, str)],
    )
    require_current_task_change_set(result, evidence)
    return evidence


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
        if status in {"FAIL", "FAILED"} or (
            isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0
        ):
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
    *,
    result: dict[str, Any] | None = None,
) -> None:
    _validate_review_lineage(state, task, review)
    if result is not None:
        _require_reviewer_separate_from_worker(review, result)
    if review.get("verdict") != "ACCEPTED":
        raise LifecycleError("task-review-not-accepted", "task review verdict is not ACCEPTED")
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise LifecycleError("task-review-invalid", "task review findings must be an array")
    structured_verdict = review.get("reviewVerdict")
    if structured_verdict is not None:
        validation = validate_review_verdict(structured_verdict, findings=findings)
        if validation["status"] == "FAIL":
            raise LifecycleError(
                "task-review-verdict-invalid", "task review structured verdict is invalid", {"validation": validation}
            )
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


def validate_task_rework_review(
    state: dict[str, Any],
    task: dict[str, Any],
    review: dict[str, Any],
    *,
    result: dict[str, Any],
) -> None:
    """Validate review lineage and independence for a remediation decision."""

    _validate_review_lineage(state, task, review)
    _require_reviewer_separate_from_worker(review, result)
    if review.get("verdict") not in {"ACCEPTED", "REWORK"}:
        raise LifecycleError("task-review-not-rework-compatible", "task rework review must be ACCEPTED or REWORK")
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise LifecycleError("task-review-invalid", "task review findings must be an array")


def validate_task_outcome_review(
    state: dict[str, Any],
    task: dict[str, Any],
    review: dict[str, Any],
    *,
    result: dict[str, Any],
) -> str:
    """Validate the common lineage boundary for every task review outcome."""

    _validate_review_lineage(state, task, review)
    _require_reviewer_separate_from_worker(review, result)
    verdict = review.get("verdict")
    if verdict not in {"ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"}:
        raise LifecycleError("task-review-verdict-invalid", "task review verdict is unsupported")
    findings = review.get("findings")
    if not isinstance(findings, list):
        raise LifecycleError("task-review-invalid", "task review findings must be an array")
    if verdict == "BLOCKED" and not isinstance(review.get("blocker"), dict):
        raise LifecycleError("task-review-blocker-required", "BLOCKED review requires a typed blocker")
    if verdict == "CONTRACT_CHANGE" and not isinstance(review.get("contractChangeRequest"), dict):
        raise LifecycleError(
            "task-review-contract-change-required",
            "CONTRACT_CHANGE review requires a typed contract change request",
        )
    return verdict


def open_finding_ids(value: dict[str, Any]) -> set[str]:
    findings = value.get("findings")
    if not isinstance(findings, list):
        return set()
    return {
        str(finding["id"])
        for finding in findings
        if isinstance(finding, dict)
        and isinstance(finding.get("id"), str)
        and finding["id"]
        and finding.get("status") == "open"
    }


def _validate_review_lineage(
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
            raise LifecycleError("task-review-lineage-mismatch", f"task review {key} mismatch")
    packet = task.get("packet")
    if isinstance(packet, dict) and review.get("taskPacketHash") != packet.get("sha256"):
        raise LifecycleError("task-review-lineage-mismatch", "task review packet hash mismatch")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("independent") is not True:
        raise LifecycleError("task-review-not-independent", "task review must be independent")


def _require_reviewer_separate_from_worker(review: dict[str, Any], result: dict[str, Any]) -> None:
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        raise LifecycleError("task-review-not-independent", "task review must identify an independent reviewer")
    same_actor = isinstance(result.get("actor"), str) and result["actor"] and reviewer.get("id") == result["actor"]
    same_run = (
        isinstance(result.get("actorRunId"), str)
        and result["actorRunId"]
        and reviewer.get("runId") == result["actorRunId"]
    )
    if same_actor or same_run:
        raise LifecycleError(
            "task-review-self-certification",
            "task result author cannot independently review the same attempt",
        )
