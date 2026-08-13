"""Reporting, context, goal, model, and metrics CLI dispatch handlers."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.context import check_context, load_context_profile, render_context
from agent_lifecycle.context.checkpoint_store import restore_context_checkpoint, write_context_checkpoint
from agent_lifecycle.context.checkpoints import build_context_checkpoint
from agent_lifecycle.context.external_memory import build_episode_retrieval_with_external_context, import_external_memory_context
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.goal import build_goal_progress_view, build_objective_snapshot, update_goal_record, validate_goal_record
from agent_lifecycle.metrics import (
    build_lifecycle_cost_summary,
    build_lifecycle_recommendation_summary,
    build_quality_cost_signals,
    build_task_outcome_index,
    build_usage_export,
    generate_lifecycle_cost_report,
    recommend_from_quality_cost_signals,
    recommend_lifecycle_mode,
    require_lifecycle_cost_pass,
    require_lifecycle_recommendation_pass,
    require_usage_export_pass,
    validate_lifecycle_cost_report,
    validate_usage_export,
)
from agent_lifecycle.model_routing import (
    resolve_model_route,
    validate_host_model_profile,
    validate_model_routing_profile,
    validate_usage_receipt,
)
from agent_lifecycle.reporting import (
    build_change_summary_receipt,
    build_lifecycle_progress_view,
    build_lifecycle_progress_watch,
    build_progress_bridge_receipt,
    build_status_view,
    build_workflow_event_feed,
    render_goal_view_terminal,
    render_progress_bridge_terminal,
    render_progress_terminal,
    render_usage_export_json,
    render_usage_export_table,
)


def dispatch_observability(args: argparse.Namespace) -> dict[str, Any] | str:
    """Dispatch read-only views, context, goal, model, and metrics commands."""
    if args.command == "report":
        return _dispatch_report(args)
    if args.command == "context":
        return _dispatch_context(args)
    if args.command == "goal":
        return _dispatch_goal(args)
    if args.command == "model":
        return _dispatch_model(args)
    if args.command == "metrics":
        return _dispatch_metrics(args)
    raise LifecycleError("command-not-implemented", "observability command is not implemented")


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
    if args.context_command == "external-import":
        payload = import_external_memory_context(
            Path(args.source),
            citation=args.citation,
            source_id=args.source_id,
            max_input_bytes=args.max_input_bytes,
            target_tokens=args.target_tokens,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.context_command == "episode-retrieve":
        payload = build_episode_retrieval_with_external_context(
            Path(args.project_root),
            list(args.artifact),
            external_context_paths=[Path(item) for item in args.external_context],
            query=args.query,
            max_results=args.max_results,
            max_external_context_hints=args.max_external_context_hints,
            target_tokens=args.target_tokens,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.context_command == "checkpoint":
        return _dispatch_context_checkpoint(args)
    if args.context_command == "restore":
        state = read_json_object(Path(args.state), label="workflow state")
        payload = restore_context_checkpoint(
            Path(args.checkpoint),
            state=state,
            session_id=args.session,
            target_tokens=args.target_tokens,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        if payload.get("status") == "BLOCKED":
            raise LifecycleError(
                "context-restore-blocked",
                "context checkpoint cannot be restored against the current workflow state",
                {"continuation": payload},
            )
        return payload
    raise LifecycleError("command-not-implemented", "context command is not implemented")


def _dispatch_context_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    state = read_json_object(Path(args.state), label="workflow state")
    manifest = read_json_object(Path(args.plan), label="context checkpoint plan")
    input_payload = read_json_object(Path(args.input), label="context checkpoint input")
    reason = str(args.reason)
    mode = args.capture_mode
    reason_mode = {
        "native-hook": "NATIVE_HOOK",
        "milestone": "MILESTONE",
        "agent-requested": "AGENT_REQUESTED",
        "unavailable": "UNAVAILABLE",
    }.get(reason.lower().replace("_", "-"))
    if mode is None and reason_mode:
        mode = reason_mode
    if mode is None:
        mode = "AGENT_REQUESTED"
    target = Path(args.out) if args.out else Path(".alk/context/checkpoints") / "checkpoint.json"
    root = target.parent
    _require_checkpoint_output_root(root)
    summary = dict(input_payload)
    capture_evidence = summary.pop("nativeHookEvidence", None) if mode == "NATIVE_HOOK" else None
    checkpoint = build_context_checkpoint(
        session_id=args.session,
        run_id=str(state.get("runId", "run")),
        adapter_id=str(args.adapter or input_payload.get("adapterId") or state.get("adapterId") or "unknown-adapter"),
        package_id=str(manifest.get("package", {}).get("id") or state.get("packageId") or "unknown-package"),
        plan_revision=int(manifest.get("planRevision", state.get("planRevision", 1))),
        plan_digest=canonical_digest(manifest),
        state_revision=int(state.get("stateRevision", 1)),
        source_revision=str(state.get("sourceRevision", "unknown-source")),
        capture_mode=mode,
        reason=reason,
        summary=summary,
        capture_evidence=capture_evidence,
        checkpoint_id=target.stem if args.out else None,
        created_at=str(state.get("updatedAt") or "1970-01-01T00:00:00Z"),
    )
    stored = write_context_checkpoint(checkpoint, root=root)
    return {**checkpoint, "storage": stored}


def _require_checkpoint_output_root(root: Path) -> None:
    resolved = root.resolve()
    if ".alk" not in resolved.parts or not resolved.name == "checkpoints":
        raise LifecycleError("context-checkpoint-output-root-invalid", "checkpoint output must remain in a .alk/context/checkpoints directory")


def _dispatch_goal(args: argparse.Namespace) -> dict[str, Any] | str:
    record = read_json_object(Path(args.record), label="goal record")
    if args.goal_command == "check":
        state = read_json_object(Path(args.state), label="workflow state") if args.state else None
        return validate_goal_record(record, state=state, require_current=args.current)
    if args.goal_command == "summarize":
        state = read_json_object(Path(args.state), label="workflow state")
        profile = read_json_object(Path(args.profile), label="context profile") if args.profile else None
        return build_objective_snapshot(record, state, profile=profile, window=args.target_window)
    if args.goal_command == "view":
        payload = build_goal_progress_view(
            record_path=Path(args.record),
            state_path=Path(args.state),
            usage_receipt_paths=[Path(item) for item in args.usage_receipt],
            change_summary_path=Path(args.change_summary) if args.change_summary else None,
            require_current=not args.allow_stale_goal,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        if args.terminal:
            return render_goal_view_terminal(payload)
        return payload
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
            raise LifecycleError(
                "model-usage-validation-failed",
                "model usage receipt validation failed",
                {"validation": result},
            )
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
        raise LifecycleError(
            "output-already-exists",
            "output artifact already exists",
            {"path": path.as_posix()},
        ) from exc
    return data


def _require_context_pass(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") == "FAIL":
        raise LifecycleError(
            "context-overflow",
            "compact context exceeds target window",
            {"receipt": result.get("receipt")},
        )
    return result
