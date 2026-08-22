"""Thin root CLI dispatcher for Agent Lifecycle Kit."""

from __future__ import annotations

import argparse
import importlib
from typing import Any

from agent_lifecycle.cli.command_registry import COMMAND_DISPATCH
from agent_lifecycle.contracts import LifecycleError


def _lazy_call(
    module_name: str, function_name: str, args: argparse.Namespace, remainder: list[str] | None = None
) -> dict[str, Any] | str | None:
    function = getattr(importlib.import_module(module_name), function_name)
    return function(args, remainder) if remainder is not None else function(args)


def dispatch_start(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.start", "dispatch_start", args, remainder)


def dispatch_host_launch(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.host_launch", "dispatch_host_launch", args)


def dispatch_strategy(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.strategy", "dispatch_strategy", args)


def dispatch_project(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.project", "dispatch_project", args)


def dispatch_adapters(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.dispatch_adapters", "dispatch_adapters", args)


def dispatch_research(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.dispatch_research", "dispatch_research", args)


def dispatch_contracts(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.dispatch_contracts", "dispatch_contracts", args)


def dispatch_lifecycle(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.dispatch_lifecycle", "dispatch_lifecycle", args)


def dispatch_observability(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.dispatch_observability", "dispatch_observability", args)


def dispatch_planning(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.dispatch_planning", "dispatch_planning", args)


def dispatch_policy(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.policy", "dispatch_policy", args)


def dispatch_followup(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.followup", "dispatch_followup", args)


def dispatch_worktree(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.worktree", "dispatch_worktree", args)


def dispatch_benchmark(args: argparse.Namespace) -> dict[str, Any] | str | None:
    return _lazy_call("agent_lifecycle.cli.benchmarks", "dispatch_benchmark", args)


def dispatch(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any] | str | None:
    """Route a parsed command without owning domain behavior or CLI output."""
    target = COMMAND_DISPATCH.get(args.command)
    if target is None:
        raise LifecycleError(
            "command-not-implemented", f"{args.command} command group is reserved but not implemented in this build"
        )
    _, function_name, accepts_remainder = target
    function = globals()[function_name]
    if accepts_remainder:
        return function(args, remainder)
    del remainder
    return function(args)
