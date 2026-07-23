"""Run-level workflow transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.workflow.operation_kernel import commit_state, load_for_update
from agent_lifecycle.workflow.query import status
from agent_lifecycle.workflow.state import TERMINAL_PHASES


def block_run(
    state_path: Path,
    *,
    operation_id: str,
    expected_revision: int,
    blocker_code: str,
    reason: str,
) -> dict[str, Any]:
    state = load_for_update(state_path, operation_id=operation_id, expected_revision=expected_revision)
    if state["phase"] in TERMINAL_PHASES:
        raise LifecycleError("terminal-run", "terminal workflow state cannot be blocked")
    previous = state["phase"]
    state["phase"] = "BLOCKED"
    state["blocker"] = {"code": blocker_code, "reason": reason, "resumePhase": previous}
    commit_state(
        state_path=state_path,
        state=state,
        operation_id=operation_id,
        event_type="run-blocked",
        payload={"previousPhase": previous, "blocker": state["blocker"]},
    )
    return status(state_path)


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
