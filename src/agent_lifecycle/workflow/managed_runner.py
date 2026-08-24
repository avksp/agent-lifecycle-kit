"""Compatibility import for the pre-2.0 managed workflow name.

The implementation lives in :mod:`agent_lifecycle.workflow.run`. This alias
does not own state, transitions, budgets or host execution.
"""

from agent_lifecycle.workflow.run import run_workflow_step

run_managed_lifecycle_step = run_workflow_step

__all__ = ["run_managed_lifecycle_step", "run_workflow_step"]
