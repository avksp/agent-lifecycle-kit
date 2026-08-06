"""Read-only goal and lifecycle progress view."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.goal.records import validate_goal_record
from agent_lifecycle.reporting.progress_view import build_lifecycle_progress_view
from agent_lifecycle.workflow.query import next_action
from agent_lifecycle.workflow.state import load_state

GOAL_PROGRESS_VIEW_SCHEMA = "agent-goal-progress-view.v1"


def build_goal_progress_view(
    *,
    record_path: Path,
    state_path: Path,
    usage_receipt_paths: list[Path] | None = None,
    change_summary_path: Path | None = None,
    require_current: bool = True,
) -> dict[str, Any]:
    """Build a compact read-only view from goal and progress artifacts."""

    record = read_json_object(record_path, label="goal record")
    state = load_state(state_path)
    validation = validate_goal_record(record, state=state, require_current=require_current)
    progress = build_lifecycle_progress_view(
        state_path=state_path,
        usage_receipt_paths=usage_receipt_paths or [],
        change_summary_path=change_summary_path,
    )
    task_summary = _task_summary(state)
    blockers = _blockers(state, task_summary)
    body = {
        "schemaVersion": GOAL_PROGRESS_VIEW_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "readOnly": True,
        "modelCallsStarted": False,
        "hostCallsStarted": False,
        "stateMutated": False,
        "goalRecordMutated": False,
        "stateWritten": False,
        "goalRecordWritten": False,
        "tokenSpendForView": False,
        "goal": {
            "goalId": validation["goalId"],
            "goalStatus": validation["goalStatus"],
            "goalDigest": validation["goalDigest"],
            "userIntentDigest": canonical_digest({"userIntent": record.get("userIntent")}),
            "ownerOutcomeDigest": canonical_digest({"ownerOutcome": record.get("ownerOutcome")}),
            "constraintCount": validation["constraintCount"],
            "evidenceIds": validation["evidenceIds"],
            "stateRevision": validation["stateRevision"],
        },
        "lifecycle": {
            "runId": state.get("runId"),
            "packageId": state.get("packageId"),
            "planRevision": state.get("planRevision"),
            "planDigest": state.get("planDigest"),
            "sourceRevision": state.get("sourceRevision"),
            "phase": state.get("phase"),
            "stateRevision": state.get("stateRevision"),
            "nextAction": next_action(state),
            "taskSummary": task_summary,
        },
        "progress": {
            "progressDigest": progress["progressDigest"],
            "rowCount": progress["rowCount"],
            "lines": progress["lines"],
            "terminalSummary": progress["terminalSummary"],
        },
        "metrics": {
            "duration": progress["terminalSummary"]["duration"],
            "tokens": progress["terminalSummary"]["tokens"],
            "changeSummary": progress["terminalSummary"]["changeSummary"],
        },
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "viewDigest": canonical_digest(body)}


def _task_summary(state: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    tasks = state.get("tasks")
    for task in tasks if isinstance(tasks, list) else []:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _blockers(state: dict[str, Any], task_summary: dict[str, int]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    blocker = state.get("blocker")
    if isinstance(blocker, dict):
        blockers.append({
            "code": str(blocker.get("code") or "workflow-blocked"),
            "message": str(blocker.get("message") or blocker.get("reason") or "workflow is blocked"),
        })
    blocked_count = task_summary.get("BLOCKED", 0)
    if blocked_count:
        blockers.append({"code": "blocked-tasks-present", "count": blocked_count})
    return blockers
