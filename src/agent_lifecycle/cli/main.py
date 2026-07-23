"""Thin root CLI dispatcher for Agent Lifecycle Kit."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from agent_lifecycle import __version__
from agent_lifecycle.audit import build_ownership_report
from agent_lifecycle.audit.ownership import report_has_category
from agent_lifecycle.changesets import changed_files
from agent_lifecycle.compiler import compile_task_packets
from agent_lifecycle.contracts import LifecycleError, canonical_bytes, read_json_object
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.context import check_context, load_context_profile, render_context
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.model_routing import (
    resolve_model_route,
    validate_host_model_profile,
    validate_model_routing_profile,
    validate_usage_receipt,
)
from agent_lifecycle.neutrality.cli import main as neutrality_main
from agent_lifecycle.planning import resolve_sdd_tier, validate_plan_manifest
from agent_lifecycle.specification import validate_specification
from agent_lifecycle.workflow import (
    accept_task,
    adopt_plan,
    block_run,
    commit_task_result,
    finalize_run,
    next_action,
    resolve_blocker,
    start_execution,
    start_task,
    status,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args, remainder = parser.parse_known_args(argv)
    if args.command == "neutrality":
        return neutrality_main(remainder)
    try:
        payload = _dispatch(args, remainder)
    except LifecycleError as exc:
        _write(exc.to_json())
        return 2
    if payload is None:
        return 0
    _write(payload)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-lifecycle")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version", help="print package version as compact JSON")
    schema = subparsers.add_parser("schema", help="inspect bundled JSON schemas")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    schema_sub.add_parser("list")
    show = schema_sub.add_parser("show")
    show.add_argument("schema_id")
    subparsers.add_parser("neutrality", help="run neutrality subcommands")
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
    audit = subparsers.add_parser("audit", help="audit commands")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    ownership = audit_sub.add_parser("ownership")
    ownership.add_argument("--manifest", required=True)
    ownership.add_argument("--base", required=False)
    ownership.add_argument("--path", action="append", default=[])
    ownership.add_argument("--fail-on-unowned", action="store_true")
    ownership.add_argument("--fail-on-forbidden", action="store_true")
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
    tier = subparsers.add_parser("tier", help="SDD tier commands")
    tier_sub = tier.add_subparsers(dest="tier_command", required=True)
    tier_resolve = tier_sub.add_parser("resolve")
    tier_resolve.add_argument("--request", required=True)

    specification = subparsers.add_parser("specification", help="specification commands")
    specification_sub = specification.add_subparsers(dest="specification_command", required=True)
    specification_check = specification_sub.add_parser("check")
    specification_check.add_argument("--specification", required=True)

    plan = subparsers.add_parser("plan", help="plan commands")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    plan_check = plan_sub.add_parser("check")
    plan_check.add_argument("--manifest", required=True)
    plan_check.add_argument("--lock")

    task = subparsers.add_parser("task", help="task commands")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_compile = task_sub.add_parser("compile")
    task_compile.add_argument("--manifest", required=True)
    task_compile.add_argument("--out-dir")
    task_compile.add_argument("--write", action="store_true")

    for name in ("adapter", "conformance"):
        subparsers.add_parser(name, help=f"{name} commands")
    return parser


def _dispatch(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any] | None:
    if args.command == "version":
        return {"schemaVersion": "agent-lifecycle-version.v1", "version": __version__}
    if args.command == "schema":
        if args.schema_command == "list":
            return list_schemas()
        if args.schema_command == "show":
            return get_schema(args.schema_id)
    if args.command == "workflow":
        return _dispatch_workflow(args)
    if args.command == "audit":
        return _dispatch_audit(args)
    if args.command == "context":
        return _dispatch_context(args)
    if args.command == "model":
        return _dispatch_model(args)
    if args.command == "tier":
        return _dispatch_tier(args)
    if args.command == "specification":
        return _dispatch_specification(args)
    if args.command == "plan":
        return _dispatch_plan(args)
    if args.command == "task":
        return _dispatch_task(args)
    raise LifecycleError(
        "command-not-implemented",
        f"{args.command} command group is reserved but not implemented in this build",
    )


def _dispatch_workflow(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    state_path = Path(args.state)
    if args.workflow_command == "status":
        return status(state_path, full=args.full)
    if args.workflow_command == "next":
        return next_action(status(state_path, full=True)["state"])
    if args.workflow_command == "adopt-plan":
        return adopt_plan(
            state_path,
            manifest_path=Path(args.manifest),
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            reset_tasks=args.reset_tasks,
            preserve_accepted_compatible=args.preserve_accepted_compatible,
            start_mode=args.start_mode,
            authorized_by=args.authorized_by,
        )
    if args.workflow_command == "run-start":
        return start_execution(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            reason=args.reason,
        )
    if args.workflow_command == "finalize":
        return finalize_run(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            final_audit_path=args.final_audit,
            proof_path=args.proof,
            reason=args.reason,
        )
    return _dispatch_workflow_task(args, state_path)


def _dispatch_workflow_task(args: argparse.Namespace, state_path: Any) -> dict[str, Any]:
    if args.workflow_command == "block":
        return block_run(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            blocker_code=args.blocker_code,
            reason=args.reason,
        )
    if args.workflow_command == "resolve":
        return resolve_blocker(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            reason=args.reason,
        )
    if args.workflow_command == "task-start":
        return start_task(
            state_path,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            reason=args.reason,
        )
    if args.workflow_command == "task-result":
        return commit_task_result(
            state_path,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            result_path=args.result,
            model_usage_receipt_path=args.model_usage_receipt,
            budget_targets_path=args.budget_targets,
            reason=args.reason,
        )
    if args.workflow_command == "task-accept":
        return accept_task(
            state_path,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            review_path=args.review,
            reason=args.reason,
        )
    raise LifecycleError("command-not-implemented", "workflow command is not implemented")


def _dispatch_audit(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    paths = args.path or changed_files(Path.cwd(), base=args.base)
    report = build_ownership_report(Path(args.manifest), paths, base=args.base)
    if args.fail_on_forbidden and report_has_category(report, {"forbidden"}):
        raise LifecycleError(
            "forbidden-write-detected",
            "ownership report contains forbidden writes",
            report["summary"],
        )
    if args.fail_on_unowned and report_has_category(report, {"unowned"}):
        raise LifecycleError(
            "unowned-write-detected",
            "ownership report contains unowned writes",
            report["summary"],
        )
    return report


def _dispatch_context(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    if args.context_command == "profile-check":
        return load_context_profile(Path(args.profile))
    if args.context_command == "check":
        result = check_context(
            Path(args.profile),
            Path(args.task_packet),
            Path(args.summary),
            latest_user=args.latest_user,
            window=args.target_window,
        )
        return _require_context_pass(result)
    if args.context_command == "render":
        from agent_lifecycle.contracts import read_json_object

        profile = read_json_object(Path(args.profile), label="context profile")
        load_context_profile(Path(args.profile))
        result = render_context(
            profile,
            read_json_object(Path(args.task_packet), label="task packet"),
            read_json_object(Path(args.summary), label="state summary"),
            latest_user=args.latest_user,
            window=args.target_window,
        )
        return _require_context_pass(result)
    raise LifecycleError("command-not-implemented", "context command is not implemented")


def _dispatch_model(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    if args.model_command == "profile-check":
        profile = read_json_object(Path(args.profile), label="model profile")
        if args.type == "routing":
            return validate_model_routing_profile(profile)
        if args.type == "host":
            return validate_host_model_profile(profile)
        if profile.get("schemaVersion") == "agent-lifecycle-host-model-profile.v1":
            return validate_host_model_profile(profile)
        return validate_model_routing_profile(profile)
    if args.model_command == "route":
        routing_profile = read_json_object(Path(args.profile), label="model routing profile")
        host_profile = read_json_object(Path(args.host_profile), label="host model profile") if args.host_profile else None
        request = read_json_object(Path(args.request), label="model route request")
        return resolve_model_route(request, routing_profile, host_profile=host_profile)
    if args.model_command == "usage-check":
        receipt = read_json_object(Path(args.receipt), label="model usage receipt")
        decision = read_json_object(Path(args.route_decision), label="model route decision") if args.route_decision else None
        targets = read_json_object(Path(args.budget_targets), label="budget targets") if args.budget_targets else None
        result = validate_usage_receipt(receipt, budget_targets=targets, route_decision=decision)
        if result["status"] == "FAIL":
            raise LifecycleError("model-usage-validation-failed", "model usage receipt validation failed", {"validation": result})
        return result
    raise LifecycleError("command-not-implemented", "model command is not implemented")


def _require_context_pass(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") == "FAIL":
        raise LifecycleError(
            "context-overflow",
            "compact context exceeds target window",
            {"receipt": result.get("receipt")},
        )
    return result


def _dispatch_tier(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    if args.tier_command == "resolve":
        return resolve_sdd_tier(read_json_object(Path(args.request), label="tier request"))
    raise LifecycleError("command-not-implemented", "tier command is not implemented")


def _dispatch_specification(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    if args.specification_command == "check":
        return validate_specification(read_json_object(Path(args.specification), label="specification"))
    raise LifecycleError("command-not-implemented", "specification command is not implemented")


def _dispatch_plan(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    if args.plan_command == "check":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        lock = read_json_object(Path(args.lock), label="plan lock") if args.lock else None
        return {
            "schemaVersion": "agent-plan-check.v1",
            "manifest": validate_plan_manifest(manifest),
            "lock": verify_plan_lock(manifest, lock) if lock else None,
        }
    raise LifecycleError("command-not-implemented", "plan command is not implemented")


def _dispatch_task(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    if args.task_command == "compile":
        result = compile_task_packets(
            Path(args.manifest),
            out_dir=Path(args.out_dir) if args.out_dir else None,
            write=args.write,
        )
        return {"schemaVersion": "agent-task-packet-compile-result.v1", **result}
    raise LifecycleError("command-not-implemented", "task command is not implemented")


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
