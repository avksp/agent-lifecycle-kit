"""Adapter CLI parser and dispatch."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions import (
    build_adapter_session_receipt,
    create_session,
    launch_from_descriptor,
    load_session,
    managed_adapter_run,
    promote_session_to_workflow,
    resume_adapter_session,
    start_adapter_task,
    update_session,
)
from agent_lifecycle.adapter_sessions.agent_plugin_probe import build_agent_plugin_probe_runner
from agent_lifecycle.adapter_sessions.launcher import load_adapter_descriptor, managed_launch_profile
from agent_lifecycle.adapter_sessions.local_launch_profile import validate_local_launch_profile
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile, qualified_profile_output_path
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.thread_bridge_schemas import (
    resolve_thread_operation_status,
    validate_thread_bridge_profile,
    validate_thread_bridge_qualification_receipt,
)
from agent_lifecycle.diagnostics import build_adapter_install_plan
from agent_lifecycle.host_protocol import (
    inspect_adapter_descriptor,
    require_adapter_event_stream_pass,
    require_adapter_inspection_pass,
    require_adapter_validation_pass,
    require_event_capture_pass,
    scaffold_adapter,
    validate_adapter_descriptor,
    validate_adapter_event_stream,
    validate_capability_manifest,
    validate_event_capture_conformance,
)
from agent_lifecycle.host_protocol.agent_plugin_qualification import run_agent_plugin_qualification_probe
from agent_lifecycle.host_protocol.capabilities import (
    build_thread_bridge_capability_projection,
    build_thread_bridge_profile_from_descriptor,
    capability_manifest_identity,
)
from agent_lifecycle.host_protocol.event_capture import (
    require_lifecycle_control_bundle_pass,
    validate_lifecycle_control_bundle,
)
from agent_lifecycle.host_protocol.lifecycle_control import load_lifecycle_control_policy
from agent_lifecycle.reporting.progress_hooks import build_progress_hook_receipt


def add_adapter_parser(subparsers: argparse._SubParsersAction) -> None:
    adapter = subparsers.add_parser("adapter", help="adapter commands")
    adapter_sub = adapter.add_subparsers(dest="adapter_command")
    adapter_validate = adapter_sub.add_parser("validate")
    adapter_validate.add_argument("--descriptor", required=True)
    adapter_validate.add_argument("--baseline")
    adapter_validate.add_argument("--request", action="append", default=[])
    adapter_validate.add_argument("--receipt", action="append", default=[])
    adapter_inspect = adapter_sub.add_parser("inspect")
    adapter_inspect.add_argument("--descriptor", required=True)
    adapter_inspect.add_argument("--host-bin")
    adapter_inspect.add_argument("--project-root", default=".")
    adapter_inspect.add_argument("--skip-host-commands", action="store_true")
    adapter_inspect.add_argument("--timeout-seconds", type=float, default=10.0)
    adapter_install_plan = adapter_sub.add_parser("install-plan")
    adapter_install_plan.add_argument("--descriptor", required=True)
    adapter_install_plan.add_argument("--project-root", default=".")
    adapter_event = adapter_sub.add_parser("event-check")
    adapter_event.add_argument("--event", action="append", required=True)
    adapter_event_capture = adapter_sub.add_parser("event-capture-check")
    adapter_event_capture.add_argument("--descriptor", required=True)
    adapter_event_capture.add_argument("--projection")
    adapter_event_capture.add_argument("--capability-manifest")
    adapter_event_capture.add_argument("--event", action="append", required=True)
    adapter_event_capture.add_argument("--receipt", required=True)
    adapter_control = adapter_sub.add_parser("lifecycle-control-check")
    adapter_control.add_argument("--policy")
    adapter_control.add_argument("--request")
    adapter_control.add_argument("--decision")
    adapter_control.add_argument("--control-event", action="append", default=[])
    adapter_control.add_argument("--attestation")
    adapter_scaffold = adapter_sub.add_parser("scaffold")
    adapter_scaffold.add_argument("--host", required=True)
    adapter_scaffold.add_argument("--target", required=True)
    adapter_scaffold.add_argument("--maturity", default="EXPERIMENTAL")
    adapter_scaffold.add_argument("--dry-run", action="store_true")
    adapter_launch_profile = adapter_sub.add_parser("launch-profile")
    adapter_launch_profile.add_argument("--adapter", required=True, choices=["codex", "claude", "opencode"])
    adapter_launch_profile.add_argument("--out", required=True)
    adapter_launch_profile.add_argument("--executable")
    adapter_launch_profile.add_argument("--repository-root", default=".")
    adapter_session = adapter_sub.add_parser("session")
    session_sub = adapter_session.add_subparsers(dest="adapter_session_command", required=True)
    session_start = session_sub.add_parser("start")
    session_start.add_argument("--adapter", required=True)
    session_start.add_argument("--descriptor")
    session_start.add_argument("--session-root")
    session_start.add_argument("--launch", action="store_true")
    session_start.add_argument("--env-policy")
    session_start.add_argument("--out")
    session_resume = session_sub.add_parser("resume")
    session_resume.add_argument("--session", required=True)
    session_resume.add_argument("--session-root")
    session_resume.add_argument("--adapter")
    session_resume.add_argument("--state")
    session_resume.add_argument("--task")
    session_resume.add_argument("--out")
    session_status = session_sub.add_parser("status")
    session_status.add_argument("--session", required=True)
    session_status.add_argument("--session-root")
    session_status.add_argument("--out")
    session_promote = session_sub.add_parser("promote")
    session_promote.add_argument("--session", required=True)
    session_promote.add_argument("--session-root")
    session_promote.add_argument("--adapter")
    session_promote.add_argument("--state", required=True)
    session_promote.add_argument("--task", required=True)
    session_promote.add_argument("--progress-hook", choices=["stderr", "receipt", "off"], default="stderr")
    session_promote.add_argument("--progress-receipt")
    session_promote.add_argument("--out")
    adapter_task = adapter_sub.add_parser("task")
    task_sub = adapter_task.add_subparsers(dest="adapter_task_command", required=True)
    task_start = task_sub.add_parser("start")
    task_start.add_argument("--adapter", required=True)
    source_group = task_start.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--file", "--task-file", dest="task_file")
    source_group.add_argument("--text", "--task-text", dest="task_text")
    task_start.add_argument("--descriptor")
    task_start.add_argument("--session-root")
    task_start.add_argument("--state")
    task_start.add_argument("--lock")
    task_start.add_argument("--task")
    task_start.add_argument("--operation-id")
    task_start.add_argument("--expected-revision", type=int)
    task_start.add_argument("--source-revision")
    task_start.add_argument("--candidate-out")
    task_start.add_argument("--package-id", default="adapter-task-intake")
    task_start.add_argument("--max-input-bytes", type=int, default=32768)
    task_start.add_argument("--target-tokens", type=int, default=4096)
    task_start.add_argument("--progress-hook", choices=["stderr", "receipt", "off"], default="stderr")
    task_start.add_argument("--progress-receipt")
    task_start.add_argument("--out")
    adapter_run = adapter_sub.add_parser("run")
    adapter_run.add_argument("--adapter", required=True)
    adapter_run.add_argument("--descriptor")
    adapter_run.add_argument("--session-root")
    adapter_run.add_argument("--state", required=True)
    adapter_run.add_argument("--manifest", required=True)
    adapter_run.add_argument("--lock")
    adapter_run.add_argument("--task", required=True)
    adapter_run.add_argument("--operation-id", required=True)
    adapter_run.add_argument("--expected-revision", required=True, type=int)
    adapter_run.add_argument("--source-revision", required=True)
    adapter_run.add_argument("--progress-hook", choices=["stderr", "receipt", "off"], default="stderr")
    adapter_run.add_argument("--progress-receipt")
    adapter_run.add_argument("--out")
    adapter_external_job = adapter_sub.add_parser("external-job")
    external_job_sub = adapter_external_job.add_subparsers(dest="external_job_command", required=True)
    external_job_run = external_job_sub.add_parser("run")
    external_job_run.add_argument("--request", required=True)
    external_job_run.add_argument("--job-root")
    external_job_run.add_argument("--cwd", default=".")
    external_job_run.add_argument("--verdict", choices=["PASS", "FAIL", "NO_FINAL_VERDICT"], default="PASS")
    external_job_run.add_argument("--incomplete", action="store_true")
    external_job_run.add_argument("--cost-micros", type=int, default=0)
    external_job_run.add_argument("--reported-tokens", type=int, default=0)
    external_job_run.add_argument("--child-request", action="append", default=[])
    external_job_run.add_argument("--out")
    external_job_run.add_argument("argv", nargs=argparse.REMAINDER)
    external_job_status = external_job_sub.add_parser("status")
    external_job_status.add_argument("--request", required=True)
    external_job_status.add_argument("--job-root")
    external_job_status.add_argument("--out")
    external_job_cancel = external_job_sub.add_parser("cancel")
    external_job_cancel.add_argument("--request", required=True)
    external_job_cancel.add_argument("--job-root")
    external_job_cancel.add_argument("--out")
    adapter_thread_capability = adapter_sub.add_parser("thread-capability")
    adapter_thread_capability.add_argument("--descriptor", required=True)
    adapter_thread_capability.add_argument("--manifest", required=True)
    adapter_thread_capability.add_argument("--receipt")
    adapter_thread_capability.add_argument("--out")
    adapter_thread_qualify = adapter_sub.add_parser("thread-qualify")
    adapter_thread_qualify.add_argument("--descriptor", required=True)
    adapter_thread_qualify.add_argument("--receipt", required=True)
    adapter_thread_qualify.add_argument("--manifest")
    adapter_thread_qualify.add_argument("--out")
    adapter_plugin_qualify = adapter_sub.add_parser("plugin-qualify")
    adapter_plugin_qualify.add_argument("--adapter", required=True, choices=["codex", "claude", "cursor"])
    adapter_plugin_qualify.add_argument("--profile", required=True)
    adapter_plugin_qualify.add_argument("--package", required=True)
    adapter_plugin_qualify.add_argument("--project-root", default=".")
    adapter_plugin_qualify.add_argument("--host-bin")
    adapter_plugin_qualify.add_argument("--out")


def dispatch_adapter(args: argparse.Namespace) -> dict[str, Any]:
    if args.adapter_command == "validate":
        descriptor = read_json_object(Path(args.descriptor), label="adapter descriptor")
        baseline = read_json_object(Path(args.baseline), label="adapter baseline") if args.baseline else None
        requests = [read_json_object(Path(path), label="host operation request") for path in args.request]
        receipts = [read_json_object(Path(path), label="host operation receipt") for path in args.receipt]
        return require_adapter_validation_pass(
            validate_adapter_descriptor(
                descriptor,
                baseline=baseline,
                requests=requests,
                receipts=receipts,
            )
        )
    if args.adapter_command == "inspect":
        descriptor_path = Path(args.descriptor)
        descriptor = read_json_object(descriptor_path, label="adapter descriptor")
        return require_adapter_inspection_pass(
            inspect_adapter_descriptor(
                descriptor,
                descriptor_path=descriptor_path,
                host_bin=args.host_bin,
                project_root=Path(args.project_root),
                skip_host_commands=args.skip_host_commands,
                timeout_seconds=args.timeout_seconds,
            )
        )
    if args.adapter_command == "install-plan":
        return build_adapter_install_plan(
            project_root=Path(args.project_root),
            descriptor_path=Path(args.descriptor),
        )
    if args.adapter_command == "event-check":
        events = [read_json_object(Path(path), label="adapter event") for path in args.event]
        return require_adapter_event_stream_pass(validate_adapter_event_stream(events))
    if args.adapter_command == "event-capture-check":
        descriptor = read_json_object(Path(args.descriptor), label="adapter descriptor")
        projection = read_json_object(Path(args.projection), label="adapter projection") if args.projection else None
        capability_manifest = (
            read_json_object(Path(args.capability_manifest), label="capability manifest")
            if args.capability_manifest
            else None
        )
        receipt = read_json_object(Path(args.receipt), label="adapter event stream receipt")
        events = [read_json_object(Path(path), label="adapter event") for path in args.event]
        return require_event_capture_pass(
            validate_event_capture_conformance(
                descriptor=descriptor,
                projection=projection,
                capability_manifest=capability_manifest,
                events=events,
                receipt=receipt,
            )
        )
    if args.adapter_command == "lifecycle-control-check":
        return _dispatch_lifecycle_control_check(args)
    if args.adapter_command == "scaffold":
        return scaffold_adapter(
            host=args.host,
            target=Path(args.target),
            maturity=args.maturity,
            dry_run=args.dry_run,
        )
    if args.adapter_command == "launch-profile":
        profile = load_shipped_launch_profile(args.adapter, repository_root=Path(args.repository_root))
        shipped_digest = canonical_digest(profile)
        profile_origin = "SHIPPED_PROFILE_BOUND"
        if args.executable:
            profile = {**profile, "executable": args.executable}
            profile_origin = "OPERATOR_OWNED_UNVERIFIED"
        validation = validate_local_launch_profile(profile)
        if validation["status"] != "PASS":
            raise LifecycleError(
                "qualified-launch-profile-invalid", "shipped launch profile failed validation", validation
            )
        out = qualified_profile_output_path(args.out)
        write_json_create(out, profile)
        return {
            "schemaVersion": "agent-qualified-launch-profile-generation.v1",
            "status": "PASS",
            "adapterId": args.adapter,
            "profilePath": out.as_posix(),
            "profileDigest": validation["profileDigest"],
            "profileOrigin": profile_origin,
            "shippedProfileDigest": shipped_digest,
            "publicSupportClaimed": False,
            "productionPromotionClaimed": False,
        }
    if args.adapter_command == "session":
        return _dispatch_adapter_session(args)
    if args.adapter_command == "task":
        return _dispatch_adapter_task(args)
    if args.adapter_command == "run":
        _validate_adapter_progress_args(args)
        payload = managed_adapter_run(
            adapter_id=args.adapter,
            descriptor_path=Path(args.descriptor) if args.descriptor else None,
            session_root=Path(args.session_root) if args.session_root else None,
            state_path=Path(args.state),
            manifest_path=Path(args.manifest),
            lock_path=Path(args.lock) if args.lock else None,
            task_id=args.task,
            operation_id=args.operation_id,
            expected_revision=args.expected_revision,
            source_revision=args.source_revision,
        )
        _emit_adapter_progress(args, adapter_id=args.adapter, state_path=Path(args.state), task_id=args.task)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.adapter_command == "thread-capability":
        payload = _build_thread_capability_payload(args)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.adapter_command == "thread-qualify":
        payload = _build_thread_qualification_payload(args)
        if args.out:
            write_json_create(Path(args.out), payload)
        if payload.get("status") != "PASS":
            raise LifecycleError("thread-qualification-failed", "thread qualification validation failed", payload)
        return payload
    if args.adapter_command == "plugin-qualify":
        profile = read_json_object(Path(args.profile), label="Agent Plugins qualification profile")
        if profile.get("adapterId") != args.adapter:
            raise LifecycleError(
                "plugin-qualification-adapter-mismatch",
                "qualification profile adapterId does not match --adapter",
                {"profileAdapterId": profile.get("adapterId"), "adapterId": args.adapter},
            )
        probe_args: dict[str, Any] = {
            "package_root": Path(args.package),
            "project_root": Path(args.project_root),
            "profile": profile,
            "host_bin": args.host_bin,
        }
        # Keep profile validation in the qualification service. The explicit
        # runner is composed only for a profile that has its bounded limits;
        # this also preserves the dispatcher seam for lightweight callers and
        # tests that replace the service.
        if isinstance(profile.get("qualification"), dict):
            probe_args["command_runner"] = build_agent_plugin_probe_runner(profile, Path(args.project_root))
        payload = run_agent_plugin_qualification_probe(**probe_args)
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "adapter command is not implemented")


def _dispatch_lifecycle_control_check(args: argparse.Namespace) -> dict[str, Any]:
    policy = load_lifecycle_control_policy(Path(args.policy)) if args.policy else load_lifecycle_control_policy()
    request = read_json_object(Path(args.request), label="lifecycle control request") if args.request else None
    decision = read_json_object(Path(args.decision), label="lifecycle control decision") if args.decision else None
    events = [read_json_object(Path(path), label="lifecycle control event") for path in args.control_event]
    attestation = (
        read_json_object(Path(args.attestation), label="lifecycle control attestation") if args.attestation else None
    )
    return require_lifecycle_control_bundle_pass(
        validate_lifecycle_control_bundle(
            policy=policy,
            request=request,
            decision=decision,
            events=events or None,
            attestation=attestation,
        )
    )


def _build_thread_capability_payload(args: argparse.Namespace) -> dict[str, Any]:
    descriptor_path = Path(args.descriptor)
    descriptor = read_json_object(descriptor_path, label="adapter descriptor")
    manifest = read_json_object(Path(args.manifest), label="adapter capability manifest")
    manifest_validation = validate_capability_manifest(manifest, descriptor=descriptor)
    if manifest_validation["status"] != "PASS":
        raise LifecycleError(
            "thread-capability-manifest-invalid", "adapter capability manifest failed validation", manifest_validation
        )
    manifest_digest = capability_manifest_identity(manifest)
    profile = build_thread_bridge_profile_from_descriptor(
        descriptor,
        capability_manifest_digest=manifest_digest,
    )
    profile_validation = validate_thread_bridge_profile(profile)
    if profile_validation["status"] != "PASS":
        raise LifecycleError(
            "thread-capability-profile-invalid", "adapter thread profile failed validation", profile_validation
        )
    receipt = read_json_object(Path(args.receipt), label="thread qualification receipt") if args.receipt else None
    return build_thread_bridge_capability_projection(profile, qualification_receipt=receipt)


def _build_thread_qualification_payload(args: argparse.Namespace) -> dict[str, Any]:
    descriptor_path = Path(args.descriptor)
    descriptor = read_json_object(descriptor_path, label="adapter descriptor")
    manifest_path = (
        Path(args.manifest) if args.manifest else _manifest_path_from_descriptor(descriptor_path, descriptor)
    )
    manifest = read_json_object(manifest_path, label="adapter capability manifest")
    manifest_validation = validate_capability_manifest(manifest, descriptor=descriptor)
    receipt = read_json_object(Path(args.receipt), label="thread qualification receipt")
    receipt_validation = validate_thread_bridge_qualification_receipt(receipt)
    profile = build_thread_bridge_profile_from_descriptor(
        descriptor,
        capability_manifest_digest=capability_manifest_identity(manifest),
    )
    profile_validation = validate_thread_bridge_profile(profile)
    blockers = list(receipt_validation.get("blockers", []))
    blockers.extend(profile_validation.get("blockers", []))
    blockers.extend(manifest_validation.get("blockers", []))
    operation_results = []
    for operation in receipt.get("operationSet", []) if isinstance(receipt.get("operationSet"), list) else []:
        decision = resolve_thread_operation_status(profile, operation, qualification_receipt=receipt)
        operation_results.append(decision)
        if decision.get("qualificationStatus") != "QUALIFIED":
            blockers.extend(decision.get("blockers", []))
    body = {
        "schemaVersion": "agent-thread-bridge-profile-validation.v1",
        "status": "PASS" if not blockers else "FAIL",
        "adapterId": descriptor.get("adapterId"),
        "host": descriptor.get("host"),
        "profileDigest": profile.get("profileDigest"),
        "receiptDigest": receipt.get("receiptDigest"),
        "checks": [
            {"name": "descriptor", "status": "PASS" if manifest_validation["status"] == "PASS" else "FAIL"},
            {"name": "profile", "status": profile_validation["status"]},
            {"name": "qualification", "status": receipt_validation["status"]},
            {
                "name": "operation-bindings",
                "status": "PASS"
                if operation_results and all(item["qualificationStatus"] == "QUALIFIED" for item in operation_results)
                else "FAIL",
            },
        ],
        "operations": operation_results,
        "blockers": blockers,
        "productionPromotionClaimed": False,
    }
    return {**body, "validationDigest": canonical_digest(body)}


def _manifest_path_from_descriptor(descriptor_path: Path, descriptor: dict[str, Any]) -> Path:
    configured = descriptor.get("capabilityManifest")
    if not isinstance(configured, str) or not configured:
        raise LifecycleError("thread-capability-manifest-missing", "descriptor does not name a capability manifest")
    configured_path = Path(configured)
    if configured_path.exists():
        return configured_path
    relative_path = descriptor_path.parent / configured_path.name
    if relative_path.exists():
        return relative_path
    raise LifecycleError(
        "thread-capability-manifest-missing", "capability manifest path does not exist", {"path": configured}
    )


def _dispatch_adapter_task(args: argparse.Namespace) -> dict[str, Any]:
    if args.adapter_task_command != "start":
        raise LifecycleError("command-not-implemented", "adapter task command is not implemented")
    payload = start_adapter_task(
        adapter_id=args.adapter,
        task_file=Path(args.task_file) if args.task_file else None,
        task_text=args.task_text,
        candidate_out=Path(args.candidate_out) if args.candidate_out else None,
        descriptor_path=Path(args.descriptor) if args.descriptor else None,
        session_root=Path(args.session_root) if args.session_root else None,
        state_path=Path(args.state) if args.state else None,
        lock_path=Path(args.lock) if args.lock else None,
        task_id=args.task,
        operation_id=args.operation_id,
        expected_revision=args.expected_revision,
        source_revision=args.source_revision,
        max_input_bytes=args.max_input_bytes,
        target_tokens=args.target_tokens,
        package_id=args.package_id,
    )
    raw_binding = payload.get("workflowBinding")
    binding: dict[str, Any] = raw_binding if isinstance(raw_binding, dict) else {}
    if payload.get("executionStarted") and binding.get("state") and binding.get("task"):
        _emit_adapter_progress(
            args, adapter_id=args.adapter, state_path=Path(binding["state"]), task_id=str(binding["task"])
        )
    if args.out:
        write_json_create(Path(args.out), payload)
    return payload


def _dispatch_adapter_session(args: argparse.Namespace) -> dict[str, Any]:
    if args.adapter_session_command == "start":
        _descriptor_path, descriptor = load_adapter_descriptor(
            args.adapter, Path(args.descriptor) if args.descriptor else None
        )
        profile = managed_launch_profile(descriptor)
        session = create_session(
            adapter_id=args.adapter,
            mode="INTERACTIVE",
            status="WAITING_FOR_TASK",
            launch_profile=profile,
            session_root=Path(args.session_root) if args.session_root else None,
        )
        launch_receipt = None
        status = "WAITING_FOR_TASK"
        host_launch_started = False
        blockers: list[dict[str, Any]] = []
        if args.launch:
            launch_receipt = launch_from_descriptor(
                descriptor=descriptor,
                session_id=session["sessionId"],
                launch_mode="interactive",
                policy_path=Path(args.env_policy) if args.env_policy else None,
            )
            host_launch_started = launch_receipt["hostLaunchStarted"]
            status = "LAUNCHED" if launch_receipt["status"] == "PASS" else "BLOCKED"
            blockers = launch_receipt.get("blockers", [])
            session["status"] = status
            update_session(session, session_root=Path(args.session_root) if args.session_root else None)
        payload = build_adapter_session_receipt(
            status=status,
            session_id=session["sessionId"],
            adapter_id=args.adapter,
            mode="INTERACTIVE",
            launch_profile=profile,
            progress_hook_default="off",
            host_launch_started=host_launch_started,
            blockers=blockers,
            launch_receipt=launch_receipt,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.adapter_session_command == "status":
        session = load_session(args.session, session_root=Path(args.session_root) if args.session_root else None)
        payload = build_adapter_session_receipt(
            status=session.get("status", "UNMANAGED"),
            session_id=session["sessionId"],
            adapter_id=session["adapterId"],
            mode=session.get("mode", "INTERACTIVE"),
            launch_profile=session.get("launchProfile", {}),
            state_identity=session.get("stateIdentity"),
            managed_workflow_proof=session.get("managedWorkflowProof"),
            progress_hook_default="off",
            state_written=False,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.adapter_session_command == "resume":
        payload = resume_adapter_session(
            session_id=args.session,
            session_root=Path(args.session_root) if args.session_root else None,
            adapter_id=args.adapter,
            state_path=Path(args.state) if args.state else None,
            task_id=args.task,
        )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    if args.adapter_session_command == "promote":
        _validate_adapter_progress_args(args)
        payload = promote_session_to_workflow(
            session_id=args.session,
            session_root=Path(args.session_root) if args.session_root else None,
            adapter_id=args.adapter,
            state_path=Path(args.state),
            task_id=args.task,
        )
        if payload.get("status") != "BLOCKED":
            _emit_adapter_progress(
                args, adapter_id=payload["adapterId"], state_path=Path(args.state), task_id=args.task
            )
        if args.out:
            write_json_create(Path(args.out), payload)
        return payload
    raise LifecycleError("command-not-implemented", "adapter session command is not implemented")


def _emit_adapter_progress(args: argparse.Namespace, *, adapter_id: str, state_path: Path, task_id: str) -> None:
    mode = getattr(args, "progress_hook", "off")
    if mode == "off":
        return
    _validate_adapter_progress_args(args)
    receipt = build_progress_hook_receipt(
        adapter_id=adapter_id,
        support_level="AUTO",
        command="workflow run",
        hook_point="after-workflow-run",
        hook_mode=mode,
        state_path=state_path,
        managed_workflow_proof={
            "kind": "alk-managed-workflow-command",
            "status": "PASS",
            "command": "workflow run",
            "adapterCommand": args.adapter_command,
            "taskId": task_id,
        },
    )
    if mode == "receipt":
        write_json_create(Path(args.progress_receipt), receipt)
    else:
        import sys

        sys.stderr.write(receipt["terminalText"].rstrip("\n") + "\n")


def _validate_adapter_progress_args(args: argparse.Namespace) -> None:
    if getattr(args, "progress_hook", "off") == "receipt" and not getattr(args, "progress_receipt", None):
        raise LifecycleError(
            "adapter-progress-receipt-path-missing", "--progress-hook receipt requires --progress-receipt"
        )
