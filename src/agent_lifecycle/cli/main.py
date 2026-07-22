"""Thin root CLI dispatcher for Agent Lifecycle Kit."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from agent_lifecycle import __version__
from agent_lifecycle.audit import build_ownership_report
from agent_lifecycle.audit.ownership import report_has_category
from agent_lifecycle.changesets import changed_files
from agent_lifecycle.contracts import LifecycleError, canonical_bytes
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.context import check_context, load_context_profile, render_context
from agent_lifecycle.neutrality.cli import main as neutrality_main
from agent_lifecycle.planning import resolve_sdd_tier
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
    tier = subparsers.add_parser("tier", help="SDD tier commands")
    tier_sub = tier.add_subparsers(dest="tier_command", required=True)
    tier_resolve = tier_sub.add_parser("resolve")
    tier_resolve.add_argument("--request", required=True)
    for name in ("specification", "plan", "task", "adapter", "conformance"):
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
    if args.command == "neutrality":
        return_code = neutrality_main(remainder)
        if return_code != 0:
            raise LifecycleError("neutrality-command-failed", "neutrality command failed", {"exitCode": return_code})
        return None
    if args.command == "workflow":
        return _dispatch_workflow(args)
    if args.command == "audit":
        return _dispatch_audit(args)
    if args.command == "context":
        return _dispatch_context(args)
    if args.command == "tier":
        return _dispatch_tier(args)
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
        return check_context(
            Path(args.profile),
            Path(args.task_packet),
            Path(args.summary),
            latest_user=args.latest_user,
            window=args.target_window,
        )
    if args.context_command == "render":
        from agent_lifecycle.contracts import read_json_object

        profile = read_json_object(Path(args.profile), label="context profile")
        load_context_profile(Path(args.profile))
        return render_context(
            profile,
            read_json_object(Path(args.task_packet), label="task packet"),
            read_json_object(Path(args.summary), label="state summary"),
            latest_user=args.latest_user,
            window=args.target_window,
        )
    raise LifecycleError("command-not-implemented", "context command is not implemented")


def _dispatch_tier(args: argparse.Namespace) -> dict[str, Any]:
    from pathlib import Path

    from agent_lifecycle.contracts import read_json_object

    if args.tier_command == "resolve":
        return resolve_sdd_tier(read_json_object(Path(args.request), label="tier request"))
    raise LifecycleError("command-not-implemented", "tier command is not implemented")


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(canonical_bytes(payload).decode("utf-8") + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
