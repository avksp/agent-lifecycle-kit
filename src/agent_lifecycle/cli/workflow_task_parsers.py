"""Parser declarations for workflow task transitions and strategy adoption."""

from __future__ import annotations

import argparse

from agent_lifecycle.cli.progress_hooks import add_progress_hook_args
from agent_lifecycle.resources import builtin_profile_path

_BASELINE_PROFILE = builtin_profile_path("lifecycle-baselines.v1.json")
_MODEL_ROUTING_PROFILE = builtin_profile_path("model-routing-profile.v1.json")
_RISK_POLICY = builtin_profile_path("risk-execution-policy.v1.json")


def add_strategy_adoption_args(parser: argparse.ArgumentParser) -> None:
    """Add an immutable strategy path and independently supplied policy inputs."""

    parser.add_argument("--strategy")
    parser.add_argument("--strategy-risk", choices=["auto", "S0", "S1", "S2"], default="auto")
    parser.add_argument("--strategy-risk-policy", default=_RISK_POLICY)
    parser.add_argument("--strategy-routing-profile", default=_MODEL_ROUTING_PROFILE)
    parser.add_argument("--strategy-baseline-profile", default=_BASELINE_PROFILE)
    parser.add_argument("--strategy-host-model-profile")
    parser.add_argument("--strategy-descriptor")
    parser.add_argument("--strategy-capability-manifest")
    parser.add_argument("--strategy-project-profile")


def add_workflow_task_parsers(
    workflow_sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register task, snapshot, validation and budget transition parsers."""

    workflow_task = workflow_sub.add_parser("task-start")
    workflow_task.add_argument("--state", required=True)
    workflow_task.add_argument("--task", required=True)
    workflow_task.add_argument("--operation-id", required=True)
    workflow_task.add_argument("--expected-revision", required=True, type=int)
    workflow_task.add_argument("--source-revision", required=True)
    workflow_task.add_argument("--risk-profile")
    add_strategy_adoption_args(workflow_task)
    workflow_task.add_argument("--reason", required=True)
    workflow_result = workflow_sub.add_parser("task-result")
    workflow_result.add_argument("--state", required=True)
    workflow_result.add_argument("--task", required=True)
    workflow_result.add_argument("--operation-id", required=True)
    workflow_result.add_argument("--expected-revision", required=True, type=int)
    workflow_result.add_argument("--source-revision", required=True)
    workflow_result.add_argument("--result", required=True)
    workflow_result.add_argument("--model-usage-receipt")
    workflow_result.add_argument("--budget-targets")
    workflow_result.add_argument("--reason", required=True)
    add_progress_hook_args(workflow_result)
    workflow_snapshot = workflow_sub.add_parser("task-snapshot")
    workflow_snapshot.add_argument("--state", required=True)
    workflow_snapshot.add_argument("--task", required=True)
    workflow_snapshot.add_argument("--out")
    workflow_snapshot.add_argument("--manifest")
    workflow_snapshot.add_argument("--lock")
    workflow_snapshot.add_argument(
        "--phase-packet-purpose",
        choices=["IMPLEMENTATION", "TASK_AUDIT", "REMEDIATION"],
    )
    workflow_snapshot.add_argument("--phase-packet-out")
    validation_select = workflow_sub.add_parser("validation-select")
    validation_select.add_argument("--state", required=True)
    validation_select.add_argument("--task", required=True)
    validation_select.add_argument("--manifest", required=True)
    validation_select.add_argument("--lock", required=True)
    validation_select.add_argument("--snapshot", required=True)
    validation_select.add_argument("--out")
    workflow_budget = workflow_sub.add_parser("budget-decision")
    workflow_budget.add_argument("--state", required=True)
    workflow_budget.add_argument("--task", required=True)
    workflow_budget.add_argument("--operation-id", required=True)
    workflow_budget.add_argument("--expected-revision", required=True, type=int)
    workflow_budget.add_argument("--source-revision", required=True)
    workflow_budget.add_argument("--model-usage-receipt")
    workflow_budget.add_argument("--budget-policy")
    workflow_budget.add_argument("--receipt", required=True)
    workflow_budget.add_argument(
        "--action",
        choices=["continue-same-route", "reroute-cheaper", "reroute-stronger", "split-task", "abort"],
    )
    workflow_budget.add_argument("--decision-receipt")
    workflow_budget.add_argument("--route-decision")
    workflow_budget.add_argument("--split-packet")
    workflow_budget.add_argument("--cap-deltas")
    workflow_budget.add_argument("--operator-identity-hash")
    workflow_budget.add_argument("--reason", required=True)
    workflow_budget_policy = workflow_sub.add_parser("budget-policy-check")
    workflow_budget_policy.add_argument("--policy", required=True)


__all__ = ["add_strategy_adoption_args", "add_workflow_task_parsers"]
