"""Run-level workflow transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.events import append_event
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import (
    TERMINAL_PHASES,
    load_state,
    now_iso,
    record_operation,
    require_expected_revision,
    require_operation_unused,
    write_state_replace,
)


def block_run(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    blocker_code: str,
    reason: str,
) -> dict[str, Any]:
    state = load_state(state_path)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    if state["phase"] in TERMINAL_PHASES:
        raise LifecycleError("terminal-run", "terminal workflow state cannot be blocked")
    previous = state["phase"]
    state["stateRevision"] += 1
    state["phase"] = "BLOCKED"
    state["blocker"] = {"code": blocker_code, "reason": reason, "resumePhase": previous}
    state["updatedAt"] = now_iso()
    record_operation(state, operation_id=operation_id, event_type="run-blocked")
    append_event(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="run-blocked",
        payload={"previousPhase": previous, "blocker": state["blocker"]},
    )
    write_state_replace(state_path, state)
    return status(state_path)


def resolve_blocker(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    reason: str,
) -> dict[str, Any]:
    state = load_state(state_path)
    require_expected_revision(state, expected_revision)
    require_operation_unused(state, operation_id)
    if state["phase"] != "BLOCKED":
        raise LifecycleError("invalid-phase", "only BLOCKED runs can be resolved")
    blocker = state.get("blocker")
    if not isinstance(blocker, dict):
        raise LifecycleError("invalid-workflow-state", "blocked run has no blocker")
    resume_phase = blocker.get("resumePhase")
    if not isinstance(resume_phase, str) or resume_phase in TERMINAL_PHASES:
        raise LifecycleError("invalid-workflow-state", "blocker resumePhase is invalid")
    previous = state["phase"]
    state["stateRevision"] += 1
    state["phase"] = resume_phase
    state["blocker"] = None
    state["updatedAt"] = now_iso()
    record_operation(state, operation_id=operation_id, event_type="run-resolved")
    append_event(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="run-resolved",
        payload={"previousPhase": previous, "resumePhase": resume_phase, "reason": reason},
    )
    write_state_replace(state_path, state)
    return status(state_path)
