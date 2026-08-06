"""Goal continuity records and compact objective snapshots."""

from agent_lifecycle.goal.records import (
    build_objective_snapshot,
    update_goal_record,
    validate_goal_record,
)
from agent_lifecycle.goal.view import build_goal_progress_view

__all__ = [
    "build_goal_progress_view",
    "build_objective_snapshot",
    "update_goal_record",
    "validate_goal_record",
]
