"""Operation-specific local launch routes with explicit security gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_lifecycle.adapter_sessions.contracts import (
    build_launch_receipt,
    build_local_launch_probe_receipt,
    build_local_launch_profile_receipt,
)
from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.local_launch_profile import (
    build_executable_identity,
    load_local_launch_profile,
    local_receipt_argv,
    local_profile_summary,
    planning_receipt_argv,
    render_local_launch_argv,
    render_planning_launch_argv,
)
from agent_lifecycle.adapter_sessions.planning_launch import run_planning_launch
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.qualification import (
    build_qualification_receipt,
    require_planning_qualification_receipt,
    require_qualification_receipt,
    shipped_profile_digest,
    write_qualification_receipt,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.freeze import verify_plan_package_integrity
from agent_lifecycle.host_protocol.validation import validate_managed_launch_profile
from agent_lifecycle.workflow.risk_execution_gate import validate_task_risk_profile

from agent_lifecycle.adapter_sessions.launch_execution import (
    _attach_qualification_receipt,
    _blocked_local_launch,
    _blocked_planning_launch,
    _managed_launch_blockers,
    _planning_qualification_report,
    _state_task,
    capture_git_worktree_identity,
)


@dataclass(frozen=True)
class _LaunchContext:
    root: Path
    relative: Path
    profile: dict[str, Any]
    profile_digest: str
    profile_adapter: str
    env: dict[str, str]
    env_receipt: dict[str, Any]
    timeout_seconds: float
    shipped_digest: str
    runner: Callable[..., dict[str, Any]]


def launch_from_local_profile(
    *,
    profile_path: Path,
    operation: str,
    adapter_id: str | None = None,
    session_id: str = "local-profile",
    project_root: Path | None = None,
    explicit_launch: bool = False,
    state_path: Path | None = None,
    manifest_path: Path | None = None,
    lock_path: Path | None = None,
    task_id: str | None = None,
    operation_id: str | None = None,
    source_revision: str | None = None,
    risk_profile: dict[str, Any] | None = None,
    process_env: dict[str, str] | None = None,
    requested_mode: str | None = None,
    task_text: str | None = None,
    input_source: str = "text",
    advisory: dict[str, Any] | None = None,
    process_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Select one local launch operation after loading and validating its profile."""

    context = _load_context(
        profile_path,
        adapter_id=adapter_id,
        project_root=project_root,
        process_env=process_env,
        process_runner=process_runner,
    )
    if operation == "preflight":
        return _preflight(context)
    if operation == "planningTask":
        return _planning_task(
            context,
            session_id=session_id,
            explicit_launch=explicit_launch,
            requested_mode=requested_mode,
            task_text=task_text,
            input_source=input_source,
            advisory=advisory,
        )
    if operation == "managedTask":
        return _managed_task(
            context,
            session_id=session_id,
            explicit_launch=explicit_launch,
            state_path=state_path,
            manifest_path=manifest_path,
            lock_path=lock_path,
            task_id=task_id,
            operation_id=operation_id,
            source_revision=source_revision,
            risk_profile=risk_profile,
        )
    raise LifecycleError("local-launch-operation-invalid", "local launch operation is unsupported")


def _load_context(
    profile_path: Path,
    *,
    adapter_id: str | None,
    project_root: Path | None,
    process_env: dict[str, str] | None,
    process_runner: Callable[..., dict[str, Any]] | None,
) -> _LaunchContext:
    root = (project_root or Path.cwd()).absolute()
    relative, profile, validation = load_local_launch_profile(profile_path, project_root=root)
    profile_digest = str(validation["profileDigest"])
    profile_adapter = str(profile["adapterId"])
    if adapter_id is not None and adapter_id != profile_adapter:
        raise LifecycleError(
            "local-launch-profile-adapter-mismatch",
            "local launch profile does not match the requested adapter",
            {"expected": adapter_id, "actual": profile_adapter},
        )
    env, env_receipt = resolve_launch_env(profile, process_env=process_env)
    return _LaunchContext(
        root=root,
        relative=relative,
        profile=profile,
        profile_digest=profile_digest,
        profile_adapter=profile_adapter,
        env=env,
        env_receipt=env_receipt,
        timeout_seconds=float(profile["timeoutSeconds"]),
        shipped_digest=shipped_profile_digest(profile_adapter, repository_root=root),
        runner=process_runner or run_process,
    )


def _preflight(context: _LaunchContext) -> dict[str, Any]:
    identity = _identity(context, strict=False)
    if identity["status"] != "PASS":
        return build_local_launch_profile_receipt(
            status="FAIL",
            operation="PREFLIGHT",
            profile_path=context.relative.as_posix(),
            profile_summary=local_profile_summary(context.profile),
            profile_digest=context.profile_digest,
            process_calls=0,
            host_identity=identity,
            blockers=[{"code": "local-launch-executable-identity-unavailable"}],
        )
    argv = [str(context.profile["executable"]), *context.profile["versionProbeArgs"]]
    probe_timeout = min(context.timeout_seconds, 10.0)
    result = context.runner(argv, env=context.env, timeout_seconds=probe_timeout)
    probe = build_local_launch_probe_receipt(
        argv=[local_receipt_argv(context.profile)[0], *context.profile["versionProbeArgs"]],
        timeout_seconds=probe_timeout,
        env=context.env_receipt,
        result=result,
    )
    qualification_receipt = None
    blockers = list(result.get("blockers", []))
    if isinstance(context.profile.get("qualification"), dict):
        qualification_receipt = build_qualification_receipt(
            profile=context.profile,
            profile_digest=context.profile_digest,
            probe_receipt=probe,
            executable_identity=identity,
        )
        blockers.extend(qualification_receipt["blockers"])
        write_qualification_receipt(context.root, context.profile, qualification_receipt)
    payload = build_local_launch_profile_receipt(
        status="PASS" if result["status"] == "PASS" and not blockers else "FAIL",
        operation="PREFLIGHT",
        profile_path=context.relative.as_posix(),
        profile_summary=local_profile_summary(context.profile),
        profile_digest=context.profile_digest,
        process_calls=1,
        probe_receipt=probe,
        blockers=blockers,
        host_identity=identity,
    )
    return _attach_qualification_receipt(payload, qualification_receipt)


def _planning_task(
    context: _LaunchContext,
    *,
    session_id: str,
    explicit_launch: bool,
    requested_mode: str | None,
    task_text: str | None,
    input_source: str,
    advisory: dict[str, Any] | None,
) -> dict[str, Any]:
    if not explicit_launch:
        return _blocked_planning_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            requested_mode=requested_mode,
            task_text=task_text,
            input_source=input_source,
            blockers=[{"code": "planning-launch-explicit-flag-required"}],
            profile_digest=context.profile_digest,
        )
    if requested_mode not in {"auto", "research", "plan", "review"} or not isinstance(task_text, str):
        return _blocked_planning_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            requested_mode=requested_mode,
            task_text=task_text,
            input_source=input_source,
            blockers=[{"code": "planning-launch-input-invalid"}],
            profile_digest=context.profile_digest,
        )
    identity = _identity(context, strict=False)
    try:
        if identity["status"] != "PASS":
            raise LifecycleError("local-launch-executable-identity-unavailable", "planning launch executable identity is unavailable")
        qualification_receipt = require_planning_qualification_receipt(
            project_root=context.root,
            profile=context.profile,
            profile_digest=context.profile_digest,
            executable_identity=identity,
        )
        argv = render_planning_launch_argv(context.profile)
        before = capture_git_worktree_identity(context.root)
        receipt = run_planning_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            requested_mode=requested_mode,
            task_text=task_text,
            input_source=input_source,
            argv=argv,
            env=context.env,
            advisory=advisory,
            timeout_seconds=context.timeout_seconds,
        )
        after = capture_git_worktree_identity(context.root)
    except LifecycleError as exc:
        return _blocked_planning_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            requested_mode=requested_mode,
            task_text=task_text,
            input_source=input_source,
            blockers=[{"code": exc.code, "message": exc.message, "context": exc.details}],
            profile_digest=context.profile_digest,
            host_identity=identity,
        )
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    body["profileDigest"] = context.profile_digest
    body["qualificationReceipt"] = qualification_receipt
    body["receiptArgv"] = planning_receipt_argv(context.profile)
    body["worktreeIdentity"] = {
        "beforeDigest": before["identityDigest"],
        "afterDigest": after["identityDigest"],
        "unchanged": before["identityDigest"] == after["identityDigest"],
        "before": before,
        "after": after,
    }
    if before["identityDigest"] != after["identityDigest"]:
        body["status"] = "BLOCKED"
        body["result"] = None
        body["blockers"] = [
            *list(body.get("blockers", [])),
            {
                "code": "planning-launch-worktree-drift",
                "message": "planning host changed authoritative repository state; ALK did not revert it",
            },
        ]
    return {**body, "receiptDigest": canonical_digest(body)}


def _managed_task(
    context: _LaunchContext,
    *,
    session_id: str,
    explicit_launch: bool,
    state_path: Path | None,
    manifest_path: Path | None,
    lock_path: Path | None,
    task_id: str | None,
    operation_id: str | None,
    source_revision: str | None,
    risk_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers = _managed_launch_blockers(
        explicit_launch=explicit_launch,
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        task_id=task_id,
        operation_id=operation_id,
        source_revision=source_revision,
        risk_profile=risk_profile,
        adapter_id=context.profile_adapter,
    )
    if blockers:
        return _blocked_local_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            timeout_seconds=context.timeout_seconds,
            env_receipt=context.env_receipt,
            blockers=blockers,
            profile_digest=context.profile_digest,
            risk_profile=risk_profile,
        )
    assert state_path is not None and manifest_path is not None and lock_path is not None
    assert task_id is not None and operation_id is not None and source_revision is not None
    assert risk_profile is not None
    identity = _identity(context, strict=False)
    if identity["status"] != "PASS":
        return _blocked_local_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            timeout_seconds=context.timeout_seconds,
            env_receipt=context.env_receipt,
            blockers=[{"code": "local-launch-executable-identity-unavailable"}],
            profile_digest=context.profile_digest,
            risk_profile=risk_profile,
            host_identity=identity,
        )
    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    state = read_json_object(state_path, label="workflow state")
    lock = read_json_object(lock_path, label="plan lock")
    try:
        verify_plan_package_integrity(manifest, lock, repository_root=context.root)
        if manifest.get("status") != "FROZEN":
            raise LifecycleError("local-launch-frozen-plan-required", "local launch requires a frozen plan")
        task = _state_task(state, task_id)
        validate_task_risk_profile(state, task, risk_profile, operation_id=operation_id, source_revision=source_revision)
        qualification_receipt = require_qualification_receipt(
            project_root=context.root,
            profile=context.profile,
            profile_digest=context.profile_digest,
            executable_identity=identity,
        )
    except LifecycleError as exc:
        return _blocked_local_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            timeout_seconds=context.timeout_seconds,
            env_receipt=context.env_receipt,
            blockers=[{"code": exc.code, "message": exc.message, "context": exc.details}],
            profile_digest=context.profile_digest,
            risk_profile=risk_profile,
            host_identity=identity,
        )
    return _run_managed_process(
        context,
        session_id=session_id,
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        task_id=task_id,
        operation_id=operation_id,
        source_revision=source_revision,
        risk_profile=risk_profile,
        qualification_receipt=qualification_receipt,
        host_identity=identity,
    )


def _run_managed_process(
    context: _LaunchContext,
    *,
    session_id: str,
    state_path: Path,
    manifest_path: Path,
    lock_path: Path,
    task_id: str,
    operation_id: str,
    source_revision: str,
    risk_profile: dict[str, Any],
    qualification_receipt: dict[str, Any],
    host_identity: dict[str, Any],
) -> dict[str, Any]:
    bindings = {
        "adapter_id": context.profile_adapter,
        "state_path": state_path.as_posix(),
        "manifest_path": manifest_path.as_posix(),
        "lock_path": lock_path.as_posix(),
        "task_id": task_id,
        "operation_id": operation_id,
        "source_revision": source_revision,
        "risk_profile_digest": str(risk_profile["profileDigest"]),
    }
    try:
        argv = render_local_launch_argv(context.profile, bindings)
    except LifecycleError as exc:
        return _blocked_local_launch(
            adapter_id=context.profile_adapter,
            session_id=session_id,
            timeout_seconds=context.timeout_seconds,
            env_receipt=context.env_receipt,
            blockers=[{"code": exc.code, "message": exc.message, "context": exc.details}],
            profile_digest=context.profile_digest,
            risk_profile=risk_profile,
            host_identity=host_identity,
        )
    result = context.runner(argv, env=context.env, timeout_seconds=context.timeout_seconds)
    payload = build_launch_receipt(
        status=str(result["status"]),
        adapter_id=context.profile_adapter,
        session_id=session_id,
        launch_mode="managedTask",
        argv=argv,
        timeout_seconds=context.timeout_seconds,
        env=context.env_receipt,
        exit_code=result.get("exitCode"),
        timed_out=bool(result.get("timedOut")),
        stdout_tail=str(result.get("stdoutTail", "")),
        stderr_tail=str(result.get("stderrTail", "")),
        stdout_redacted=bool(result.get("stdoutRedacted")),
        stderr_redacted=bool(result.get("stderrRedacted")),
        host_launch_started=True,
        blockers=list(result.get("blockers", [])),
        profile_digest=context.profile_digest,
        risk_profile_digest=str(risk_profile["profileDigest"]),
        receipt_argv=local_receipt_argv(context.profile),
        host_identity=host_identity,
    )
    return _attach_qualification_receipt(payload, qualification_receipt)


def _identity(context: _LaunchContext, *, strict: bool) -> dict[str, Any]:
    return build_executable_identity(
        context.profile,
        process_env=context.env,
        profile_digest=context.profile_digest,
        shipped_profile_digest=context.shipped_digest,
        strict=strict,
    )


__all__ = ["launch_from_local_profile"]
