"""Tiering, specification, planning, and task-packet CLI handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.audit.delta_review import (
    _input_refusal,
    build_delta_review_packet,
)
from agent_lifecycle.changesets.snapshot import _baseline_entries
from agent_lifecycle.cli.compact_plan_commands import compact_package_profiles, compact_plan_command
from agent_lifecycle.cli.plan_lock_commands import create_reviewed_plan_lock, prepare_freeze_candidate
from agent_lifecycle.compiler import build_phase_packet, compile_small_model_packets, compile_task_packets
from agent_lifecycle.contracts import (
    LifecycleError,
    canonical_digest,
    load_json_object,
    read_json_object,
    sha256_hex,
    write_json_create,
)
from agent_lifecycle.contracts.authority_io import create_authority_bytes
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.finding_check_schemas import (
    validate_finding_check_binding,
    validate_finding_check_evidence,
    validate_finding_check_proposal,
)
from agent_lifecycle.contracts.ownership_paths import require_output_footprint
from agent_lifecycle.contracts.paths import normalize_repo_path
from agent_lifecycle.contracts.phase_packet_schemas import PLANNING_HANDOFF_PAYLOAD_SCHEMA
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.freeze.package_integrity import (
    _bind_review_inputs,
    _read_composite_reports,
    _read_review_artifact,
    _runtime_paths,
    _verify_runtime_inventory,
)
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
from agent_lifecycle.review.validation import (
    make_review_subject,
    review_output_paths,
    validate_bound_plan_review,
    validate_review_composition,
)
from agent_lifecycle.specification import (
    build_completion_gate_receipt,
    validate_specification,
)
from agent_lifecycle.workflow.artifact_builders import (
    artifact_summary,
    build_authored_artifact,
    create_artifact,
    inspect_artifact,
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
    if args.plan_command == "package-profiles":
        return compact_package_profiles()
    if args.plan_command in {"compact-compile", "compact-explain"}:
        return compact_plan_command(
            input_path=args.input,
            output_path=getattr(args, "out", None),
            repository_root=Path(args.repository_root),
            explain=args.plan_command == "compact-explain",
        )
    if args.plan_command == "freeze-prepare":
        return prepare_freeze_candidate(
            manifest_path=args.manifest,
            output_path=args.out,
            repository_root=Path(args.repository_root),
        )
    if args.plan_command == "lock-create":
        return create_reviewed_plan_lock(
            manifest_path=args.manifest,
            review_path=args.review,
            repository_root=Path(args.repository_root),
        )
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
                require_completeness=True,
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
        return _verify_plan(args)
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
        if args.phase_packet_out:
            if not args.snapshot or not args.lock:
                raise LifecycleError(
                    "phase-packet-required-fact-missing",
                    "plan handoff phase packet requires --snapshot and --lock",
                )
            lock = read_json_object(Path(args.lock), label="plan lock")
            verify_plan_lock(manifest, lock)
            packet = _build_planning_handoff_phase_packet(
                manifest,
                lock,
                handoff_snapshot,
                selected_workstream_ids=[
                    item["id"]
                    for item in payload.get("workstreams", [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                ],
            )
            write_json_create(Path(args.phase_packet_out), packet)
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
            language_before=read(args.language_before, "before project domain language"),
            language_after=read(args.language_after, "after project domain language"),
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.plan_command == "review-packet":
        return _plan_review_packet(args)
    if args.plan_command in {"delta-check", "delta-validate"}:
        payload = validate_plan_delta(read_json_object(Path(args.delta), label="plan delta"))
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.plan_command == "finding-check":
        return _dispatch_finding_check(args)
    raise LifecycleError("command-not-implemented", "plan command is not implemented")


def _plan_review_packet(args: argparse.Namespace) -> dict[str, Any]:
    """Bind physical inputs before advisory selection; refusal writes nothing."""
    root = Path(args.repository_root).resolve(strict=True)
    if type(args.max_bytes) is not int or args.max_bytes < 1024:
        raise LifecycleError("review-packet-limit", "Invalid packet limit")
    subject: dict[str, Any] = {}
    try:
        manifest = load_json_object(_read_review_artifact(root, args.manifest), label="review manifest")
        subject = {"manifest": manifest}
        package = manifest.get("package")
        if not isinstance(package, dict):
            raise LifecycleError("review-input-incomplete", "Package needed")
        expected = package.get("planArtifactRoot", "")
        if not isinstance(expected, str) or not expected:
            raise LifecycleError("review-input-incomplete", "Plan root needed")
        if args.manifest != expected + "/plan.manifest.json":
            raise LifecycleError("review-subject-mismatch", "Manifest location")
        baseline, reports, sizes = _packet_baseline(root, args.baseline)
        subject = _packet_subject(root, manifest, reports)
        # A stable second read detects changes during inventory collection.
        _bind_review_inputs(
            {
                "subject": subject,
                "reviewAuthority": {"evidence": []},
            },
            root,
            {},
        )
        _verify_runtime_inventory(
            {**reports, "candidate": {"subject": subject}},
            root,
            require_current=True,
        )
        payload = build_delta_review_packet(
            subject,
            baseline=baseline,
            reports=reports or None,
            report_sizes=sizes or None,
            max_bytes=args.max_bytes,
        )
    except LifecycleError as exc:
        return _input_refusal(subject, exc.code)
    if payload["mode"] == "FULL_REQUIRED":
        return payload
    outputs = [(args.out, payload, ".review-packet.json")]
    if args.subject_out:
        outputs.append((args.subject_out, subject, ".review-subject.json"))
    names = [name for name, _, _ in outputs if name]
    require_output_footprint(manifest, names, repository_root=root)
    for name, _, suffix in outputs:
        if name:
            _packet_output_preflight(root, name, suffix, manifest)
    for name, value, _ in outputs:
        if name:
            create_authority_bytes(root / name, canonical_bytes(value) + b"\n", root=root)
    return payload


def _packet_baseline(
    root: Path,
    path: str | None,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], dict[str, int]]:
    if path is None:
        return None, {}, {}
    raw = _read_review_artifact(root, path)
    baseline = load_json_object(raw, label="review baseline")
    evidence: dict[str, dict[str, Any]] = {}
    if baseline.get("schemaVersion") == "agent-plan-composite-review.v1":
        current = baseline.get("currentReports")
        if not isinstance(current, list) or not current:
            raise LifecycleError("review-set-incomplete", "Current report needed")
        report = load_json_object(_read_review_artifact(root, current[0]))
        bound = validate_bound_plan_review(report)
        manifest = bound["subject"]["manifest"]
        reports, sizes = _read_composite_reports(manifest, baseline, root, evidence)
        validate_review_composition(manifest, baseline, reports, report_sizes=sizes)
    else:
        bound = validate_bound_plan_review(baseline)
        if bound["scope"]["kind"] != "FULL":
            raise LifecycleError("review-incomplete", "Full baseline needed")
        reports, sizes = {path: baseline}, {path: len(raw)}
    for report in reports.values():
        _bind_review_inputs(report, root, evidence)
    return baseline, reports, sizes


def _packet_subject(
    root: Path,
    manifest: dict[str, Any],
    reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    subjects = [r["subject"] for r in reports.values()]
    manifests = [manifest, *(s["manifest"] for s in subjects)]
    roots = {normalize_repo_path(m["package"]["planArtifactRoot"]) + "/" for m in manifests}
    base = manifest.get("baseRevision")
    source = base.get("sha") if isinstance(base, dict) else None
    if not isinstance(source, str) or len(source) not in {40, 64}:
        raise LifecycleError("review-source-unavailable", "Exact source needed")
    if any(c not in "0123456789abcdef" for c in source):
        raise LifecycleError("review-source-unavailable", "Invalid source hash")
    paths = _runtime_paths(root, ["ls-tree", "-r", "--name-only", "-z", source], roots)
    if len(paths) > 4096:
        raise LifecycleError("review-input-limit", "Runtime inventory cap")
    blobs = _baseline_entries(root, source, sorted(paths))
    files = manifest.get("planFiles")
    if not isinstance(files, list) or any(not isinstance(p, str) for p in files):
        raise LifecycleError("review-input-incomplete", "Plan inventory needed")
    if len(files) > 4096:
        raise LifecycleError("review-input-limit", "Plan inventory cap")
    digests = {p: sha256_hex(_read_review_artifact(root, p)) for p in set(files) - review_output_paths(manifest)}
    return make_review_subject(manifest, digests, {p: entry["sha256"] for p, entry in blobs.items()})


def _packet_output_preflight(
    root: Path,
    path: str,
    suffix: str,
    manifest: dict[str, Any],
) -> None:
    name = normalize_repo_path(path)
    if name != path or not name.endswith(suffix):
        raise LifecycleError("review-output-invalid", "Advisory suffix required")
    forbidden = {".git", ".alk", ".claude", ".codex"}
    if any(p.casefold() in forbidden for p in Path(name).parts):
        raise LifecycleError("review-output-invalid", "Protected destination")
    policy = manifest.get("orchestration", {})
    declared = {value for value in policy.values() if isinstance(value, str)} if isinstance(policy, dict) else set()
    if name in declared or (root / name).exists():
        raise LifecycleError("review-output-invalid", "Destination reserved")


def _verify_plan(args: argparse.Namespace) -> dict[str, Any]:
    if args.compact and not args.out:
        raise LifecycleError("plan-compact-output-required", "Compact display requires --out for the full receipt")
    manifest_path = Path(args.manifest)
    manifest, lock, markdown, state, package_root = load_verification_inputs(
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
        acceptance_markdown=markdown,
        workflow_state=state,
        repository_root=Path(args.repository_root),
        package_root=package_root,
    )
    output_path = args.out or args.evidence
    if output_path:
        write_json_create(Path(output_path), payload)
    require_plan_verification_pass(payload)
    return artifact_summary(Path(output_path), payload) if args.compact else payload


def _build_planning_handoff_phase_packet(
    manifest: dict[str, Any],
    lock: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    selected_workstream_ids: list[str],
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise LifecycleError("phase-packet-required-fact-missing", "plan handoff snapshot is required")
    all_workstreams = [item for item in manifest.get("workstreams", []) if isinstance(item, dict)]
    by_id = {item.get("id"): item for item in all_workstreams if isinstance(item.get("id"), str)}
    selected: list[dict[str, Any]] = []
    for workstream_id in selected_workstream_ids:
        workstream = by_id.get(workstream_id)
        if not isinstance(workstream, dict):
            raise LifecycleError(
                "phase-packet-required-fact-missing",
                "plan handoff selected an unknown workstream",
                {"workstreamId": workstream_id},
            )
        acceptance = _phase_acceptance(manifest, workstream)
        evidence = _phase_evidence(workstream)
        selected.append(
            {
                "id": workstream_id,
                "dependsOn": _string_list(workstream.get("dependsOn")),
                "writes": _string_list(workstream.get("writes")),
                "readOnly": _scope_list(manifest, workstream, "readOnly"),
                "forbiddenWrites": _scope_list(manifest, workstream, "forbiddenWrites"),
                "acceptanceCriteria": acceptance,
                "evidenceRequirements": evidence,
                "activeBlockerIds": _string_list(workstream.get("activeBlockerIds")),
            }
        )
    payload = {
        "schemaVersion": PLANNING_HANDOFF_PAYLOAD_SCHEMA,
        "workstreams": selected,
        "dependencyEdges": [
            {"from": dependency, "to": item["id"]} for item in selected for dependency in item["dependsOn"]
        ],
    }
    base_revision = manifest.get("baseRevision")
    source_revision = None
    if isinstance(base_revision, dict):
        source_revision = base_revision.get("sha") or base_revision.get("ref")
    if not isinstance(source_revision, str) or not source_revision:
        source_revision = snapshot.get("sourceDigest")
    if not isinstance(source_revision, str) or not source_revision:
        raise LifecycleError("phase-packet-required-fact-missing", "plan handoff source revision is required")
    acceptance = [criterion for item in selected for criterion in item["acceptanceCriteria"]]
    evidence = [requirement for item in selected for requirement in item["evidenceRequirements"]]
    blockers = [blocker for item in selected for blocker in item["activeBlockerIds"]]
    scopes = [
        {
            "id": item["id"],
            "writes": item["writes"],
            "readOnly": item["readOnly"],
            "forbiddenWrites": item["forbiddenWrites"],
        }
        for item in selected
    ]
    return build_phase_packet(
        purpose="PLANNING_HANDOFF",
        payload=payload,
        plan_digest=canonical_digest(manifest),
        plan_lock_digest=canonical_digest(lock),
        state_revision=None,
        source_revision=source_revision,
        write_scope_digest=canonical_digest(scopes),
        acceptance_digest=canonical_digest(acceptance),
        evidence_digest=canonical_digest(evidence),
        active_blocker_ids=blockers,
    )


def _phase_acceptance(manifest: dict[str, Any], workstream: dict[str, Any]) -> list[dict[str, Any]]:
    acceptance = manifest.get("acceptance")
    criteria = acceptance.get("criteria") if isinstance(acceptance, dict) else []
    criteria = criteria if isinstance(criteria, list) else []
    by_id = {item.get("id"): item for item in criteria if isinstance(item, dict) and isinstance(item.get("id"), str)}
    return [dict(by_id.get(item, {"id": item})) for item in _string_list(workstream.get("acceptanceIds"))]


def _phase_evidence(workstream: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": item, "required": True} for item in _string_list(workstream.get("evidenceIds"))]


def _scope_list(manifest: dict[str, Any], workstream: dict[str, Any], field: str) -> list[str]:
    return sorted(set(_string_list(manifest.get(field)) + _string_list(workstream.get(field))))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


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
    if args.task_command == "artifact-create":
        value = build_authored_artifact(
            read_json_object(Path(args.input)),
            kind=args.kind,
            redact_advisory=args.redact_advisory,
            state=read_json_object(Path(args.state)) if args.state else None,
            task_id=args.task,
            repository_root=Path(args.repository_root),
        )
        return create_artifact(Path(args.out), value)
    if args.task_command == "artifact-inspect":
        return inspect_artifact(Path(args.input), max_display_bytes=args.max_display_bytes)
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
