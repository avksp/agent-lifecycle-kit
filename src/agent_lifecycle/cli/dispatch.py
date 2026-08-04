"""Root CLI dispatch handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle import __version__
from agent_lifecycle.audit import (
    build_final_implementation_audit,
    build_implementation_audit_report,
    build_ownership_report,
    require_review_verdict_pass,
    validate_review_verdict,
)
from agent_lifecycle.audit.ownership import report_has_category
from agent_lifecycle.changesets import changed_files
from agent_lifecycle.compiler import compile_small_model_packets, compile_task_packets
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.compatibility import (
    build_contract_policy,
    require_contract_policy_pass,
    validate_contract_policy,
)
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.context import check_context, load_context_profile, render_context
from agent_lifecycle.diagnostics import build_diagnostic_bundle, build_readiness_report
from agent_lifecycle.evidence_index import (
    build_evidence_index,
    require_evidence_index_pass,
    require_evidence_search_pass,
    search_evidence_index,
    validate_evidence_index,
)
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.cli.adapter import dispatch_adapter
from agent_lifecycle.cli.followup import dispatch_followup
from agent_lifecycle.cli.policy import dispatch_policy
from agent_lifecycle.cli.progress_hooks import maybe_emit_workflow_progress_hook, validate_workflow_progress_hook_request
from agent_lifecycle.cli.worktree import dispatch_worktree
from agent_lifecycle.goal import build_objective_snapshot, update_goal_record, validate_goal_record
from agent_lifecycle.imports import (
    external_dialect_registry,
    import_external_dialect,
    import_planning_input,
    require_external_import_pass,
    require_import_validation_pass,
    require_skill_proposal_pass,
    validate_external_import_result,
    validate_import_result,
    validate_skill_improvement_proposal,
)
from agent_lifecycle.model_routing import (
    resolve_model_route,
    validate_host_model_profile,
    validate_model_routing_profile,
    validate_usage_receipt,
)
from agent_lifecycle.metrics import (
    build_quality_cost_signals,
    build_task_outcome_index,
    build_usage_export,
    build_lifecycle_cost_summary,
    build_lifecycle_recommendation_summary,
    generate_lifecycle_cost_report,
    recommend_from_quality_cost_signals,
    recommend_lifecycle_mode,
    require_lifecycle_cost_pass,
    require_lifecycle_recommendation_pass,
    require_usage_export_pass,
    validate_lifecycle_cost_report,
    validate_usage_export,
)
from agent_lifecycle.planning import (
    load_plan_completeness_profile,
    build_plan_snapshot,
    build_task_template_library,
    reconcile_plan_snapshot,
    require_task_template_validation_pass,
    render_plan_handoff,
    require_reconciliation_pass,
    require_repository_references_pass,
    resolve_sdd_tier,
    validate_acceptance_checklist,
    validate_plan_completeness,
    validate_plan_manifest,
    validate_repository_references,
    validate_task_template_library,
)
from agent_lifecycle.quality import (
    build_bug_forensics_recipe_library,
    build_default_quality_pack,
    require_behavior_checks_pass,
    require_bug_forensics_recipe_pass,
    require_quality_pack_pass,
    run_behavior_checks,
    validate_bug_forensics_recipe_library,
    validate_quality_pack,
)
from agent_lifecycle.reporting import (
    build_change_summary_receipt,
    build_lifecycle_progress_view,
    build_lifecycle_progress_watch,
    build_progress_bridge_receipt,
    build_status_view,
    build_workflow_event_feed,
    render_progress_bridge_terminal,
    render_progress_terminal,
    render_usage_export_json,
    render_usage_export_table,
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
from agent_lifecycle.specification import build_completion_gate_receipt, validate_specification
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
    run_managed_lifecycle_step,
    start_execution,
    start_task,
    status,
    validate_budget_exceeded_policy,
)


def dispatch(args: argparse.Namespace, remainder: list[str]) -> dict[str, Any] | str | None:
    if args.command == "version":
        return {"schemaVersion": "agent-lifecycle-version.v1", "version": __version__}
    if args.command == "schema":
        if args.schema_command == "list":
            return list_schemas()
        if args.schema_command == "show":
            return get_schema(args.schema_id)
    if args.command == "contract":
        return _dispatch_contract(args)
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
    if args.command == "diagnostics":
        return _dispatch_diagnostics(args)
    if args.command == "evidence":
        return _dispatch_evidence(args)
    if args.command == "import":
        return _dispatch_import(args)
    if args.command == "quality":
        return _dispatch_quality(args)
    if args.command == "report":
        return _dispatch_report(args)
    if args.command == "policy":
        return dispatch_policy(args)
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
    if args.command == "metrics":
        return _dispatch_metrics(args)
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


def _dispatch_diagnostics(args: argparse.Namespace) -> dict[str, Any]:
    if args.diagnostics_command == "bundle":
        payload = build_diagnostic_bundle(
            project_root=Path(args.project_root),
            artifact_paths=[Path(item) for item in args.artifact],
            max_artifacts=args.max_artifacts,
            max_input_bytes=args.max_input_bytes,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "diagnostics command is not implemented")


def _dispatch_contract(args: argparse.Namespace) -> dict[str, Any]:
    if args.contract_command == "policy":
        payload = build_contract_policy()
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.contract_command == "check":
        policy = read_json_object(Path(args.policy), label="public contract policy") if args.policy else build_contract_policy()
        return require_contract_policy_pass(validate_contract_policy(policy))
    raise LifecycleError("command-not-implemented", "contract command is not implemented")


def _dispatch_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if args.evidence_command == "index":
        payload = build_evidence_index(
            Path(args.project_root),
            list(args.artifact),
            max_artifacts=args.max_artifacts,
            max_input_bytes=args.max_input_bytes,
            target_tokens=args.target_tokens,
        )
        require_evidence_index_pass(validate_evidence_index(payload))
        require_evidence_index_pass(payload)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.evidence_command == "search":
        payload = search_evidence_index(
            read_json_object(Path(args.index), label="evidence index"),
            query=args.query or "",
            max_results=args.max_results,
            target_tokens=args.target_tokens,
        )
        require_evidence_search_pass(payload)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "evidence command is not implemented")


def _dispatch_import(args: argparse.Namespace) -> dict[str, Any]:
    if args.import_command == "profile-list":
        payload = external_dialect_registry()
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.import_command == "plan":
        payload = import_planning_input(
            Path(args.source),
            package_id=args.package_id,
            max_input_bytes=args.max_input_bytes,
            target_tokens=args.target_tokens,
        )
        require_import_validation_pass(validate_import_result(payload))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.import_command == "external":
        payload = import_external_dialect(
            Path(args.source),
            family=args.family,
            profile_id=args.profile,
            package_id=args.package_id,
            max_input_bytes=args.max_input_bytes,
            target_tokens=args.target_tokens,
        )
        require_external_import_pass(validate_external_import_result(payload))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.import_command == "check":
        return require_import_validation_pass(validate_import_result(read_json_object(Path(args.candidate), label="planning import result")))
    if args.import_command == "external-check":
        return require_external_import_pass(validate_external_import_result(read_json_object(Path(args.candidate), label="external dialect import result")))
    if args.import_command == "proposal-check":
        return require_skill_proposal_pass(validate_skill_improvement_proposal(read_json_object(Path(args.proposal), label="skill proposal")))
    raise LifecycleError("command-not-implemented", "import command is not implemented")


def _dispatch_quality(args: argparse.Namespace) -> dict[str, Any]:
    if args.quality_command == "pack-check":
        manifest = read_json_object(Path(args.manifest), label="quality pack") if args.manifest else build_default_quality_pack()
        return require_quality_pack_pass(validate_quality_pack(manifest))
    if args.quality_command == "behavior-check":
        manifest = read_json_object(Path(args.manifest), label="quality pack") if args.manifest else build_default_quality_pack()
        fixtures = [read_json_object(Path(item), label="behavior fixture") for item in args.fixture]
        return require_behavior_checks_pass(run_behavior_checks(manifest, fixtures))
    if args.quality_command == "template-list":
        payload = build_task_template_library()
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.quality_command == "template-check":
        payload = validate_task_template_library(project_root=Path(args.project_root), template_id=args.template_id)
        require_task_template_validation_pass(payload)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.quality_command == "bug-recipe-list":
        payload = build_bug_forensics_recipe_library()
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.quality_command == "bug-recipe-check":
        payload = validate_bug_forensics_recipe_library(recipe_id=args.recipe_id)
        require_bug_forensics_recipe_pass(payload)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "quality command is not implemented")


def _dispatch_report(args: argparse.Namespace) -> dict[str, Any] | str:
    if args.report_command == "status-view":
        payload = build_status_view(
            project_root=Path(args.project_root),
            artifact_paths=[Path(item) for item in args.artifact],
            max_items=args.max_items,
            target_window=args.target_window,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.report_command == "progress-bridge":
        payload = build_progress_bridge_receipt(
            adapter_id=args.adapter,
            support_level=args.support_level,
            hook_point=args.hook_point,
            state_path=Path(args.state),
            usage_receipt_paths=[Path(item) for item in args.usage_receipt],
            change_summary_path=Path(args.change_summary) if args.change_summary else None,
            display_mode=args.display_mode,
            watch=args.watch,
            iterations=args.watch_iterations,
            interval_seconds=args.watch_interval,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        if args.terminal:
            return render_progress_bridge_terminal(payload)
        return payload
    if args.report_command == "event-feed":
        payload = build_workflow_event_feed(state_path=Path(args.state))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.report_command == "progress":
        if args.watch:
            payload = build_lifecycle_progress_watch(
                state_path=Path(args.state),
                usage_receipt_paths=[Path(item) for item in args.usage_receipt],
                change_summary_path=Path(args.change_summary) if args.change_summary else None,
                iterations=args.watch_iterations,
                interval_seconds=args.watch_interval,
            )
        else:
            payload = build_lifecycle_progress_view(
                state_path=Path(args.state),
                usage_receipt_paths=[Path(item) for item in args.usage_receipt],
                change_summary_path=Path(args.change_summary) if args.change_summary else None,
            )
        if args.out:
            write_json_create(Path(args.out), payload)
        if args.terminal:
            return render_progress_terminal(payload)
        return payload
    if args.report_command == "change-summary":
        payload = build_change_summary_receipt(
            project_root=Path(args.project_root),
            base=args.base,
            head=args.head,
            staged=args.staged,
            paths=args.path,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "report command is not implemented")


def _dispatch_workflow(args: argparse.Namespace) -> dict[str, Any]:
    if args.workflow_command == "budget-policy-check":
        return validate_budget_exceeded_policy(read_json_object(Path(args.policy), label="budget policy"))
    state_path = Path(args.state)
    if args.workflow_command == "status":
        return status(state_path, full=args.full)
    if args.workflow_command == "next":
        return next_action(status(state_path, full=True)["state"])
    if args.workflow_command == "run":
        validate_workflow_progress_hook_request(args, command="workflow run")
        payload = run_managed_lifecycle_step(
            state_path=state_path,
            manifest_path=Path(args.manifest),
            lock_path=Path(args.lock) if args.lock else None,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            reason=args.reason,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        maybe_emit_workflow_progress_hook(args, command="workflow run", state_path=state_path)
        return payload
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
        validate_workflow_progress_hook_request(args, command="workflow finalize")
        payload = finalize_run(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            final_audit_path=args.final_audit,
            proof_path=args.proof,
            proof_integrity_path=args.proof_integrity,
            goal_record_path=args.goal_record,
            follow_up_register_path=args.follow_up_register,
            completion_gate_receipt_path=args.completion_gate_receipt,
            final_implementation_audit_path=args.final_implementation_audit,
            reason=args.reason,
        )
        maybe_emit_workflow_progress_hook(args, command="workflow finalize", state_path=state_path)
        return payload
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
        validate_workflow_progress_hook_request(args, command="workflow task-result")
        payload = commit_task_result(
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
        maybe_emit_workflow_progress_hook(args, command="workflow task-result", state_path=state_path)
        return payload
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
        validate_workflow_progress_hook_request(args, command="workflow task-accept")
        payload = accept_task(
            state_path,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            review_path=args.review,
            implementation_audit_path=args.implementation_audit,
            reason=args.reason,
        )
        maybe_emit_workflow_progress_hook(args, command="workflow task-accept", state_path=state_path)
        return payload
    raise LifecycleError("command-not-implemented", "workflow command is not implemented")


def _require_args(args: argparse.Namespace, names: list[str], *, mode: str) -> None:
    missing = [name.replace("_", "-") for name in names if not getattr(args, name, None)]
    if missing:
        raise LifecycleError("missing-cli-argument", f"{mode} requires arguments", {"missing": missing})


def _dispatch_audit(args: argparse.Namespace) -> dict[str, Any]:
    if args.audit_command == "review-check":
        review = read_json_object(Path(args.review), label="task review")
        verdict = review.get("reviewVerdict", review)
        findings = review.get("findings", []) if isinstance(review.get("findings", []), list) else []
        return require_review_verdict_pass(validate_review_verdict(verdict, findings=findings))
    if args.audit_command == "implementation":
        payload = build_implementation_audit_report(
            manifest_path=Path(args.manifest),
            state_path=Path(args.state),
            task_id=args.task,
            result_path=args.result,
            review_path=args.review,
            evidence_paths=args.evidence,
            sandbox_receipt_paths=args.sandbox_receipt,
            changed_paths=args.path or None,
            expected_revision=args.expected_revision,
            base=args.base,
            auditor_id=args.auditor_id,
            auditor_surface=args.auditor_surface,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.audit_command == "final-implementation":
        payload = build_final_implementation_audit(
            manifest_path=Path(args.manifest),
            state_path=Path(args.state),
            report_paths=args.report,
            auditor_id=args.auditor_id,
            auditor_surface=args.auditor_surface,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
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


def _dispatch_metrics(args: argparse.Namespace) -> dict[str, Any]:
    if args.metrics_command == "cost-check":
        report = read_json_object(Path(args.receipt), label="lifecycle cost report")
        return require_lifecycle_cost_pass(validate_lifecycle_cost_report(report))
    if args.metrics_command == "cost-report":
        report = generate_lifecycle_cost_report(
            artifact_paths=[Path(item) for item in args.artifact],
            mode=args.mode,
            root=Path(args.project_root),
        )
        validation = require_lifecycle_cost_pass(validate_lifecycle_cost_report(report))
        report_bytes = write_json_create(Path(args.out), report)
        summary_path = None
        summary_digest = None
        if args.summary_out:
            summary = build_lifecycle_cost_summary(report)
            write_json_create(Path(args.summary_out), summary)
            summary_path = args.summary_out
            summary_digest = canonical_digest(summary)
        return {
            "schemaVersion": "agent-lifecycle-cost-generation.v1",
            "status": validation["status"],
            "reportPath": args.out,
            "reportBytes": len(report_bytes),
            "reportDigest": canonical_digest(report),
            "summaryPath": summary_path,
            "summaryDigest": summary_digest,
            "validation": validation,
            "liveCallsStarted": False,
            "productionPromotionClaimed": False,
        }
    if args.metrics_command == "usage-export":
        export = build_usage_export(
            artifact_paths=[Path(item) for item in args.artifact],
            project_root=Path(args.project_root),
        )
        validation = require_usage_export_pass(validate_usage_export(export))
        rendered = render_usage_export_json(export) if args.format == "json" else render_usage_export_table(export)
        output_path = Path(args.out)
        _write_text_create(output_path, rendered)
        return {
            "schemaVersion": "agent-usage-export-generation.v1",
            "status": validation["status"],
            "format": args.format,
            "outputPath": args.out,
            "outputBytes": len(rendered.encode("utf-8")),
            "exportDigest": canonical_digest(export),
            "validation": validation,
            "liveCallsStarted": False,
            "productionPromotionClaimed": False,
        }
    if args.metrics_command == "outcome-index":
        artifacts = [read_json_object(Path(item), label="outcome artifact") for item in args.artifact]
        payload = build_task_outcome_index(artifacts, source_paths=list(args.artifact))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.metrics_command == "quality-signals":
        payload = build_quality_cost_signals(read_json_object(Path(args.index), label="task outcome index"))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.metrics_command == "recommend":
        reports = [read_json_object(Path(item), label="lifecycle cost report") for item in args.report]
        baseline_profile = read_json_object(Path(args.baseline_profile), label="lifecycle baseline profile")
        recommendation = recommend_lifecycle_mode(
            reports=reports,
            baseline_profile=baseline_profile,
            task_shape=args.task_shape,
            current_mode=args.current_mode,
            sdd_tier=args.sdd_tier,
            risk_flags=args.risk,
        )
        require_lifecycle_recommendation_pass(recommendation)
        if args.out:
            write_json_create(Path(args.out), recommendation)
        if args.summary_out:
            write_json_create(Path(args.summary_out), build_lifecycle_recommendation_summary(recommendation))
        return recommendation
    if args.metrics_command == "learn-recommend":
        signals = read_json_object(Path(args.signals), label="quality-cost signals")
        baseline_profile = read_json_object(Path(args.baseline_profile), label="lifecycle baseline profile")
        recommendation = recommend_from_quality_cost_signals(
            signals=signals,
            baseline_profile=baseline_profile,
            task_shape=args.task_shape,
            current_mode=args.current_mode,
            sdd_tier=args.sdd_tier,
            risk_flags=args.risk,
        )
        require_lifecycle_recommendation_pass(recommendation)
        if args.out:
            write_json_create(Path(args.out), recommendation)
        if args.summary_out:
            write_json_create(Path(args.summary_out), build_lifecycle_recommendation_summary(recommendation))
        return recommendation
    raise LifecycleError("command-not-implemented", "metrics command is not implemented")


def _write_text_create(path: Path, text: str) -> bytes:
    data = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise LifecycleError("output-already-exists", "output artifact already exists", {"path": path.as_posix()}) from exc
    return data


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
    if args.specification_command == "completion-gate":
        gate_input = read_json_object(Path(args.input), label="completion gate input") if args.input else {}
        payload = build_completion_gate_receipt(
            state=read_json_object(Path(args.state), label="workflow state"),
            final_audit=read_json_object(Path(args.final_audit), label="final audit") if args.final_audit else None,
            follow_up_register=read_json_object(Path(args.follow_up_register), label="follow-up register") if args.follow_up_register else None,
            validation_results=gate_input.get("validationResults", []),
            required_validation_ids=gate_input.get("requiredValidationIds", []),
            follow_up_candidates=gate_input.get("followUpCandidates", []),
            regression_signals=gate_input.get("regressionSignals", []),
            risk_flags=gate_input.get("riskFlags", []),
            split_candidates=gate_input.get("splitCandidates", []),
            verifier_id=args.verifier,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "specification command is not implemented")


def _dispatch_plan(args: argparse.Namespace) -> dict[str, Any]:
    if args.plan_command == "check":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        lock = read_json_object(Path(args.lock), label="plan lock") if args.lock else None
        completeness_profile = (
            load_plan_completeness_profile(Path(args.completeness_profile))
            if args.completeness_profile
            else None
        )
        return {
            "schemaVersion": "agent-plan-check.v1",
            "manifest": validate_plan_manifest(
                manifest,
                require_completeness=args.require_completeness,
                completeness_profile=completeness_profile,
            ),
            "lock": verify_plan_lock(manifest, lock) if lock else None,
        }
    if args.plan_command == "completeness-check":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        profile = load_plan_completeness_profile(Path(args.profile)) if args.profile else None
        payload = validate_plan_completeness(manifest, profile=profile)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.plan_command == "acceptance-check":
        manifest_path = Path(args.manifest)
        acceptance_path = Path(args.acceptance)
        return validate_acceptance_checklist(
            read_json_object(manifest_path, label="plan manifest"),
            acceptance_path.read_text(encoding="utf-8"),
        )
    if args.plan_command == "refs-check":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        return require_repository_references_pass(validate_repository_references(manifest))
    if args.plan_command == "snapshot":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        payload = build_plan_snapshot(manifest)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.plan_command == "reconcile":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        snapshot = read_json_object(Path(args.snapshot), label="plan snapshot")
        return require_reconciliation_pass(reconcile_plan_snapshot(snapshot, manifest))
    if args.plan_command == "handoff":
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        snapshot = read_json_object(Path(args.snapshot), label="plan snapshot") if args.snapshot else None
        payload = render_plan_handoff(
            manifest,
            snapshot=snapshot,
            max_workstreams=args.max_workstreams,
            target_tokens=args.target_tokens,
        )
        if payload.get("status") != "PASS":
            raise LifecycleError("plan-handoff-render-failed", "plan handoff did not fit the requested limits", {"handoff": payload})
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "plan command is not implemented")


def _dispatch_task(args: argparse.Namespace) -> dict[str, Any]:
    if args.task_command == "compile":
        result = compile_task_packets(
            Path(args.manifest),
            out_dir=Path(args.out_dir) if args.out_dir else None,
            write=args.write,
        )
        return {"schemaVersion": "agent-task-packet-compile-result.v1", **result}
    if args.task_command == "compile-small":
        adaptive_decision = read_json_object(Path(args.adaptive_decision), label="adaptive lifecycle decision") if args.adaptive_decision else None
        result = compile_small_model_packets(
            Path(args.manifest),
            context_profile_path=Path(args.context_profile),
            out_dir=Path(args.out_dir) if args.out_dir else None,
            target_window=args.target_window,
            adaptive_decision=adaptive_decision,
            write=args.write,
        )
        if result["status"] != "PASS":
            raise LifecycleError("small-model-packet-compile-failed", "small-model packet compilation failed", {"result": result})
        return result
    raise LifecycleError("command-not-implemented", "task command is not implemented")
