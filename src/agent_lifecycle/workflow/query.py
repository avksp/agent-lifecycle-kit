"""Read-only workflow projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.workflow.selectors import active_tasks, ready_tasks, rework_tasks
from agent_lifecycle.workflow.state import (
    EXECUTION_PHASES,
    TERMINAL_PHASES,
    load_state,
    summarize_state,
)


def status(state_path: Path, *, full: bool = False) -> dict[str, Any]:
    state = load_state(state_path)
    if full:
        return {
            "schemaVersion": "agent-workflow-status-full.v1",
            "state": state,
            "nextAction": next_action(state),
        }
    return {**summarize_state(state_path, state), "nextAction": next_action(state)}


def next_action(state: dict[str, Any]) -> dict[str, Any]:
    phase = state["phase"]
    if phase in TERMINAL_PHASES:
        return {"type": "none", "reason": f"run is {phase}"}
    if phase == "BLOCKED":
        blocker = state.get("blocker")
        if isinstance(blocker, dict) and blocker.get("recoveryRoute") in {"adopt-plan", "replan-task"}:
            return {
                "type": "adopt-plan",
                "reason": "frozen plan authority must be renewed",
                "blocker": blocker,
            }
        if isinstance(blocker, dict) and blocker.get("recoveryRoute") == "cancel-run":
            return {"type": "none", "reason": "run cancellation is already selected", "blocker": blocker}
        return {"type": "request-human-decision", "blocker": blocker}
    if phase == "WAITING_FOR_BUDGET_DECISION":
        return {"type": "record-budget-decision", "blocker": state.get("blocker")}
    if phase == "WAITING_FOR_EXTERNAL_ACTION":
        return {"type": "record-external-action-receipt", "externalAction": state.get("externalAction")}
    if phase == "AWAITING_AUTHORIZATION":
        return {"type": "request-execution-authorization"}
    if phase == "PLAN_ONLY":
        return {"type": "none", "reason": "plan-only workflow is non-executable"}
    if phase == "READY":
        return {"type": "start-execution"}
    if phase in EXECUTION_PHASES:
        rework = rework_tasks(state)
        if rework:
            return {"type": "launch-tasks", "taskIds": rework, "reason": "start-remediation-attempt"}
        ready = ready_tasks(state)
        if ready:
            return {"type": "launch-tasks", "taskIds": ready}
        verifying = [
            task.get("id")
            for task in state.get("tasks", [])
            if task.get("status") == "VERIFYING" and isinstance(task.get("id"), str)
        ]
        if verifying:
            return {"type": "accept-task", "taskIds": verifying, "reason": "task-review-required"}
        active = active_tasks(state)
        if active:
            return {"type": "wait-for-active-tasks", "taskIds": active}
        required = [task for task in state.get("tasks", []) if task.get("required", True)]
        unresolved = [
            task for task in required if task.get("status") in {"BLOCKED", "CONTRACT_CHANGE"}
        ]
        if unresolved:
            return {
                "type": "request-human-decision",
                "reason": "required-task-outcome-needs-resolution",
                "taskIds": [task.get("id") for task in unresolved],
                "outcomes": [
                    {"taskId": task.get("id"), "status": task.get("status"), "blocker": task.get("blocker")}
                    for task in unresolved
                ],
            }
        if any(task.get("status") != "ACCEPTED" for task in required):
            return {
                "type": "wait-for-task-outcome",
                "taskIds": [task.get("id") for task in required if task.get("status") != "ACCEPTED"],
            }
        return {"type": "run-final-audit"}
    if phase == "FINAL_AUDIT":
        outcome = state.get("finalAuditOutcome")
        if state.get("schemaVersion") == "agent-workflow-state.v4" and (
            not isinstance(outcome, dict) or outcome.get("verdict") != "ACCEPTED"
        ):
            return {
                "type": "final-audit-outcome",
                "verdicts": ["ACCEPTED", "REWORK", "CONTRACT_CHANGE", "BLOCKED"],
                "reason": "independent final-audit verdict is required",
            }
        return {"type": "finalize-run"}
    return {"type": "none", "reason": f"unsupported workflow phase: {phase}"}
