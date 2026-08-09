"""Thin root CLI dispatcher for Agent Lifecycle Kit."""

from __future__ import annotations

import argparse
from typing import Any

from agent_lifecycle.cli.dispatch_adapters import dispatch_adapters
from agent_lifecycle.cli.dispatch_contracts import dispatch_contracts
from agent_lifecycle.cli.dispatch_lifecycle import dispatch_lifecycle
from agent_lifecycle.cli.dispatch_observability import dispatch_observability
from agent_lifecycle.cli.dispatch_planning import dispatch_planning
from agent_lifecycle.cli.followup import dispatch_followup
from agent_lifecycle.cli.policy import dispatch_policy
from agent_lifecycle.cli.worktree import dispatch_worktree
from agent_lifecycle.contracts import LifecycleError


def dispatch(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any] | str | None:
    """Route a parsed command without owning domain behavior or CLI output."""
    del remainder
    if args.command in {"diagnose", "diagnostics", "adapter"}:
        return dispatch_adapters(args)
    if args.command in {"version", "schema", "contract", "evidence", "import", "quality", "review-mesh"}:
        return dispatch_contracts(args)
    if args.command in {"workflow", "audit", "runner"}:
        return dispatch_lifecycle(args)
    if args.command in {"report", "context", "goal", "model", "metrics"}:
        return dispatch_observability(args)
    if args.command in {"tier", "specification", "plan", "task"}:
        return dispatch_planning(args)
    if args.command == "policy":
        return dispatch_policy(args)
    if args.command == "followup":
        return dispatch_followup(args)
    if args.command == "worktree":
        return dispatch_worktree(args)
    raise LifecycleError(
        "command-not-implemented",
        f"{args.command} command group is reserved but not implemented in this build",
    )
