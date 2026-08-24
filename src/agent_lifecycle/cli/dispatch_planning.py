"""Tiering, specification, planning, and task-packet CLI handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.compiler import compile_small_model_packets, compile_task_packets
from agent_lifecycle.contracts import (
    LifecycleError,
    read_json_object,
    write_json_create,
)
from agent_lifecycle.contracts.finding_check_schemas import (
    validate_finding_check_binding,
    validate_finding_check_evidence,
    validate_finding_check_proposal,
)
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.planning import (
    build_plan_delta,
    build_plan_snapshot,
    load_plan_completeness_profile,
    reconcile_plan_snapshot,
    render_plan_handoff,
    require_reconciliation_pass,
    require_repository_references_pass,
    resolve_sdd_tier,
    validate_acceptance_checklist,
    validate_plan_completeness,
    validate_plan_delta,
    validate_plan_manifest,
    validate_repository_references,
)
from agent_lifecycle.planning.verification import (
    build_plan_verification,
    load_verification_inputs,
    require_plan_verification_pass,
)
from agent_lifecycle.policy.proposals import accept_finding_check_proposal, build_finding_check_proposal
from agent_lifecycle.specification import (
    build_completion_gate_receipt,
    validate_specification,
)
from agent_lifecycle.workflow.artifacts import build_finding_check_evidence_artifact


def dispatch_planning(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch plan- and task-oriented command groups."""
    if args.command == "tier":
        return _dispatch_tier(args)
    if args.command == "specification":
        return _dispatch_specification(args)
    if args.command == "plan":
        return _dispatch_plan(args)
    if args.command == "task":
        return _dispatch_task(args)
    raise LifecycleError("command-not-implemented", "planning command is not implemented")


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
            follow_up_register=(
                read_json_object(Path(args.follow_up_register), label="follow-up register")
                if args.follow_up_register
                else None
            ),
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
            load_plan_completeness_profile(Path(args.completeness_profile)) if args.completeness_profile else None
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
    if args.plan_command == "verify":
        manifest_path = Path(args.manifest)
        manifest, lock, acceptance_markdown, workflow_state, package_root = load_verification_inputs(
            manifest_path=manifest_path,
            lock_path=Path(args.lock) if args.lock else None,
            acceptance_path=Path(args.acceptance) if args.acceptance else None,
            state_path=Path(args.state) if args.state else None,
            package_root=Path(args.package_root) if args.package_root else None,
        )
        payload = build_plan_verification(
            manifest,
            manifest_path=manifest_path,
            lock=lock,
            acceptance_markdown=acceptance_markdown,
            workflow_state=workflow_state,
            repository_root=Path(args.repository_root),
            package_root=package_root,
        )
        output_path = args.out or args.evidence
        if output_path:
            write_json_create(Path(output_path), payload)
        return require_plan_verification_pass(payload)
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
        handoff_snapshot = read_json_object(Path(args.snapshot), label="plan snapshot") if args.snapshot else None
        payload = render_plan_handoff(
            manifest,
            snapshot=handoff_snapshot,
            max_workstreams=args.max_workstreams,
            target_tokens=args.target_tokens,
        )
        if payload.get("status") != "PASS":
            raise LifecycleError(
                "plan-handoff-render-failed",
                "plan handoff did not fit the requested limits",
                {"handoff": payload},
            )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.plan_command == "delta":

        def read(value: str | None, label: str) -> dict[str, Any] | None:
            return read_json_object(Path(value), label=label) if value else None

        before = read(args.before, "before plan")
        after = read(args.after, "after plan")
        if before is None or after is None:
            raise LifecycleError("plan-delta-input-required", "before and after plans are required")
        payload = build_plan_delta(
            before,
            after,
            before_snapshot=read(args.before_snapshot, "before plan snapshot"),
            after_snapshot=read(args.after_snapshot, "after plan snapshot"),
            before_lock=read(args.before_lock, "before plan lock"),
            after_lock=read(args.after_lock, "after plan lock"),
            principles=read(args.principles, "project principles"),
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.plan_command in {"delta-check", "delta-validate"}:
        payload = validate_plan_delta(read_json_object(Path(args.delta), label="plan delta"))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.plan_command == "finding-check":
        return _dispatch_finding_check(args)
    raise LifecycleError("command-not-implemented", "plan command is not implemented")


def _dispatch_finding_check(args: argparse.Namespace) -> dict[str, Any]:
    def read(path: str, label: str) -> dict[str, Any]:
        return read_json_object(Path(path), label=label)

    if args.finding_check_command == "propose":
        payload = build_finding_check_proposal(
            finding=read(args.finding, "finding"),
            plan_delta=read(args.delta, "plan delta"),
            check_identity=read(args.check, "check identity"),
            owner=args.owner,
            scope=read(args.scope, "check scope"),
            source_revision=args.source_revision,
            expected_result=args.expected_result,
            proposal_id=args.proposal_id,
        )
    elif args.finding_check_command == "validate":
        if args.binding:
            payload = validate_finding_check_binding(read(args.binding, "finding-check binding"))
        elif args.proposal:
            payload = validate_finding_check_proposal(read(args.proposal, "finding-check proposal"))
        elif args.evidence:
            payload = validate_finding_check_evidence(read(args.evidence, "finding-check evidence"))
        else:
            raise LifecycleError("finding-check-input-required", "binding, proposal or evidence is required")
    elif args.finding_check_command == "accept":
        payload = accept_finding_check_proposal(
            read(args.proposal, "finding-check proposal"), read(args.authorization, "authorization")
        )
    elif args.finding_check_command == "evidence":
        payload = build_finding_check_evidence_artifact(
            read(args.binding, "finding-check binding"),
            result=args.result,
            source_revision=args.source_revision,
            evidence_ids=args.evidence_id,
        )
    elif args.finding_check_command == "transition":
        from agent_lifecycle.contracts.finding_check_schemas import transition_finding_check_binding

        payload = transition_finding_check_binding(
            read(args.binding, "finding-check binding"),
            args.target_status,
            authorization=read(args.authorization, "authorization"),
            evidence=read(args.evidence, "finding-check evidence") if args.evidence else None,
        )
    else:
        raise LifecycleError("command-not-implemented", "finding-check command is not implemented")
    if args.out:
        write_json_create(Path(args.out), payload)
    return payload


def _dispatch_task(args: argparse.Namespace) -> dict[str, Any]:
    if args.task_command == "compile":
        execution_strategy = (
            read_json_object(Path(args.strategy), label="execution strategy") if args.strategy else None
        )
        result = compile_task_packets(
            Path(args.manifest),
            out_dir=Path(args.out_dir) if args.out_dir else None,
            write=args.write,
            execution_strategy=execution_strategy,
        )
        return {"schemaVersion": "agent-task-packet-compile-result.v1", **result}
    if args.task_command == "compile-small":
        adaptive_decision = (
            read_json_object(Path(args.adaptive_decision), label="adaptive lifecycle decision")
            if args.adaptive_decision
            else None
        )
        execution_strategy = (
            read_json_object(Path(args.strategy), label="execution strategy") if args.strategy else None
        )
        result = compile_small_model_packets(
            Path(args.manifest),
            context_profile_path=Path(args.context_profile),
            out_dir=Path(args.out_dir) if args.out_dir else None,
            target_window=args.target_window,
            adaptive_decision=adaptive_decision,
            write=args.write,
            execution_strategy=execution_strategy,
        )
        if result["status"] != "PASS":
            raise LifecycleError(
                "small-model-packet-compile-failed",
                "small-model packet compilation failed",
                {"result": result},
            )
        return result
    raise LifecycleError("command-not-implemented", "task command is not implemented")
