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
from agent_lifecycle.compiler import build_phase_packet
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.phase_packet_schemas import (
    IMPLEMENTATION_PAYLOAD_SCHEMA,
    REMEDIATION_PAYLOAD_SCHEMA,
    TASK_AUDIT_PAYLOAD_SCHEMA,
)
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.quality import build_validation_selection
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
    continue_workflow_batch,
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
    if args.workflow_command == "validation-select":
        return _dispatch_validation_select(args, state_path)
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
        return _dispatch_workflow_continue(args, state_path)
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
            release_full_receipt_path=args.release_full_receipt,
            review_mesh_quorum_paths=args.review_mesh_quorum,
            reason=args.reason,
        )
        maybe_emit_workflow_progress_hook(args, command="workflow finalize", state_path=state_path)
        return payload
    return _dispatch_workflow_task(args, state_path)


def _dispatch_workflow_task(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    if args.workflow_command == "task-snapshot":
        return _dispatch_task_snapshot(args, state_path)
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


def _dispatch_task_snapshot(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    packet_args = (args.manifest, args.lock, args.phase_packet_purpose, args.phase_packet_out)
    packet_requested = any(value is not None for value in packet_args)
    if packet_requested and not all(value is not None for value in packet_args):
        raise LifecycleError(
            "phase-packet-required-fact-missing",
            "task snapshot phase packet requires --manifest, --lock, --phase-packet-purpose and --phase-packet-out",
        )
    state = read_json_object(state_path, label="workflow state") if packet_requested else None
    task = _state_task(state, args.task) if isinstance(state, dict) else None
    if args.phase_packet_purpose == "TASK_AUDIT" and isinstance(task, dict) and task.get("status") == "VERIFYING":
        assert state is not None
        payload = _result_bound_task_change_set(state, task)
    else:
        payload = build_current_task_change_set(state_path, task_id=args.task)
    if args.out:
        write_json_create(Path(args.out), payload)
    if packet_requested:
        assert state is not None
        manifest = read_json_object(Path(args.manifest), label="plan manifest")
        lock = read_json_object(Path(args.lock), label="plan lock")
        verify_plan_lock(manifest, lock)
        packet = _build_task_phase_packet(
            manifest=manifest,
            lock=lock,
            state=state,
            task_id=args.task,
            purpose=args.phase_packet_purpose,
            snapshot=payload,
        )
        write_json_create(Path(args.phase_packet_out), packet)
    return payload


def _result_bound_task_change_set(state: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    evidence = task.get("resultChangeSetEvidence")
    if not isinstance(evidence, dict):
        raise LifecycleError("phase-packet-required-fact-missing", "task audit result change-set evidence is missing")
    required = ("provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash")
    if any(not isinstance(evidence.get(field), str) or not evidence[field] for field in required):
        raise LifecycleError(
            "phase-packet-required-fact-missing", "task audit result change-set evidence is incomplete"
        )
    return {
        **evidence,
        "runId": state.get("runId"),
        "packageId": state.get("packageId"),
        "taskId": task.get("id"),
        "attempt": task.get("attempt"),
        "planDigest": state.get("planDigest"),
        "sourceRevision": state.get("sourceRevision"),
        "readOnly": True,
        "stateWritten": False,
        "modelCallsStarted": False,
        "productionPromotionClaimed": False,
        "claim": {
            "schemaVersion": "agent-task-change-set-claim.v1",
            **{key: evidence[key] for key in required},
        },
    }


def _dispatch_validation_select(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    state = read_json_object(state_path, label="workflow state")
    task = _state_task(state, args.task)
    snapshot = read_json_object(Path(args.snapshot), label="task snapshot")
    if snapshot.get("taskId") != task.get("id"):
        raise LifecycleError("task-snapshot-lineage-mismatch", "task snapshot does not match the requested task")
    payload = build_validation_selection(
        manifest=read_json_object(Path(args.manifest), label="plan manifest"),
        lock=read_json_object(Path(args.lock), label="plan lock"),
        state=state,
        snapshot=snapshot,
        repository_root=Path.cwd(),
    )
    if args.out:
        write_json_create(Path(args.out), payload)
    return payload


def _build_task_phase_packet(
    *,
    manifest: dict[str, Any],
    lock: dict[str, Any],
    state: dict[str, Any],
    task_id: str,
    purpose: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    task = _state_task(state, task_id)
    workstream = _manifest_workstream(manifest, task_id)
    plan_digest = canonical_digest(manifest)
    if state.get("planDigest") != plan_digest:
        raise LifecycleError("phase-packet-required-fact-missing", "workflow state plan lineage is stale")
    attempt = task.get("attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise LifecycleError("phase-packet-required-fact-missing", "task attempt is required")
    writes = _task_scope(manifest, workstream, task, "writes")
    read_only = _task_scope(manifest, workstream, task, "readOnly")
    forbidden = _task_scope(manifest, workstream, task, "forbiddenWrites")
    acceptance = _task_acceptance(manifest, workstream)
    evidence = _task_evidence(workstream)
    active_blockers = _task_active_blockers(state, task)
    payload = _task_phase_payload(
        purpose=purpose,
        manifest=manifest,
        task=task,
        task_id=task_id,
        attempt=attempt,
        snapshot=snapshot,
        writes=writes,
        read_only=read_only,
        forbidden=forbidden,
        acceptance=acceptance,
        evidence=evidence,
        active_blockers=active_blockers,
    )
    state_revision = state.get("stateRevision")
    source_revision = state.get("sourceRevision")
    if not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
        raise LifecycleError("phase-packet-required-fact-missing", "workflow state revision is required")
    if not isinstance(source_revision, str) or not source_revision:
        raise LifecycleError("phase-packet-required-fact-missing", "workflow source revision is required")
    return build_phase_packet(
        purpose=purpose,
        payload=payload,
        plan_digest=plan_digest,
        plan_lock_digest=canonical_digest(lock),
        state_revision=state_revision,
        source_revision=source_revision,
        write_scope_digest=canonical_digest({"writes": writes, "readOnly": read_only, "forbiddenWrites": forbidden}),
        acceptance_digest=canonical_digest(acceptance),
        evidence_digest=canonical_digest(evidence),
        active_blocker_ids=active_blockers,
    )


def _task_phase_payload(
    *,
    purpose: str,
    manifest: dict[str, Any],
    task: dict[str, Any],
    task_id: str,
    attempt: int,
    snapshot: dict[str, Any],
    writes: list[str],
    read_only: list[str],
    forbidden: list[str],
    acceptance: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    active_blockers: list[str],
) -> dict[str, Any]:
    common = {
        "taskId": task_id,
        "attempt": attempt,
        "writes": writes,
        "readOnly": read_only,
        "forbiddenWrites": forbidden,
        "acceptanceCriteria": acceptance,
        "activeBlockerIds": active_blockers,
    }
    if purpose == "IMPLEMENTATION":
        packet = task.get("packet")
        task_packet_digest = packet.get("sha256") if isinstance(packet, dict) else None
        return {
            "schemaVersion": IMPLEMENTATION_PAYLOAD_SCHEMA,
            **common,
            "taskPacketDigest": task_packet_digest,
            "evidenceRequirements": evidence,
        }
    changed_paths = _task_strings(snapshot.get("changedFiles"))
    if purpose == "TASK_AUDIT":
        result = task.get("result")
        result_digest = result.get("sha256") if isinstance(result, dict) else None
        return {
            "schemaVersion": TASK_AUDIT_PAYLOAD_SCHEMA,
            **common,
            "resultDigest": result_digest,
            "changeSetDigest": snapshot.get("snapshotHash"),
            "changedPaths": changed_paths,
            "reviewRequirements": {
                "independentRequired": True,
                "minimumVerdict": "ACCEPTED",
                "requiredReviewerIds": _required_reviewer_ids(task),
            },
            "evidenceReferences": [item["id"] for item in evidence],
        }
    if purpose != "REMEDIATION":
        raise LifecycleError("phase-packet-required-fact-missing", "phase packet purpose is unsupported")
    history = task.get("attemptHistory")
    prior = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else None
    prior_result = prior.get("result") if isinstance(prior, dict) else None
    prior_review = prior.get("review") if isinstance(prior, dict) else None
    return {
        "schemaVersion": REMEDIATION_PAYLOAD_SCHEMA,
        **common,
        "priorResultDigest": prior_result.get("sha256") if isinstance(prior_result, dict) else None,
        "priorReviewDigest": prior_review.get("sha256") if isinstance(prior_review, dict) else None,
        "changedPaths": changed_paths,
        "openFindingIds": _task_strings(task.get("remediationFindingIds")),
        "remainingAttempts": max(1, _max_task_attempts(manifest) - attempt + 1),
        "evidenceRequirements": evidence,
    }


def _state_task(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    tasks = state.get("tasks")
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict) and task.get("id") == task_id:
                return task
    raise LifecycleError("task-not-found", "workflow task does not exist", {"taskId": task_id})


def _manifest_workstream(manifest: dict[str, Any], task_id: str) -> dict[str, Any]:
    workstreams = manifest.get("workstreams")
    if isinstance(workstreams, list):
        for workstream in workstreams:
            if isinstance(workstream, dict) and workstream.get("id") == task_id:
                return workstream
    raise LifecycleError("phase-packet-required-fact-missing", "manifest workstream is missing", {"taskId": task_id})


def _task_acceptance(manifest: dict[str, Any], workstream: dict[str, Any]) -> list[dict[str, Any]]:
    acceptance = manifest.get("acceptance")
    criteria = acceptance.get("criteria") if isinstance(acceptance, dict) else []
    criteria = criteria if isinstance(criteria, list) else []
    by_id = {item.get("id"): item for item in criteria if isinstance(item, dict) and isinstance(item.get("id"), str)}
    return [dict(by_id.get(item, {"id": item})) for item in _task_strings(workstream.get("acceptanceIds"))]


def _task_evidence(workstream: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": item, "required": True} for item in _task_strings(workstream.get("evidenceIds"))]


def _task_scope(manifest: dict[str, Any], workstream: dict[str, Any], task: dict[str, Any], field: str) -> list[str]:
    return sorted(
        set(_task_strings(manifest.get(field)) + _task_strings(workstream.get(field)) + _task_strings(task.get(field)))
    )


def _task_active_blockers(state: dict[str, Any], task: dict[str, Any]) -> list[str]:
    blockers = _task_strings(task.get("remediationFindingIds"))
    blocker = state.get("blocker")
    if isinstance(blocker, dict):
        value = blocker.get("id") or blocker.get("code")
        if isinstance(value, str) and value:
            blockers.append(value)
    return sorted(set(blockers))


def _required_reviewer_ids(task: dict[str, Any]) -> list[str]:
    reviewer = task.get("reviewer")
    if isinstance(reviewer, str) and reviewer:
        return [reviewer]
    if isinstance(reviewer, dict) and isinstance(reviewer.get("id"), str) and reviewer["id"]:
        return [reviewer["id"]]
    return []


def _max_task_attempts(manifest: dict[str, Any]) -> int:
    orchestration = manifest.get("orchestration")
    value = orchestration.get("maxTaskAttempts") if isinstance(orchestration, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 1


def _task_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def _require_args(args: argparse.Namespace, names: list[str], *, mode: str) -> None:
    missing = [name.replace("_", "-") for name in names if not getattr(args, name, None)]
    if missing:
        raise LifecycleError("missing-cli-argument", f"{mode} requires arguments", {"missing": missing})


def _dispatch_workflow_continue(args: argparse.Namespace, state_path: Path) -> dict[str, Any]:
    batch_options = (args.input_bundle, args.max_transitions, args.max_io_bytes, args.resume_receipt)
    if not args.until_blocked:
        if any(value is not None for value in batch_options):
            raise LifecycleError(
                "continuation-batch-option-conflict",
                "bounded continuation options require --until-blocked",
            )
        if not args.operation_id:
            raise LifecycleError(
                "continuation-one-step-operation-id-required",
                "one-step continuation requires --operation-id",
            )
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
    if not args.apply:
        raise LifecycleError(
            "continuation-batch-apply-required",
            "bounded continuation requires --apply",
        )
    if (
        args.operation_id is not None
        or args.projected_state_revision is not None
        or args.projected_action_digest is not None
    ):
        raise LifecycleError(
            "continuation-batch-option-conflict",
            "bounded continuation cannot use singular operation or projection options",
        )
    if _continuation_inputs(args):
        raise LifecycleError(
            "continuation-batch-option-conflict",
            "bounded continuation inputs must come from --input-bundle",
        )
    required = ("lock", "input_bundle", "max_transitions", "max_io_bytes", "out")
    missing = [name.replace("_", "-") for name in required if getattr(args, name) is None or getattr(args, name) == ""]
    if missing:
        raise LifecycleError(
            "continuation-batch-arguments-required",
            "bounded continuation requires explicit lock, bundle, caps and output",
            {"missing": missing},
        )
    if args.max_transitions <= 0 or args.max_io_bytes <= 0:
        raise LifecycleError(
            "continuation-batch-cap-invalid",
            "bounded continuation caps must be positive",
        )
    return continue_workflow_batch(
        state_path=state_path,
        manifest_path=Path(args.manifest),
        lock_path=Path(args.lock),
        input_bundle_path=args.input_bundle,
        output_path=args.out,
        max_transitions=args.max_transitions,
        max_io_bytes=args.max_io_bytes,
        expected_revision=args.expected_revision,
        source_revision=args.source_revision,
        reason=args.reason,
        resume_receipt_path=args.resume_receipt,
    )


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
