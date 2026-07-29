"""Argparse construction for the root CLI."""

from __future__ import annotations

import argparse

from agent_lifecycle.cli.adapter import add_adapter_parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-lifecycle")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version", help="print package version as compact JSON")
    _add_schema_parser(subparsers)
    subparsers.add_parser("neutrality", help="run neutrality subcommands")
    _add_workflow_parser(subparsers)
    _add_audit_parser(subparsers)
    _add_context_parser(subparsers)
    _add_model_parser(subparsers)
    _add_tier_parser(subparsers)
    _add_specification_parser(subparsers)
    _add_plan_parser(subparsers)
    _add_task_parser(subparsers)
    add_adapter_parser(subparsers)
    subparsers.add_parser("conformance", help="conformance commands")
    return parser


def _add_schema_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    schema = subparsers.add_parser("schema", help="inspect bundled JSON schemas")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    schema_sub.add_parser("list")
    show = schema_sub.add_parser("show")
    show.add_argument("schema_id")


def _add_workflow_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    workflow = subparsers.add_parser("workflow", help="workflow commands")
    workflow_sub = workflow.add_subparsers(dest="workflow_command", required=True)
    workflow_status = workflow_sub.add_parser("status")
    workflow_status.add_argument("--state", required=True)
    workflow_status.add_argument("--full", action="store_true")
    workflow_next = workflow_sub.add_parser("next")
    workflow_next.add_argument("--state", required=True)
    workflow_adopt = workflow_sub.add_parser("adopt-plan")
    workflow_adopt.add_argument("--state", required=True)
    workflow_adopt.add_argument("--manifest", required=True)
    workflow_adopt.add_argument("--operation-id", required=True)
    workflow_adopt.add_argument("--expected-revision", required=True, type=int)
    workflow_adopt.add_argument("--source-revision", required=True)
    workflow_adopt.add_argument("--reset-tasks", action="store_true")
    workflow_adopt.add_argument("--preserve-accepted-compatible", action="store_true")
    workflow_adopt.add_argument(
        "--start-mode",
        choices=["approval-required", "auto-after-freeze", "plan-only"],
        default="approval-required",
    )
    workflow_adopt.add_argument("--authorized-by")
    workflow_run_start = workflow_sub.add_parser("run-start")
    workflow_run_start.add_argument("--state", required=True)
    workflow_run_start.add_argument("--operation-id", required=True)
    workflow_run_start.add_argument("--expected-revision", required=True, type=int)
    workflow_run_start.add_argument("--source-revision", required=True)
    workflow_run_start.add_argument("--reason", required=True)
    workflow_block = workflow_sub.add_parser("block")
    workflow_block.add_argument("--state", required=True)
    workflow_block.add_argument("--operation-id", required=True)
    workflow_block.add_argument("--expected-revision", required=True, type=int)
    workflow_block.add_argument("--blocker-code", required=True)
    workflow_block.add_argument("--reason", required=True)
    workflow_resolve = workflow_sub.add_parser("resolve")
    workflow_resolve.add_argument("--state", required=True)
    workflow_resolve.add_argument("--operation-id", required=True)
    workflow_resolve.add_argument("--expected-revision", required=True, type=int)
    workflow_resolve.add_argument("--reason", required=True)
    workflow_task = workflow_sub.add_parser("task-start")
    workflow_task.add_argument("--state", required=True)
    workflow_task.add_argument("--task", required=True)
    workflow_task.add_argument("--operation-id", required=True)
    workflow_task.add_argument("--expected-revision", required=True, type=int)
    workflow_task.add_argument("--source-revision", required=True)
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
    workflow_accept = workflow_sub.add_parser("task-accept")
    workflow_accept.add_argument("--state", required=True)
    workflow_accept.add_argument("--task", required=True)
    workflow_accept.add_argument("--operation-id", required=True)
    workflow_accept.add_argument("--expected-revision", required=True, type=int)
    workflow_accept.add_argument("--review", required=True)
    workflow_accept.add_argument("--reason", required=True)
    workflow_finalize = workflow_sub.add_parser("finalize")
    workflow_finalize.add_argument("--state", required=True)
    workflow_finalize.add_argument("--operation-id", required=True)
    workflow_finalize.add_argument("--expected-revision", required=True, type=int)
    workflow_finalize.add_argument("--source-revision", required=True)
    workflow_finalize.add_argument("--final-audit", required=True)
    workflow_finalize.add_argument("--proof", required=True)
    workflow_finalize.add_argument("--reason", required=True)


def _add_audit_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    audit = subparsers.add_parser("audit", help="audit commands")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    ownership = audit_sub.add_parser("ownership")
    ownership.add_argument("--manifest", required=True)
    ownership.add_argument("--base", required=False)
    ownership.add_argument("--path", action="append", default=[])
    ownership.add_argument("--fail-on-unowned", action="store_true")
    ownership.add_argument("--fail-on-forbidden", action="store_true")


def _add_context_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    context = subparsers.add_parser("context", help="compact context commands")
    context_sub = context.add_subparsers(dest="context_command", required=True)
    profile_check = context_sub.add_parser("profile-check")
    profile_check.add_argument("--profile", required=True)
    context_check = context_sub.add_parser("check")
    context_check.add_argument("--profile", required=True)
    context_check.add_argument("--task-packet", required=True)
    context_check.add_argument("--summary", required=True)
    context_check.add_argument("--target-window")
    context_check.add_argument("--latest-user", default="")
    context_render = context_sub.add_parser("render")
    context_render.add_argument("--profile", required=True)
    context_render.add_argument("--task-packet", required=True)
    context_render.add_argument("--summary", required=True)
    context_render.add_argument("--target-window")
    context_render.add_argument("--latest-user", default="")


def _add_model_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    model = subparsers.add_parser("model", help="model routing commands")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_route = model_sub.add_parser("route")
    model_route.add_argument("--request", required=True)
    model_route.add_argument("--profile", default="profiles/model-routing-profile.v1.json")
    model_route.add_argument("--host-profile")
    model_profile_check = model_sub.add_parser("profile-check")
    model_profile_check.add_argument("--profile", required=True)
    model_profile_check.add_argument("--type", choices=["auto", "routing", "host"], default="auto")
    model_usage_check = model_sub.add_parser("usage-check")
    model_usage_check.add_argument("--receipt", required=True)
    model_usage_check.add_argument("--route-decision")
    model_usage_check.add_argument("--budget-targets")


def _add_tier_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    tier = subparsers.add_parser("tier", help="SDD tier commands")
    tier_sub = tier.add_subparsers(dest="tier_command", required=True)
    tier_resolve = tier_sub.add_parser("resolve")
    tier_resolve.add_argument("--request", required=True)


def _add_specification_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    specification = subparsers.add_parser("specification", help="specification commands")
    specification_sub = specification.add_subparsers(dest="specification_command", required=True)
    specification_check = specification_sub.add_parser("check")
    specification_check.add_argument("--specification", required=True)


def _add_plan_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    plan = subparsers.add_parser("plan", help="plan commands")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_check = plan_sub.add_parser("check")
    plan_check.add_argument("--manifest", required=True)
    plan_check.add_argument("--lock")
    acceptance_check = plan_sub.add_parser("acceptance-check")
    acceptance_check.add_argument("--manifest", required=True)
    acceptance_check.add_argument("--acceptance", required=True)


def _add_task_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    task = subparsers.add_parser("task", help="task commands")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_compile = task_sub.add_parser("compile")
    task_compile.add_argument("--manifest", required=True)
    task_compile.add_argument("--out-dir")
    task_compile.add_argument("--write", action="store_true")
