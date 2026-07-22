"""Compatibility facade for the standalone workflow controller API."""

from __future__ import annotations

from agent_lifecycle.workflow.finalization import finalize_run
from agent_lifecycle.workflow.query import next_action, status
from agent_lifecycle.workflow.plan_adoption import adopt_plan, start_execution
from agent_lifecycle.workflow.run_transitions import block_run, resolve_blocker
from agent_lifecycle.workflow.task_transitions import (
    accept_task,
    commit_task_result,
    start_task,
)

__all__ = [
    "accept_task",
    "adopt_plan",
    "block_run",
    "commit_task_result",
    "finalize_run",
    "next_action",
    "resolve_blocker",
    "start_execution",
    "start_task",
    "status",
]
