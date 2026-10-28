"""Run-level workflow transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.workflow_state_schemas import has_current_workflow_semantics
from agent_lifecycle.workflow.artifacts import artifact_identity, package_root, require_artifact_identity
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.reviews import task_result_freshness_required, validate_task_result
from agent_lifecycle.workflow.selectors import find_task
from agent_lifecycle.workflow.state import EXTERNAL_ACTION_PHASES, TERMINAL_PHASES, validate_typed_blocker
from agent_lifecycle.workflow.transactions import workflow_transaction

REVIEW_INTERRUPTION_CODES = {"review-response-missing", "review-response-truncated"}


@workflow_transaction
def block_run(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    blocker_code: str,
    reason: str,
    review_task_id: str | None = None,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] in TERMINAL_PHASES:
        raise LifecycleError("terminal-run", "terminal workflow state cannot be blocked")
    if state["phase"] == "BLOCKED":
        raise LifecycleError("nested-blocker-forbidden", "a blocked workflow cannot be blocked again")
    subject = None
    if blocker_code in REVIEW_INTERRUPTION_CODES:
        if not has_current_workflow_semantics(state) or not review_task_id:
            raise LifecycleError(
                "review-interruption-task-required", "technical review interruption requires v4 and a task"
            )
        subject = _technical_review_subject(state_path, state, review_task_id)
    elif review_task_id is not None:
        raise LifecycleError("review-interruption-code-required", "review task requires a technical interruption code")
    previous = state["phase"]
    state["phase"] = "BLOCKED"
    blocker: dict[str, Any] = {"code": blocker_code, "reason": reason, "resumePhase": previous}
    if has_current_workflow_semantics(state):
        blocker.update({"scope": "run", "recoveryRoute": "resolve-run"})
        if subject is not None:
            blocker["reviewSubject"] = subject
        validate_typed_blocker(blocker)
    state["blocker"] = blocker
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="run-blocked",
        payload={"previousPhase": previous, "blocker": state["blocker"]},
    )
    return status(state_path)


@workflow_transaction
def resolve_blocker(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] != "BLOCKED":
        raise LifecycleError("invalid-phase", "only BLOCKED runs can be resolved")
    blocker = state.get("blocker")
    if not isinstance(blocker, dict):
        raise LifecycleError("invalid-workflow-state", "blocked run has no blocker")
    if "scope" in blocker:
        validate_typed_blocker(blocker)
        if blocker.get("scope") != "run" or blocker.get("recoveryRoute") != "resolve-run":
            raise LifecycleError(
                "typed-blocker-route-required",
                "task, plan and external blockers require their named recovery route",
            )
    if blocker.get("code") in REVIEW_INTERRUPTION_CODES:
        _require_review_recovery(state_path, state, blocker)
    resume_phase = blocker.get("resumePhase")
    if not isinstance(resume_phase, str) or resume_phase in TERMINAL_PHASES:
        raise LifecycleError("invalid-workflow-state", "blocker resumePhase is invalid")
    previous = state["phase"]
    state["phase"] = resume_phase
    state["blocker"] = None
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="run-resolved",
        payload={"previousPhase": previous, "resumePhase": resume_phase, "reason": reason},
    )
    return status(state_path)


def _technical_review_subject(state_path: Path, state: dict[str, Any], task_id: str) -> dict[str, Any]:
    task = find_task(state, task_id)
    if task.get("status") != "VERIFYING" or not isinstance(task.get("result"), dict) or task.get("pendingDecision"):
        raise LifecycleError(
            "review-interruption-subject-invalid", "technical recovery requires a pending implementation review"
        )
    root = package_root(state_path, state)
    result = require_artifact_identity(root, task["result"], label="pending review subject")
    if any(result.get(key) != state.get(key) for key in ("runId", "planDigest", "sourceRevision")):
        raise LifecycleError("review-interruption-subject-invalid", "pending result does not match the current run")
    if "planRevision" in result and result["planRevision"] != state.get("planRevision"):
        raise LifecycleError("review-interruption-subject-invalid", "pending result has another plan revision")
    if result.get("taskId") != task_id or result.get("attempt") != task.get("attempt"):
        raise LifecycleError("review-interruption-subject-invalid", "pending result does not match the current attempt")
    packet = task.get("packet")
    if isinstance(packet, dict) and result.get("taskPacketHash") != packet.get("sha256"):
        raise LifecycleError("review-interruption-subject-invalid", "pending result does not match its task packet")
    if task_result_freshness_required(state):
        validate_task_result(
            state,
            task,
            result,
            task["result"],
            repository_root=root,
            require_freshness=True,
            allow_non_accepting_outcome=True,
        )
    iterations = task.get("usageIterations", [])
    return {
        "runId": state["runId"],
        "taskId": task_id,
        "attempt": task["attempt"],
        "planDigest": state["planDigest"],
        "planRevision": state["planRevision"],
        "packet": dict(packet) if isinstance(packet, dict) else None,
        "sourceRevision": state["sourceRevision"],
        "result": dict(task["result"]),
        "findingIds": sorted(task.get("remediationFindingIds", [])),
        "budgetDigest": canonical_digest(state.get("budgets", {})),
        "runDeadlineAt": state.get("runDeadlineAt"),
        "attemptDeadlineAt": task.get("attemptDeadlineAt"),
        "usageTotals": dict(task.get("usageTotals") or {}),
        "usageIterationCount": len(iterations),
        "usageIterationDigest": canonical_digest(iterations),
    }


def _require_review_recovery(state_path: Path, state: dict[str, Any], blocker: dict[str, Any]) -> None:
    previous = blocker.get("reviewSubject")
    if not isinstance(previous, dict) or not isinstance(previous.get("taskId"), str):
        raise LifecycleError("review-recovery-subject-missing", "technical blocker lacks a bound review subject")
    current = _technical_review_subject(state_path, state, previous["taskId"])
    if (
        set(previous) != set(current)
        or not isinstance(previous.get("usageTotals"), dict)
        or type(previous.get("usageIterationCount")) is not int
        or previous["usageIterationCount"] < 0
    ):
        raise LifecycleError("review-recovery-subject-invalid", "technical blocker subject shape is invalid")
    changing_usage = {"usageTotals", "usageIterationCount", "usageIterationDigest"}
    if {k: v for k, v in current.items() if k not in changing_usage} != {
        k: v for k, v in previous.items() if k not in changing_usage
    }:
        raise LifecycleError(
            "review-recovery-subject-mismatch", "technical recovery cannot change its review subject or caps"
        )
    task = find_task(state, previous["taskId"])
    iterations = task.get("usageIterations", [])
    count = previous["usageIterationCount"]
    if len(iterations) < count or canonical_digest(iterations[:count]) != previous["usageIterationDigest"]:
        raise LifecycleError("review-recovery-usage-reset", "technical recovery cannot discard usage history")
    for metric, value in previous["usageTotals"].items():
        actual = current["usageTotals"].get(metric)
        if type(value) in (int, float) and (type(actual) not in (int, float) or actual < value):
            raise LifecycleError("review-recovery-usage-reset", "technical recovery cannot reset accrued usage")
    for name in ("runDeadlineAt", "attemptDeadlineAt"):
        _require_review_deadline(current[name])
    _require_review_capacity(state, task)


def _require_review_capacity(state: dict[str, Any], task: dict[str, Any]) -> None:
    budgets = state.get("budgets", {})
    for metric, task_limit, run_limit in (
        ("reportedTokens", "maxReportedTokensPerTask", "maxReportedTokensPerRun"),
        ("toolCalls", "maxToolCallsPerTask", "maxToolCallsPerRun"),
        ("iterations", "maxUsageIterationsPerAttempt", None),
    ):
        _require_known_capacity((task.get("usageTotals") or {}).get(metric), budgets.get(task_limit))
        cap = budgets.get(run_limit) if run_limit else None
        if type(cap) in (int, float):
            values = [(item.get("usageTotals") or {}).get(metric) for item in state["tasks"] if item.get("attempt")]
            total = (
                sum(value for value in values if isinstance(value, (int, float)))
                if all(type(value) in (int, float) for value in values)
                else None
            )
            _require_known_capacity(total, cap)


def _require_known_capacity(used: Any, cap: Any) -> None:
    if type(cap) in (int, float):
        if type(used) not in (int, float):
            raise LifecycleError("review-recovery-budget-unavailable", "declared remaining capacity is unavailable")
        if used >= cap:
            raise LifecycleError("review-recovery-budget-exhausted", "declared review capacity is exhausted")


def _require_review_deadline(value: Any) -> None:
    try:
        deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if deadline.tzinfo is None or deadline.utcoffset() is None:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise LifecycleError(
            "review-recovery-deadline-unavailable", "technical recovery requires an absolute deadline"
        ) from None
    if datetime.now(UTC) >= deadline:
        raise LifecycleError("review-recovery-deadline-expired", "technical recovery cannot extend an expired deadline")


@workflow_transaction
def pause_for_external_action(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    action_id: str,
    receipt_path: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] not in EXTERNAL_ACTION_PHASES:
        raise LifecycleError(
            "invalid-phase",
            "external action pause requires RUNNING, FINAL_AUDIT or a legacy execution phase",
        )
    if not action_id:
        raise LifecycleError("invalid-external-action", "action_id is required")
    previous = state["phase"]
    expected_receipt = normalize_repo_path(receipt_path, label="external action receipt")
    state["phase"] = "WAITING_FOR_EXTERNAL_ACTION"
    state["externalAction"] = {
        "actionId": action_id,
        "reason": reason,
        "resumePhase": previous,
        "expectedReceiptPath": expected_receipt,
    }
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="external-action-paused",
        payload={"previousPhase": previous, "externalAction": state["externalAction"]},
    )
    return status(state_path)


@workflow_transaction
def resume_external_action(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    receipt_path: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] != "WAITING_FOR_EXTERNAL_ACTION":
        raise LifecycleError("invalid-phase", "external action resume requires WAITING_FOR_EXTERNAL_ACTION phase")
    external_action = state.get("externalAction")
    if not isinstance(external_action, dict):
        raise LifecycleError("invalid-workflow-state", "external action state is missing")
    receipt_rel = normalize_repo_path(receipt_path, label="external action receipt")
    expected_receipt = external_action.get("expectedReceiptPath")
    if isinstance(expected_receipt, str) and receipt_rel != expected_receipt:
        raise LifecycleError("external-action-receipt-mismatch", "external action receipt path mismatch")
    root = package_root(state_path, state)
    if not (root / receipt_rel).is_file():
        raise LifecycleError("external-action-receipt-missing", "external action receipt is missing")
    receipt = read_json_object(root / receipt_rel, label="external action receipt")
    _validate_external_action_receipt(state, external_action, receipt)
    identity = artifact_identity(root, receipt_rel, receipt)
    resume_phase = external_action.get("resumePhase")
    if not isinstance(resume_phase, str) or resume_phase not in EXTERNAL_ACTION_PHASES:
        raise LifecycleError("invalid-workflow-state", "external action resumePhase is invalid")
    state["phase"] = resume_phase
    state["externalActionReceipt"] = identity
    state["externalAction"] = None
    if isinstance(state.get("blocker"), dict) and state["blocker"].get("scope") == "external":
        state["blocker"] = None
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="external-action-resumed",
        payload={"resumePhase": resume_phase, "receipt": identity, "reason": reason},
    )
    return status(state_path)


def _validate_external_action_receipt(
    state: dict[str, Any],
    external_action: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    if receipt.get("schemaVersion") != "agent-external-action-receipt.v1":
        raise LifecycleError("invalid-external-action-receipt", "external action receipt schemaVersion is unsupported")
    expected = {
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "planRevision": state.get("planRevision"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "actionId": external_action.get("actionId"),
        "status": "PASS",
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LifecycleError("external-action-receipt-lineage-mismatch", f"external action receipt {key} mismatch")
    evidence_ids = receipt.get("evidenceIds")
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or not all(isinstance(item, str) and item for item in evidence_ids)
    ):
        raise LifecycleError("invalid-external-action-receipt", "external action receipt evidenceIds are required")
