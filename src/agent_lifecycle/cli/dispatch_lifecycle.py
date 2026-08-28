"""Workflow and audit CLI dispatch handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.audit import (
    build_final_implementation_audit,
    build_implementation_audit_report,
    build_ownership_report,
    build_package_audit,
    require_package_audit_pass,
    require_review_verdict_pass,
    validate_review_verdict,
)
from agent_lifecycle.audit.ownership import report_has_category
from agent_lifecycle.changesets import changed_files
from agent_lifecycle.cli.progress_hooks import (
    maybe_emit_workflow_progress_hook,
    validate_workflow_progress_hook_request,
)
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
from agent_lifecycle.workflow import (
    accept_task,
    adopt_plan,
    apply_budget_decision,
    apply_final_audit_outcome,
    apply_task_review_outcome,
    authorize_execution,
    block_run,
    commit_task_result,
    continue_workflow,
    finalize_run,
    initialize_workflow_state,
    migrate_workflow_state,
    next_action,
    pause_for_budget_decision,
    pause_for_external_action,
    resolve_blocker,
    resume_external_action,
    rework_task,
    run_workflow_step,
    start_execution,
    start_task,
    status,
    validate_budget_exceeded_policy,
)
from agent_lifecycle.workflow.artifacts import build_current_task_change_set


def dispatch_lifecycle(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch workflow and audit command groups."""
    if args.command == "workflow":
        return _dispatch_workflow(args)
    if args.command == "audit":
        return _dispatch_audit(args)
    raise LifecycleError("command-not-implemented", "lifecycle command is not implemented")


def _dispatch_workflow(args: argparse.Namespace) -> dict[str, Any]:
    if args.workflow_command == "budget-policy-check":
        return validate_budget_exceeded_policy(read_json_object(Path(args.policy), label="budget policy"))
    if args.workflow_command == "init":
        return initialize_workflow_state(
            Path(args.state),
            run_id=args.run_id,
            package_id=args.package_id,
            package_root=args.package_root,
            event_log=args.event_log,
        )
    if args.workflow_command == "state-migrate":
        return migrate_workflow_state(
            Path(args.state),
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
        )
    if args.workflow_command == "migrate-runner-artifact":
        from agent_lifecycle.migration.legacy_runner import convert_legacy_runner_artifact

        return convert_legacy_runner_artifact(
            Path(args.input),
            Path(args.output),
            expected_sha256=args.expected_sha256,
            max_input_bytes=args.max_input_bytes,
        )
    state_path = Path(args.state)
    if args.workflow_command == "status":
        return status(state_path, full=args.full)
    if args.workflow_command == "next":
        return next_action(status(state_path, full=True)["state"])
    if args.workflow_command == "run":
        validate_workflow_progress_hook_request(args, command="workflow run")
        payload = run_workflow_step(
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
    if args.workflow_command == "continue":
        payload = continue_workflow(
            state_path=state_path,
            manifest_path=Path(args.manifest),
            lock_path=Path(args.lock) if args.lock else None,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            reason=args.reason,
            apply=args.apply,
            projected_state_revision=args.projected_state_revision,
            projected_action_digest=args.projected_action_digest,
            inputs=_continuation_inputs(args),
        )
        if args.out:
            write_json_create(Path(args.out), payload)
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
    if args.workflow_command == "authorize":
        return authorize_execution(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            receipt_path=args.receipt,
            reason=args.reason,
        )
    if args.workflow_command in {"external-pause", "pause-external"}:
        return pause_for_external_action(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            action_id=args.action_id,
            receipt_path=args.receipt,
            reason=args.reason,
        )
    if args.workflow_command in {"external-resume", "resume-external"}:
        return resume_external_action(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            receipt_path=args.receipt,
            reason=args.reason,
        )
    if args.workflow_command == "final-audit-outcome":
        validate_workflow_progress_hook_request(args, command="workflow final-audit-outcome")
        payload = apply_final_audit_outcome(
            state_path,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            final_audit_path=args.final_audit,
            verdict=args.verdict,
            task_ids=args.task_id,
            finding_ids=args.finding_id,
            reason=args.reason,
        )
        maybe_emit_workflow_progress_hook(args, command="workflow final-audit-outcome", state_path=state_path)
        return payload
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
            review_mesh_quorum_paths=args.review_mesh_quorum,
            reason=args.reason,
        )
        maybe_emit_workflow_progress_hook(args, command="workflow finalize", state_path=state_path)
        return payload
    return _dispatch_workflow_task(args, state_path)


def _dispatch_workflow_task(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    if args.workflow_command == "task-snapshot":
        payload = build_current_task_change_set(state_path, task_id=args.task)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
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
            risk_profile_path=args.risk_profile,
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
        if args.source_revision:
            payload = apply_task_review_outcome(
                state_path,
                task_id=args.task,
                operation_id=args.operation_id,
                expected_revision=args.expected_revision,
                source_revision=args.source_revision,
                review_path=args.review,
                implementation_audit_path=args.implementation_audit,
                reason=args.reason,
            )
        else:
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
    if args.workflow_command == "task-rework":
        return rework_task(
            state_path,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            review_path=args.review,
            implementation_audit_path=args.implementation_audit,
            finding_ids=args.finding_id,
            reason=args.reason,
        )
    if args.workflow_command == "task-review-apply":
        validate_workflow_progress_hook_request(args, command="workflow task-review-apply")
        payload = apply_task_review_outcome(
            state_path,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
            review_path=args.review,
            finding_ids=args.finding_id,
            implementation_audit_path=args.implementation_audit,
            reason=args.reason,
        )
        maybe_emit_workflow_progress_hook(args, command="workflow task-review-apply", state_path=state_path)
        return payload
    raise LifecycleError("command-not-implemented", "workflow command is not implemented")


def _require_args(args: argparse.Namespace, names: list[str], *, mode: str) -> None:
    missing = [name.replace("_", "-") for name in names if not getattr(args, name, None)]
    if missing:
        raise LifecycleError("missing-cli-argument", f"{mode} requires arguments", {"missing": missing})


def _continuation_inputs(args: argparse.Namespace) -> dict[str, Any]:
    singular = {
        "taskId": args.task,
        "authorizationReceipt": args.authorization_receipt,
        "riskProfile": args.risk_profile,
        "result": args.result,
        "modelUsageReceipt": args.model_usage_receipt,
        "budgetTargets": args.budget_targets,
        "review": args.review,
        "implementationAudit": args.implementation_audit,
        "finalAudit": args.final_audit,
        "verdict": args.verdict,
        "proof": args.proof,
        "proofIntegrity": args.proof_integrity,
        "goalRecord": args.goal_record,
        "followUpRegister": args.follow_up_register,
        "completionGateReceipt": args.completion_gate_receipt,
        "finalImplementationAudit": args.final_implementation_audit,
    }
    inputs = {key: value for key, value in singular.items() if value is not None}
    for key, values in (
        ("findingIds", args.finding_id),
        ("taskIds", args.task_id),
        ("reviewMeshQuorum", args.review_mesh_quorum),
    ):
        if values:
            inputs[key] = values
    return inputs


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
            review_mesh_quorum_paths=args.review_mesh_quorum,
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
    if args.audit_command == "package":
        payload = build_package_audit(
            plan_dir=Path(args.plan_dir),
            state_path=Path(args.state) if args.state else None,
            report_paths=args.report,
            changed_paths=args.path or None,
            base=args.base,
            require_frozen=args.require_frozen,
            require_implementation=args.require_implementation,
            completeness_profile_path=Path(args.completeness_profile) if args.completeness_profile else None,
            auditor_id=args.auditor_id,
            auditor_surface=args.auditor_surface,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        if args.strict:
            require_package_audit_pass(payload)
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
