"""Task result and independent review validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.changesets import capture_task_change_set, require_current_task_change_set
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.authority_text import require_review_text
from agent_lifecycle.contracts.review_verdict import open_blocking_finding_ids, validate_review_verdict
from agent_lifecycle.review.validation import require_supported_review_provenance
from agent_lifecycle.workflow.artifacts import require_artifact_identity
from agent_lifecycle.workflow.state import validate_typed_blocker


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
    _require_worker_identity(result)
    packet = task.get("packet")
    if isinstance(packet, dict) and result.get("taskPacketHash") != packet.get("sha256"):
        raise LifecycleError(
            "task-result-lineage-mismatch",
            "task result packet hash mismatch",
        )
    non_accepting = _validate_non_accepting_outcome(
        state,
        task,
        result,
        allowed=allow_non_accepting_outcome,
    )
    _validate_attempt_baseline(task, result)
    item_outcomes = result.get("itemOutcomes")
    if not isinstance(item_outcomes, list) or not item_outcomes:
        raise LifecycleError("task-result-invalid", "task result itemOutcomes are required")
    if any(not isinstance(item, dict) for item in item_outcomes):
        raise LifecycleError("task-result-invalid", "task result itemOutcomes entries must be objects")
    allowed_statuses = (
        {"COMPLETE", "INCOMPLETE", "BLOCKED", "NOT_STARTED", "DEFERRED"} if non_accepting else {"COMPLETE"}
    )
    if any(not isinstance(item.get("status"), str) or item["status"] not in allowed_statuses for item in item_outcomes):
        raise LifecycleError("task-result-not-complete", "task result has incomplete items")
    _validate_commands(result, allow_failed=non_accepting)
    _validate_item_dispositions(state, task, result, repository_root)
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


def _validate_item_dispositions(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    root: Path | None,
) -> None:
    items = result["itemOutcomes"]
    identifiers = [item.get("plannedItemId") for item in items]
    if any(not isinstance(value, str) or not value.strip() for value in identifiers) or len(set(identifiers)) != len(
        items
    ):
        raise LifecycleError(
            "task-result-item-identity-invalid", "item outcomes require unique stable plannedItemId values"
        )
    unfinished = _unfinished_item_ids(state, task, root)
    omitted = sorted(unfinished.difference(identifiers))
    if omitted:
        raise LifecycleError(
            "task-result-unresolved-item-omitted",
            "unfinished prior items require explicit current disposition or reviewed contract change",
            {"plannedItemIds": omitted},
        )
    commands = result.get("commands") or []
    passing = {
        command["id"]
        for command in commands
        if isinstance(command.get("id"), str)
        and command.get("status") in {"PASS", "PASSED"}
        and command.get("exitCode") == 0
    }
    for item in items:
        if item["plannedItemId"] not in unfinished or item["status"] != "COMPLETE":
            continue
        references = item.get("commandIds")
        if (
            not isinstance(references, list)
            or not references
            or any(not isinstance(value, str) or value not in passing for value in references)
        ):
            raise LifecycleError(
                "task-result-item-resolution-unproven",
                "resolving an unfinished item requires passing evidence selected in the current source-bound result",
                {"plannedItemId": item["plannedItemId"]},
            )


def _unfinished_item_ids(state: dict[str, Any], task: dict[str, Any], root: Path | None) -> set[str]:
    unfinished: set[str] = set()
    snapshots = state.get("priorSnapshots", [])
    if not isinstance(snapshots, list):
        raise LifecycleError("task-result-history-invalid", "prior plan snapshots must be an array")
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("tasks"), list):
            raise LifecycleError("task-result-history-invalid", "prior plan snapshot has no task history")
        for previous in snapshot["tasks"]:
            if not isinstance(previous, dict) or previous.get("id") != task.get("id"):
                continue
            _add_unfinished_items(state, task, previous.get("attemptHistory", []), root, unfinished)
            if previous.get("result") is not None:
                _add_unfinished_items(state, task, [{"result": previous["result"]}], root, unfinished)
            excluded = _authorized_item_exclusions(state, snapshot, previous, root)
            if not excluded.issubset(unfinished):
                raise LifecycleError(
                    "task-result-contract-change-invalid", "exclusions must name unfinished prior items"
                )
            unfinished.difference_update(excluded)
    _add_unfinished_items(state, task, task.get("attemptHistory", []), root, unfinished)
    return unfinished


def _add_unfinished_items(
    state: dict[str, Any],
    task: dict[str, Any],
    history: Any,
    root: Path | None,
    unfinished: set[str],
) -> None:
    if not isinstance(history, list):
        raise LifecycleError("task-result-history-invalid", "prior outcome history must be an array")
    if history and root is None:
        raise LifecycleError("task-result-history-context-missing", "prior outcomes require their repository context")
    for entry in history:
        if not isinstance(entry, dict) or not isinstance(entry.get("result"), dict) or root is None:
            raise LifecycleError("task-result-history-invalid", "prior outcome identity is unavailable")
        prior = require_artifact_identity(root, entry["result"], label="prior task result")
        if prior.get("runId") != state.get("runId") or prior.get("taskId") != task.get("id"):
            raise LifecycleError("task-result-history-invalid", "prior outcomes belong to another run or task")
        items = prior.get("itemOutcomes")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise LifecycleError("task-result-history-invalid", "prior item outcomes are invalid")
        for item in items:
            if isinstance(item, dict) and item.get("status") in {"INCOMPLETE", "BLOCKED", "NOT_STARTED", "DEFERRED"}:
                identifier = item.get("plannedItemId")
                if not isinstance(identifier, str) or not identifier.strip():
                    raise LifecycleError("task-result-history-invalid", "unfinished prior item lacks stable identity")
                unfinished.add(identifier)


def _authorized_item_exclusions(
    state: dict[str, Any],
    snapshot: dict[str, Any],
    previous: dict[str, Any],
    root: Path | None,
) -> set[str]:
    request = previous.get("contractChangeRequest")
    if not isinstance(request, dict) or "excludedPlannedItemIds" not in request:
        return set()
    identifiers = request["excludedPlannedItemIds"]
    current_revision, old_revision = state.get("planRevision"), snapshot.get("planRevision")
    if (
        not isinstance(identifiers, list)
        or any(not isinstance(item, str) or not item.strip() for item in identifiers)
        or len(set(identifiers)) != len(identifiers)
        or not isinstance(request.get("reason"), str)
        or not request["reason"].strip()
        or previous.get("status") != "CONTRACT_CHANGE"
        or root is None
        or type(current_revision) is not int
        or type(old_revision) is not int
        or current_revision <= old_revision
        or state.get("planDigest") == snapshot.get("planDigest")
        or not isinstance(previous.get("review"), dict)
        or not isinstance(previous.get("result"), dict)
    ):
        raise LifecycleError(
            "task-result-contract-change-invalid", "exclusion requires an adopted independent contract change"
        )
    result = require_artifact_identity(root, previous["result"], label="contract change result")
    review = require_artifact_identity(root, previous["review"], label="contract change review")
    if validate_task_outcome_review(snapshot, previous, review, result=result) != "CONTRACT_CHANGE":
        raise LifecycleError(
            "task-result-contract-change-invalid", "exclusion review does not authorize a contract change"
        )
    reviewed_request = review["contractChangeRequest"]
    if (
        not reviewed_request
        or any(request.get(key) != value for key, value in reviewed_request.items())
        or (reviewed_request.get("excludedPlannedItemIds") != identifiers)
    ):
        raise LifecycleError(
            "task-result-contract-change-invalid", "exclusion differs from the immutable independent review"
        )
    return set(identifiers)


def _validate_non_accepting_outcome(
    state: dict[str, Any],
    task: dict[str, Any],
    result: dict[str, Any],
    *,
    allowed: bool,
) -> bool:
    blocker, change = result.get("blocker"), result.get("contractChangeRequest")
    if blocker is None and change is None:
        return False
    if not allowed or state.get("schemaVersion") != "agent-workflow-state.v4":
        raise LifecycleError("task-result-not-acceptable", "blocking task result cannot enter review acceptance path")
    if blocker is not None and change is not None:
        raise LifecycleError("task-result-invalid", "task result must select one non-accepting outcome")
    if blocker is not None:
        validate_typed_blocker(blocker, expected_task_id=task.get("id"))
        if "attempt" in blocker and blocker["attempt"] != task.get("attempt"):
            raise LifecycleError("task-result-lineage-mismatch", "task result blocker attempt mismatch")
    elif not isinstance(change, dict) or not isinstance(change.get("reason"), str) or not change["reason"].strip():
        raise LifecycleError("task-result-invalid", "contract change request requires a reason")
    return True


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


def _validate_commands(result: dict[str, Any], *, allow_failed: bool = False) -> None:
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
        failed_outcome = status in ("FAIL", "FAILED") or (type(exit_code) is int and exit_code != 0)
        unproven_outcome = (
            not isinstance(status, str)
            or status not in {"PASS", "PASSED"}
            or type(exit_code) is not int
            or exit_code != 0
        )
        if failed_outcome or (not allow_failed and unproven_outcome):
            failed.append(command.get("id") or command.get("command") or "<unknown>")
    if failed and not allow_failed:
        raise LifecycleError(
            "task-result-failed-command",
            "task result cannot report completion over failed commands",
            {"commands": failed},
        )


def _require_worker_identity(result: dict[str, Any]) -> None:
    for field in ("actor", "actorRunId"):
        if not isinstance(result.get(field), str) or not result[field]:
            raise LifecycleError(
                "task-result-invalid",
                f"task result {field} is required",
            )


def validate_task_review(
    state: dict[str, Any],
    task: dict[str, Any],
    review: dict[str, Any],
    *,
    result: dict[str, Any] | None = None,
) -> None:
    if result is not None:
        _require_review_id(review)
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
    open_medium_plus = open_blocking_finding_ids(findings)
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

    _require_review_id(review)
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

    _require_review_id(review)
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
    require_review_text(value)
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
    require_review_text(review)
    require_supported_review_provenance(review, native_phase="task-review")
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


def _require_review_id(review: dict[str, Any]) -> None:
    if not isinstance(review.get("reviewId"), str) or not review["reviewId"]:
        raise LifecycleError("task-review-invalid", "task review reviewId is required")


def _require_reviewer_separate_from_worker(review: dict[str, Any], result: dict[str, Any]) -> None:
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        raise LifecycleError("task-review-not-independent", "task review must identify an independent reviewer")
    for field in ("id", "runId"):
        value = reviewer.get(field)
        if not isinstance(value, str) or not value.strip():
            raise LifecycleError(
                "task-review-not-independent",
                f"task review reviewer.{field} must identify an independent reviewer",
            )
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
