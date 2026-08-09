"""Contract, evidence, import, quality, and review-mesh CLI handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle import __version__
from agent_lifecycle.contracts import LifecycleError, read_json_object, write_json_create
from agent_lifecycle.contracts.compatibility import (
    build_contract_policy,
    require_contract_policy_pass,
    validate_contract_policy,
)
from agent_lifecycle.contracts.schemas import get_schema, list_schemas
from agent_lifecycle.evidence_index import (
    build_evidence_index,
    require_evidence_index_pass,
    require_evidence_search_pass,
    search_evidence_index,
    validate_evidence_index,
)
from agent_lifecycle.imports import (
    bmad_profile,
    external_dialect_registry,
    import_external_dialect,
    import_markdown_collection,
    import_planning_input,
    openspec_profile,
    require_external_import_pass,
    require_import_validation_pass,
    require_skill_proposal_pass,
    spec_kit_profile,
    spec_kitty_profile,
    validate_external_import_result,
    validate_import_result,
    validate_skill_improvement_proposal,
)
from agent_lifecycle.planning import (
    build_task_template_library,
    require_task_template_validation_pass,
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
from agent_lifecycle.review_mesh import (
    build_quorum_from_synthesis,
    build_review_mesh_assignment_packet,
    build_review_mesh_profile,
    import_review_mesh_result,
    list_review_mesh_operator_templates,
    parse_reviewer_spec,
    prepare_review_mesh_operator_packets,
    recommend_review_mesh_for_intake,
    recommend_review_mesh_for_plan_manifest,
    recommend_review_mesh_for_text,
    require_review_mesh_profile_pass,
    require_review_mesh_recommendation_pass,
    source_from_handoff,
    source_from_intake,
    source_from_manifest,
    synthesize_review_mesh_results,
    validate_review_mesh_profile,
    validate_review_mesh_recommendation,
)


def dispatch_contracts(args: argparse.Namespace) -> dict[str, Any]:
    """Dispatch schema, contract, evidence, import, quality, and review commands."""
    if args.command == "version":
        return {"schemaVersion": "agent-lifecycle-version.v1", "version": __version__}
    if args.command == "schema":
        if args.schema_command == "list":
            return list_schemas()
        if args.schema_command == "show":
            return get_schema(args.schema_id)
        raise LifecycleError("command-not-implemented", "schema command is not implemented")
    if args.command == "contract":
        return _dispatch_contract(args)
    if args.command == "evidence":
        return _dispatch_evidence(args)
    if args.command == "import":
        return _dispatch_import(args)
    if args.command == "quality":
        return _dispatch_quality(args)
    if args.command == "review-mesh":
        return _dispatch_review_mesh(args)
    raise LifecycleError("command-not-implemented", "contract command is not implemented")


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
        source = Path(args.source)
        dialect_profile = _planning_import_profile(
            args.dialect,
            max_input_bytes=args.max_input_bytes,
            target_tokens=args.target_tokens,
        )
        if source.is_dir() or dialect_profile is not None:
            payload = import_markdown_collection(
                source,
                package_id=args.package_id,
                max_input_bytes=args.max_input_bytes,
                target_tokens=args.target_tokens,
                max_files=args.max_files,
                dialect_profile=dialect_profile,
            )
        else:
            payload = import_planning_input(
                source,
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
        return require_import_validation_pass(
            validate_import_result(read_json_object(Path(args.candidate), label="planning import result"))
        )
    if args.import_command == "external-check":
        return require_external_import_pass(
            validate_external_import_result(read_json_object(Path(args.candidate), label="external dialect import result"))
        )
    if args.import_command == "proposal-check":
        return require_skill_proposal_pass(
            validate_skill_improvement_proposal(read_json_object(Path(args.proposal), label="skill proposal"))
        )
    raise LifecycleError("command-not-implemented", "import command is not implemented")


def _planning_import_profile(
    dialect: str | None,
    *,
    max_input_bytes: int,
    target_tokens: int,
) -> dict[str, Any] | None:
    if dialect is None:
        return None
    builders = {
        "openspec": openspec_profile,
        "spec-kit": spec_kit_profile,
        "bmad": bmad_profile,
        "spec-kitty": spec_kitty_profile,
    }
    return builders[dialect](max_input_bytes=max_input_bytes, target_tokens=target_tokens)


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


def _dispatch_review_mesh(args: argparse.Namespace) -> dict[str, Any]:
    if args.review_mesh_command == "template-list":
        payload = list_review_mesh_operator_templates()
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.review_mesh_command == "profile":
        budget_cap = _review_mesh_budget_cap(args)
        payload = build_review_mesh_profile(
            profile_id=args.profile_id,
            modes=args.mode or None,
            default_mode=args.default_mode,
            budget_cap=budget_cap,
            live_calls_allowed=args.allow_live_calls,
            independence_required=args.require_independence,
            independence_dimensions=args.independence_dimension or None,
            reviewer_model_classes=args.reviewer_model_class or None,
        )
        require_review_mesh_profile_pass(validate_review_mesh_profile(payload))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.review_mesh_command == "recommend":
        if args.text is not None:
            payload = recommend_review_mesh_for_text(args.text, sdd_tier=args.sdd_tier, risk_flags=args.risk_flag)
        elif args.file:
            path = Path(args.file)
            payload = recommend_review_mesh_for_text(
                path.read_text(encoding="utf-8"),
                source_label=path.name,
                sdd_tier=args.sdd_tier,
                risk_flags=args.risk_flag,
            )
        elif args.intake:
            payload = recommend_review_mesh_for_intake(
                read_json_object(Path(args.intake), label="adapter task intake receipt")
            )
        elif args.manifest:
            payload = recommend_review_mesh_for_plan_manifest(
                read_json_object(Path(args.manifest), label="plan manifest")
            )
        else:
            raise LifecycleError("review-mesh-recommendation-source-missing", "one recommendation source is required")
        require_review_mesh_recommendation_pass(validate_review_mesh_recommendation(payload))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.review_mesh_command == "prepare":
        source = _review_mesh_source(args, code="review-mesh-prepare-source-missing", label="prepare")
        payload = prepare_review_mesh_operator_packets(
            source=source,
            template_id=args.template,
            reviewers=[parse_reviewer_spec(spec) for spec in args.reviewer] if args.reviewer else None,
            profile_id=args.profile_id,
            phase=args.phase,
            blocking=args.blocking,
            evidence_ids=args.evidence_id,
            out_dir=Path(args.out_dir) if args.out_dir else None,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.review_mesh_command == "assign":
        source = _review_mesh_source(args, code="review-mesh-assignment-source-missing", label="assignment")
        profile = (
            read_json_object(Path(args.profile), label="review mesh profile")
            if args.profile
            else build_review_mesh_profile(default_mode=args.mode, independence_required=False)
        )
        payload = build_review_mesh_assignment_packet(
            source=source,
            mode=args.mode,
            phase=args.phase,
            assignment_id=args.assignment_id,
            reviewer_id=args.reviewer_id,
            reviewer_role=args.reviewer_role,
            reviewer_model_class=args.reviewer_model_class,
            reviewer_host_identity_hash=args.reviewer_host_identity_hash,
            reviewer_model_identity_hash=args.reviewer_model_identity_hash,
            blocking=args.blocking,
            profile=profile,
            evidence_ids=args.evidence_id,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.review_mesh_command == "import-result":
        assignment_payload = read_json_object(Path(args.assignment), label="review mesh assignment")
        assignment = assignment_payload.get("assignment") if isinstance(assignment_payload.get("assignment"), dict) else assignment_payload
        payload = import_review_mesh_result(
            profile=read_json_object(Path(args.profile), label="review mesh profile"),
            assignment=assignment,
            reviewer_output=read_json_object(Path(args.reviewer_output), label="reviewer output"),
            allow_local_evidence_refs=args.allow_local_evidence_ref,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.review_mesh_command == "synthesize":
        payload = synthesize_review_mesh_results(
            profile=read_json_object(Path(args.profile), label="review mesh profile"),
            results=[read_json_object(Path(path), label="review mesh result") for path in args.result],
            mode=args.mode,
            accepted_finding_ids=args.accepted_finding_id,
            rejected_finding_ids=args.rejected_finding_id,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.review_mesh_command == "quorum":
        profile = read_json_object(Path(args.profile), label="review mesh profile")
        synthesis = read_json_object(Path(args.synthesis), label="review mesh synthesis")
        payload = build_quorum_from_synthesis(
            profile=profile,
            synthesis=synthesis,
            quorum_policy={"minReviewers": args.min_reviewers, "requiredRoles": args.required_role},
            reviewer_roles=args.reviewer_role,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "review-mesh command is not implemented")


def _review_mesh_source(args: argparse.Namespace, *, code: str, label: str) -> dict[str, Any]:
    if args.manifest:
        return source_from_manifest(read_json_object(Path(args.manifest), label="plan manifest"))
    if args.intake:
        return source_from_intake(read_json_object(Path(args.intake), label="adapter task intake receipt"))
    if args.handoff:
        return source_from_handoff(read_json_object(Path(args.handoff), label="plan handoff"))
    raise LifecycleError(code, f"one {label} source is required")


def _review_mesh_budget_cap(args: argparse.Namespace) -> dict[str, int] | None:
    budget_cap = {
        key: value
        for key, value in {
            "maxInvocations": args.max_invocations,
            "maxInputTokens": args.max_input_tokens,
            "maxOutputTokens": args.max_output_tokens,
            "maxWallSeconds": args.max_wall_seconds,
        }.items()
        if value is not None
    }
    return budget_cap or None
