"""Thin root CLI dispatcher for Agent Lifecycle Kit."""

from __future__ import annotations

import argparse
from typing import Any

from agent_lifecycle.cli.dispatch_adapters import dispatch_adapters
from agent_lifecycle.cli.benchmarks import dispatch_benchmark
from agent_lifecycle.cli.dispatch_contracts import dispatch_contracts
from agent_lifecycle.cli.dispatch_lifecycle import dispatch_lifecycle
from agent_lifecycle.cli.dispatch_observability import dispatch_observability
from agent_lifecycle.cli.dispatch_planning import dispatch_planning
from agent_lifecycle.cli.followup import dispatch_followup
from agent_lifecycle.cli.host_launch import dispatch_host_launch
from agent_lifecycle.cli.policy import dispatch_policy
from agent_lifecycle.cli.start import dispatch_start
from agent_lifecycle.cli.project import dispatch_project
from agent_lifecycle.cli.strategy import dispatch_strategy
from agent_lifecycle.cli.worktree import dispatch_worktree
from agent_lifecycle.contracts import LifecycleError


def dispatch(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any] | str | None:
    """Route a parsed command without owning domain behavior or CLI output."""
    if args.command == "start":
        return dispatch_start(args, remainder)
    if args.command == "host-launch":
        return dispatch_host_launch(args)
    if args.command == "strategy":
        return dispatch_strategy(args)
    if args.command == "project":
        return dispatch_project(args)
    del remainder
    if args.command in {"diagnose", "diagnostics", "adapter"}:
        return dispatch_adapters(args)
    if args.command in {"version", "schema", "contract", "evidence", "import", "quality", "review-mesh"}:
        return dispatch_contracts(args)
    if args.command in {"workflow", "audit", "runner"}:
        return dispatch_lifecycle(args)
    if args.command in {"report", "context", "goal", "model", "metrics", "thread"}:
        return dispatch_observability(args)
    if args.command in {"tier", "specification", "plan", "task"}:
        return dispatch_planning(args)
    if args.command == "policy":
        return dispatch_policy(args)
    if args.command == "followup":
        return dispatch_followup(args)
    if args.command == "worktree":
        return dispatch_worktree(args)
    if args.command == "benchmark":
        return dispatch_benchmark(args)
    raise LifecycleError(
        "command-not-implemented",
        f"{args.command} command group is reserved but not implemented in this build",
    )
