"""Read-only workflow projections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.workflow.selectors import active_tasks, ready_tasks
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
        return {"type": "request-human-decision", "blocker": state.get("blocker")}
    if phase == "AWAITING_AUTHORIZATION":
        return {"type": "request-execution-authorization"}
    if phase == "READY":
        return {"type": "start-execution"}
    if phase in EXECUTION_PHASES:
        ready = ready_tasks(state)
        if ready:
            return {"type": "launch-tasks", "taskIds": ready}
        active = active_tasks(state)
        if active:
            return {"type": "wait-for-active-tasks", "taskIds": active}
        return {"type": "run-final-audit"}
    if phase == "FINAL_AUDIT":
        return {"type": "finalize-run"}
    return {"type": "continue-phase", "phase": phase}
