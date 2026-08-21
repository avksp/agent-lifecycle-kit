"""Parser declarations for plan and task compilation commands."""

from __future__ import annotations

import argparse

from agent_lifecycle.resources import builtin_profile_path

_SMALL_CONTEXT_PROFILE = builtin_profile_path("small-context-profile.v1.json")


def _add_plan_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    plan = subparsers.add_parser("plan", help="plan commands")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_check = plan_sub.add_parser("check")
    plan_check.add_argument("--manifest", required=True)
    plan_check.add_argument("--lock")
    plan_check.add_argument("--require-completeness", action="store_true")
    plan_check.add_argument("--completeness-profile")
    completeness_check = plan_sub.add_parser("completeness-check")
    completeness_check.add_argument("--manifest", required=True)
    completeness_check.add_argument("--profile")
    completeness_check.add_argument("--out")
    acceptance_check = plan_sub.add_parser("acceptance-check")
    acceptance_check.add_argument("--manifest", required=True)
    acceptance_check.add_argument("--acceptance", required=True)
    refs_check = plan_sub.add_parser("refs-check")
    refs_check.add_argument("--manifest", required=True)
    snapshot = plan_sub.add_parser("snapshot")
    snapshot.add_argument("--manifest", required=True)
    snapshot.add_argument("--out")
    reconcile = plan_sub.add_parser("reconcile")
    reconcile.add_argument("--manifest", required=True)
    reconcile.add_argument("--snapshot", required=True)
    handoff = plan_sub.add_parser("handoff")
    handoff.add_argument("--manifest", required=True)
    handoff.add_argument("--snapshot")
    handoff.add_argument("--max-workstreams", type=int, default=12)
    handoff.add_argument("--target-tokens", type=int, default=4096)
    handoff.add_argument("--out")
    delta = plan_sub.add_parser("delta", help="compare two explicit plan revisions")
    delta.add_argument("--before", required=True)
    delta.add_argument("--after", required=True)
    delta.add_argument("--before-snapshot")
    delta.add_argument("--after-snapshot")
    delta.add_argument("--before-lock")
    delta.add_argument("--after-lock")
    delta.add_argument("--principles")
    delta.add_argument("--out")
    delta_check = plan_sub.add_parser("delta-check", aliases=["delta-validate"])
    delta_check.add_argument("--delta", required=True)
    delta_check.add_argument("--out")


def _add_task_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    task = subparsers.add_parser("task", help="task commands")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_compile = task_sub.add_parser("compile")
    task_compile.add_argument("--manifest", required=True)
    task_compile.add_argument("--strategy")
    task_compile.add_argument("--out-dir")
    task_compile.add_argument("--write", action="store_true")
    small_compile = task_sub.add_parser("compile-small")
    small_compile.add_argument("--manifest", required=True)
    small_compile.add_argument("--context-profile", default=_SMALL_CONTEXT_PROFILE)
    small_compile.add_argument("--target-window", default="4k-strict")
    small_compile.add_argument("--adaptive-decision")
    small_compile.add_argument("--strategy")
    small_compile.add_argument("--out-dir")
    small_compile.add_argument("--write", action="store_true")
