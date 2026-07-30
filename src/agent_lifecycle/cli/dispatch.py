"""Root CLI dispatch handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle import __version__
from agent_lifecycle.audit import build_ownership_report
from agent_lifecycle.audit.ownership import report_has_category
from agent_lifecycle.changesets import changed_files
from agent_lifecycle.compiler import compile_task_packets
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.context import check_context, load_context_profile, render_context
from agent_lifecycle.diagnostics import build_readiness_report
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.cli.adapter import dispatch_adapter
from agent_lifecycle.cli.followup import dispatch_followup
from agent_lifecycle.cli.worktree import dispatch_worktree
from agent_lifecycle.goal import build_objective_snapshot, update_goal_record, validate_goal_record
from agent_lifecycle.model_routing import (
    resolve_model_route,
    validate_host_model_profile,
    validate_model_routing_profile,
    validate_usage_receipt,
)
from agent_lifecycle.planning import (
    resolve_sdd_tier,
    validate_acceptance_checklist,
    validate_plan_manifest,
)
from agent_lifecycle.runner import (
    build_runner_snapshot,
    initialize_runner_state,
    load_runner_policy,
    load_runner_state,
    request_runner_stop,
    resume_runner,
    transition_runner,
    validate_runner_state,
)
from agent_lifecycle.runner.core import write_runner_state, write_runner_state_create
from agent_lifecycle.specification import validate_specification
from agent_lifecycle.workflow import (
    accept_task,
    adopt_plan,
    apply_budget_decision,
    block_run,
    commit_task_result,
    finalize_run,
    next_action,
    pause_for_budget_decision,
    resolve_blocker,
    start_execution,
    start_task,
    status,
    validate_budget_exceeded_policy,
)


def dispatch(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any] | None:
    if args.command == "version":
        return {"schemaVersion": "agent-lifecycle-version.v1", "version": __version__}
    if args.command == "schema":
        if args.schema_command == "list":
            return list_schemas()
        if args.schema_command == "show":
            return get_schema(args.schema_id)
    if args.command == "diagnose":
        return build_readiness_report(
            project_root=Path(args.project_root),
            adapter_paths=[Path(item) for item in args.adapter] if args.adapter else None,
            include_install_plans=not args.no_install_plans,
            include_host_probes=args.include_host_probes,
            timeout_seconds=args.timeout_seconds,
            max_host_probes=args.max_host_probes,
            context_profile=Path(args.context_profile) if args.context_profile else None,
            model_profile=Path(args.model_profile) if args.model_profile else None,
            adapter_baseline=Path(args.adapter_baseline) if args.adapter_baseline else None,
        )
    if args.command == "workflow":
        return _dispatch_workflow(args)
    if args.command == "audit":
        return _dispatch_audit(args)
    if args.command == "context":
        return _dispatch_context(args)
    if args.command == "goal":
        return _dispatch_goal(args)
    if args.command == "followup":
        return dispatch_followup(args)
    if args.command == "worktree":
        return dispatch_worktree(args)
    if args.command == "model":
        return _dispatch_model(args)
    if args.command == "runner":
        return _dispatch_runner(args)
    if args.command == "tier":
        return _dispatch_tier(args)
    if args.command == "specification":
        return _dispatch_specification(args)
    if args.command == "plan":
        return _dispatch_plan(args)
    if args.command == "task":
        return _dispatch_task(args)
    if args.command == "adapter":
        return dispatch_adapter(args)
    raise LifecycleError(
        "command-not-implemented",
        f"{args.command} command group is reserved but not implemented in this build",
    )


def _dispatch_workflow(args: argparse.Namespace) -> dict[str, Any]:
    if args.workflow_command == "budget-policy-check":
        return validate_budget_exceeded_policy(read_json_object(Path(args.policy), label="budget policy"))
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
            goal_record_path=args.goal_record,
            follow_up_register_path=args.follow_up_register,
            reason=args.reason,
        )
    return _dispatch_workflow_task(args, state_path)


def _dispatch_workflow_task(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
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
    if args.workflow_command == "budget-decision":
        if args.action:
            _require_args(args, ["decision_receipt", "receipt"], mode="budget-decision apply")
            return apply_budget_decision(
                state_path,
                task_id=args.task,
                operation_id=args.operation_id,
                expected_revision=args.expected_revision,
                source_revision=args.source_revision,
                decision_receipt_path=args.decision_receipt,
                action=args.action,
                applied_receipt_path=args.receipt,
                route_decision_path=args.route_decision,
                split_packet_path=args.split_packet,
                cap_deltas_path=args.cap_deltas,
                operator_identity_hash=args.operator_identity_hash,
                reason=args.reason,
            )
        _require_args(args, ["model_usage_receipt", "budget_policy", "receipt"], mode="budget-decision pause")
        return pause_for_budget_decision(
            state_path,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            usage_receipt_path=args.model_usage_receipt,
            budget_policy_path=args.budget_policy,
            decision_receipt_path=args.receipt,
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


def _require_args(args: argparse.Namespace, names: list[str], *, mode: str) -> None:
    missing = [name.replace("_", "-") for name in names if not getattr(args, name, None)]
    if missing:
        raise LifecycleError("missing-cli-argument", f"{mode} requires arguments", {"missing": missing})


def _dispatch_audit(args: argparse.Namespace) -> dict[str, Any]:
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


def _dispatch_goal(args: argparse.Namespace) -> dict[str, Any]:
    record = read_json_object(Path(args.record), label="goal record")
    if args.goal_command == "check":
        state = read_json_object(Path(args.state), label="workflow state") if args.state else None
        return validate_goal_record(record, state=state, require_current=args.current)
    if args.goal_command == "summarize":
        state = read_json_object(Path(args.state), label="workflow state")
        profile = read_json_object(Path(args.profile), label="context profile") if args.profile else None
        return build_objective_snapshot(record, state, profile=profile, window=args.target_window)
    if args.goal_command == "update":
        state = read_json_object(Path(args.state), label="workflow state")
        updated = update_goal_record(
            record,
            state,
            status=args.status,
            reason=args.reason,
            evidence_ids=args.evidence_id,
        )
        if args.out:
            write_json_create(Path(args.out), updated)
        return updated
    raise LifecycleError("command-not-implemented", "goal command is not implemented")


def _dispatch_model(args: argparse.Namespace) -> dict[str, Any]:
    if args.model_command == "profile-check":
        profile = read_json_object(Path(args.profile), label="model profile")
        if args.type == "routing":
            return validate_model_routing_profile(profile)
        if args.type == "host":
            return validate_host_model_profile(profile)
        if profile.get("schemaVersion") in {
            "agent-lifecycle-host-model-profile.v1",
            "agent-host-model-selection-profile.v1",
        }:
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


def _dispatch_runner(args: argparse.Namespace) -> dict[str, Any]:
    runner_path = Path(args.runner)
    if args.runner_command == "start":
        workflow_state = read_json_object(Path(args.state), label="workflow state")
        policy = load_runner_policy(Path(args.policy) if args.policy else None)
        runner_state = initialize_runner_state(
            workflow_state,
            policy=policy,
            operation_id=args.operation_id,
            reason=args.reason,
        )
        write_runner_state_create(runner_path, runner_state)
        return validate_runner_state(runner_state, workflow_state=workflow_state)
    runner_state = load_runner_state(runner_path)
    if args.runner_command == "status":
        workflow_state = read_json_object(Path(args.state), label="workflow state") if args.state else None
        if args.profile:
            if workflow_state is None:
                raise LifecycleError("missing-cli-argument", "runner status with --profile requires --state")
            profile = read_json_object(Path(args.profile), label="context profile")
            return build_runner_snapshot(runner_state, workflow_state, profile=profile, window=args.target_window)
        return validate_runner_state(runner_state, workflow_state=workflow_state)
    workflow_state = read_json_object(Path(args.state), label="workflow state")
    if args.runner_command == "transition":
        request = read_json_object(Path(args.request), label="runner transition request")
        payload = transition_runner(runner_state, workflow_state, request)
        write_runner_state(runner_path, payload["state"])
        return payload["result"]
    if args.runner_command == "stop":
        payload = request_runner_stop(
            runner_state,
            workflow_state,
            operation_id=args.operation_id,
            expected_runner_revision=args.expected_runner_revision,
            reason=args.reason,
        )
        write_runner_state(runner_path, payload["state"])
        return payload["result"]
    if args.runner_command == "resume":
        payload = resume_runner(
            runner_state,
            workflow_state,
            operation_id=args.operation_id,
            expected_runner_revision=args.expected_runner_revision,
            reason=args.reason,
        )
        write_runner_state(runner_path, payload["state"])
        return payload["result"]
    raise LifecycleError("command-not-implemented", "runner command is not implemented")


def _require_context_pass(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") == "FAIL":
        raise LifecycleError(
            "context-overflow",
            "compact context exceeds target window",
            {"receipt": result.get("receipt")},
        )
    return result


def _dispatch_tier(args: argparse.Namespace) -> dict[str, Any]:
    if args.tier_command == "resolve":
        return resolve_sdd_tier(read_json_object(Path(args.request), label="tier request"))
    raise LifecycleError("command-not-implemented", "tier command is not implemented")


def _dispatch_specification(args: argparse.Namespace) -> dict[str, Any]:
    if args.specification_command == "check":
        return validate_specification(read_json_object(Path(args.specification), label="specification"))
    raise LifecycleError("command-not-implemented", "specification command is not implemented")


def _dispatch_plan(args: argparse.Namespace) -> dict[str, Any]:
    if args.plan_command == "check":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        lock = read_json_object(Path(args.lock), label="plan lock") if args.lock else None
        return {
            "schemaVersion": "agent-plan-check.v1",
            "manifest": validate_plan_manifest(manifest),
            "lock": verify_plan_lock(manifest, lock) if lock else None,
        }
    if args.plan_command == "acceptance-check":
        manifest_path = Path(args.manifest)
        acceptance_path = Path(args.acceptance)
        return validate_acceptance_checklist(
            read_json_object(manifest_path, label="plan manifest"),
            acceptance_path.read_text(encoding="utf-8"),
        )
    raise LifecycleError("command-not-implemented", "plan command is not implemented")


def _dispatch_task(args: argparse.Namespace) -> dict[str, Any]:
    if args.task_command == "compile":
        result = compile_task_packets(
            Path(args.manifest),
            out_dir=Path(args.out_dir) if args.out_dir else None,
            write=args.write,
        )
        return {"schemaVersion": "agent-task-packet-compile-result.v1", **result}
    raise LifecycleError("command-not-implemented", "task command is not implemented")
