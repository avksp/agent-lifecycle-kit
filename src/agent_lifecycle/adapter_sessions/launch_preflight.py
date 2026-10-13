"""Operation-specific local launch routes with explicit security gates."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.bootstrap_r11 import (
    claim_attempt_start,
    publish_attempt_result,
    record_uncertain_attempt,
    require_positive_attempt_result,
)
from agent_lifecycle.adapter_sessions.codex_exact_prompt import require_bootstrap_audit
from agent_lifecycle.adapter_sessions.codex_prompt_preparation import CLAIM as CODEX_SCOPED_CLAIM
from agent_lifecycle.adapter_sessions.codex_prompt_preparation import ROUTE_ID as CODEX_EXACT_ROUTE
from agent_lifecycle.adapter_sessions.codex_prompt_preparation import cleanup_prestart_raw, prepare_exact_prompt
from agent_lifecycle.adapter_sessions.contracts import (
    build_launch_receipt,
    build_local_launch_probe_receipt,
    build_local_launch_profile_receipt,
)
from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.immutable_input import (
    current_managed_invocation,
    planning_invocation_context,
    require_no_strong_protection,
    validate_current_invocation,
)
from agent_lifecycle.adapter_sessions.input_lifecycle import cleanup_no_start, record_proven_no_start
from agent_lifecycle.adapter_sessions.launch_execution import (
    _attach_qualification_receipt,
    _blocked_local_launch,
    _blocked_planning_launch,
    _managed_launch_blockers,
    _state_task,
    capture_git_worktree_identity,
)
from agent_lifecycle.adapter_sessions.local_launch_profile import (
    build_executable_identity,
    load_local_launch_profile,
    local_profile_summary,
    local_receipt_argv,
    planning_receipt_argv,
    render_local_launch_argv,
    render_planning_launch_argv,
)
from agent_lifecycle.adapter_sessions.ordinary_audit import verify_fresh_task_gate
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
from agent_lifecycle.workflow.risk_execution_gate import validate_task_risk_profile
from agent_lifecycle.workflow.closing_window import PROTECTED_OPERATOR_CLAIM, operator_claim_refusal


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
    shipped_digest: str | None
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
    route_id: str | None = None,
    requested_claim: str | None = None,
    input_request: Path | None = None,
    immutable_input_request: dict[str, Any] | None = None,
    immutable_input_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Select one local launch operation after loading and validating its profile."""

    if operation == "managedTask" and requested_claim == PROTECTED_OPERATOR_CLAIM:
        refusal = operator_claim_refusal(requested_claim)
        assert refusal is not None
        return build_launch_receipt(
            status="BLOCKED", adapter_id=adapter_id or "unknown", session_id=session_id,
            launch_mode="managedTask", argv=[], timeout_seconds=0.0, env={},
            exit_code=None, timed_out=False, host_launch_started=False,
            blockers=_no_start_cleanup_blockers(
                (project_root or Path.cwd()).absolute(), input_request,
                [{"code": refusal["reason"], "message": "Protected native operator route is unavailable"}],
            ),
        )
    try:
        context = _load_context(
            profile_path,
            adapter_id=adapter_id,
            project_root=project_root,
            process_env=process_env,
            process_runner=process_runner,
        )
    except (LifecycleError, OSError, ValueError) as exc:
        if input_request is None:
            raise
        code = exc.code if isinstance(exc, LifecycleError) else "local-launch-profile-read-failed"
        blockers = _no_start_cleanup_blockers(
            (project_root or Path.cwd()).absolute(), input_request,
            [{"code": code, "message": exc.message if isinstance(exc, LifecycleError)
              else "local launch profile could not be read"}],
        )
        return build_launch_receipt(
            status="BLOCKED", adapter_id=adapter_id or "unknown",
            session_id=session_id, launch_mode="managedTask", argv=[],
            timeout_seconds=0.0, env={}, exit_code=None, timed_out=False,
            host_launch_started=False, blockers=blockers,
        )
    try:
        request = require_no_strong_protection(immutable_input_request, expected_protection="NONE")
        if operation not in {"preflight", "planningTask", "managedTask"}:
            raise LifecycleError("a5-context-invalid", "Unknown launch operation")
        if operation == "preflight" and (
            immutable_input_context is not None or task_text is not None or task_id is not None
            or state_path is not None or manifest_path is not None or lock_path is not None
        ):
            raise LifecycleError("a5-context-invalid", "Version-only preflight cannot carry a task context")
    except LifecycleError as exc:
        blockers = _no_start_cleanup_blockers(context.root, input_request,
                                            [{"code": exc.code, "message": exc.message}])
        if operation == "planningTask":
            return _blocked_planning_launch(adapter_id=context.profile_adapter, session_id=session_id,
                requested_mode=requested_mode, task_text=task_text, input_source=input_source,
                blockers=blockers, profile_digest=context.profile_digest)
        return _blocked_local_launch(adapter_id=context.profile_adapter, session_id=session_id,
            timeout_seconds=context.timeout_seconds, env_receipt=context.env_receipt,
            blockers=blockers, profile_digest=context.profile_digest, risk_profile=risk_profile)
    if operation == "preflight":
        if any(value is not None for value in (route_id, requested_claim, input_request)):
            return _blocked_local_launch(
                adapter_id=context.profile_adapter, session_id=session_id,
                timeout_seconds=context.timeout_seconds, env_receipt=context.env_receipt,
                blockers=_no_start_cleanup_blockers(
                    context.root, input_request,
                    [{"code":"codex-exact-preflight-route-refused"}],
                ), profile_digest=context.profile_digest, risk_profile=risk_profile,
            )
        return _preflight(context)
    if operation == "planningTask":
        if any(value is not None for value in (route_id, requested_claim, input_request)):
            return _blocked_planning_launch(
                adapter_id=context.profile_adapter, session_id=session_id,
                requested_mode=requested_mode, task_text=task_text,
                input_source=input_source,
                blockers=_no_start_cleanup_blockers(
                    context.root, input_request,
                    [{"code":"codex-exact-planning-route-refused"}],
                ),
                profile_digest=context.profile_digest,
            )
        return _planning_task(
            context,
            session_id=session_id,
            explicit_launch=explicit_launch,
            requested_mode=requested_mode,
            task_text=task_text,
            input_source=input_source,
            advisory=advisory,
            immutable_input_request=request,
            immutable_input_context=immutable_input_context,
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
            route_id=route_id,
            requested_claim=requested_claim,
            input_request=input_request,
            immutable_input_request=request,
            immutable_input_context=immutable_input_context,
        )
    if input_request is not None:
        cleanup_no_start(context.root, None, input_request)
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
    immutable_input_request: dict[str, Any] | None = None,
    immutable_input_context: dict[str, Any] | None = None,
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
    identity: dict[str, Any] = {}
    try:
        request = require_no_strong_protection(immutable_input_request, expected_protection="NONE")
        argv = render_planning_launch_argv(context.profile)
        current = planning_invocation_context(
            adapter_id=context.profile_adapter, session_id=session_id, request=request,
            requested_mode=requested_mode, task_text=task_text, input_source=input_source,
            argv=argv, env=context.env, advisory=advisory, timeout_seconds=min(context.timeout_seconds, 300),
            process_cwd=context.root, profile_digest=context.profile_digest,
        )
        validate_current_invocation(immutable_input_context if immutable_input_context is not None else current,
                                    request, current_context=current)
        identity = _identity(context, strict=False)
        if identity["status"] != "PASS":
            raise LifecycleError(
                "local-launch-executable-identity-unavailable", "planning launch executable identity is unavailable"
            )
        qualification_receipt = require_planning_qualification_receipt(
            project_root=context.root,
            profile=context.profile,
            profile_digest=context.profile_digest,
            executable_identity=identity,
        )
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
            process_cwd=context.root,
            immutable_input_request=request,
            immutable_input_context=current,
            profile_digest=context.profile_digest,
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


def _no_start_cleanup_blockers(
    root: Path, input_request: Path | None, blockers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve the refusal and append a durable privacy failure if cleanup fails."""
    if input_request is None:
        return blockers
    try:
        cleanup_no_start(root, None, input_request)
    except LifecycleError as exc:
        if exc.code == "codex-exact-start-uncertain":
            raise
        return [*blockers, {"code": exc.code, "message": exc.message, "context": exc.details}]
    return blockers


def _original_attempt_deadline(state: dict[str, Any], task: dict[str, Any]) -> int:
    """Bridge the earlier immutable UTC deadline once, conservatively, before preparation."""
    mono = time.monotonic_ns()
    now = datetime.now(timezone.utc)
    try:
        deadlines = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in
                     (state.get("runDeadlineAt"), task.get("attemptDeadlineAt"))
                     if isinstance(value, str)]
        if len(deadlines) != 2 or any(value.utcoffset() is None or value.utcoffset().total_seconds() != 0
                                      for value in deadlines):
            raise ValueError("original UTC deadlines required")
        remaining = min(deadlines) - now
        ns = ((remaining.days * 86_400 + remaining.seconds) * 1_000_000 + remaining.microseconds) * 1_000
        if ns <= 0:
            raise ValueError("original deadline expired")
    except (TypeError, ValueError, OverflowError) as exc:
        raise LifecycleError("codex-exact-deadline-unavailable", "original run/attempt deadline is missing or expired") from exc
    return mono + ns


class _ExactPrestartRefusal(dict):
    """Internal result: context refused before touching prepared authority."""


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
    route_id: str | None,
    requested_claim: str | None,
    input_request: Path | None,
    immutable_input_request: dict[str, Any] | None = None,
    immutable_input_context: dict[str, Any] | None = None,
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
            blockers=_no_start_cleanup_blockers(context.root, input_request, blockers),
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
            blockers=_no_start_cleanup_blockers(
                context.root, input_request,
                [{"code": "local-launch-executable-identity-unavailable"}],
            ),
            profile_digest=context.profile_digest,
            risk_profile=risk_profile,
            host_identity=identity,
        )
    prepared: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    absolute_deadline_monotonic_ns: int | None = None
    try:
        manifest = read_json_object(manifest_path, label="frozen plan manifest")
        state = read_json_object(state_path, label="workflow state")
        lock = read_json_object(lock_path, label="plan lock")
        verify_plan_package_integrity(manifest, lock, repository_root=context.root)
        if manifest.get("status") != "FROZEN":
            raise LifecycleError("local-launch-frozen-plan-required", "local launch requires a frozen plan")
        task = _state_task(state, task_id)
        a5_inputs = {"state_path": state_path, "manifest_path": manifest_path, "lock_path": lock_path,
                     "task_id": task_id, "operation_id": operation_id, "source_revision": source_revision}
        current = current_managed_invocation(
            project_root=context.root, adapter_id=context.profile_adapter, session_id=session_id,
            request=immutable_input_request, profile=context.profile, profile_digest=context.profile_digest,
            risk_profile=risk_profile, **a5_inputs,
        )
        validate_current_invocation(immutable_input_context if immutable_input_context is not None else current,
                                    immutable_input_request, current_context=current)
        validate_task_risk_profile(
            state, task, risk_profile, operation_id=operation_id, source_revision=source_revision
        )
        exact_required = (
            manifest.get("package", {}).get("id") == "release-2-16"
            and isinstance(manifest.get("runtimePolicy", {}).get("preExecutionBootstrap"), dict)
            and context.profile_adapter == "codex"
        )
        if exact_required or any(value is not None for value in (route_id, requested_claim, input_request)):
            if context.profile_adapter != "codex":
                raise LifecycleError("codex-exact-adapter-mismatch", "exact prompt route requires Codex")
            if route_id != CODEX_EXACT_ROUTE or requested_claim != CODEX_SCOPED_CLAIM or input_request is None:
                raise LifecycleError("codex-exact-route-required", "explicit limited route request is required")
            if context.runner is not run_process:
                raise LifecycleError("codex-exact-runner-unobserved", "selected runner cannot prove child-start boundary")
            absolute_deadline_monotonic_ns = _original_attempt_deadline(state, task)
            prepared = prepare_exact_prompt(
                project_root=context.root, input_request=input_request,
                route_id=route_id, requested_claim=requested_claim,
                state=state, task=task, manifest=manifest, lock_path=lock_path,
                source_revision=source_revision, operation_id=operation_id,
                executable_identity=identity, executable=str(context.profile["executable"]),
                process_env=context.env, state_path=state_path,
                manifest_path=manifest_path,
            )
            audit = require_bootstrap_audit(
                context.root, plan_digest=canonical_digest(manifest),
                lock_sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                selected_binary_sha256=identity["executableContentSha256"],
                intent_path=prepared.get("intentPath"), state_path=state_path,
                profile=context.profile, executable_identity=identity, process_env=context.env,
            )
        else:
            qualification_receipt = require_qualification_receipt(
                project_root=context.root, profile=context.profile,
                profile_digest=context.profile_digest, executable_identity=identity,
            )
    except (LifecycleError, OSError, ValueError) as caught:
        exc = caught if isinstance(caught, LifecycleError) else LifecycleError(
            "codex-exact-preflight-unavailable", "exact route preflight could not read its evidence")
        if exc.code == "codex-exact-start-uncertain":
            raise exc
        if input_request is not None:
            try:
                if prepared is not None:
                    cleanup_prestart_raw(context.root, run_id=prepared["runId"], task_id=prepared["taskId"],
                        attempt_id=prepared["attemptId"], staging_source=None, proven_no_start=True)
                    record_proven_no_start(context.root, prepared["startReceiptPath"])
                else:
                    cleanup_no_start(context.root, None, input_request)
            except LifecycleError as cleanup_exc:
                if cleanup_exc.code == "codex-exact-start-uncertain":
                    raise
                exc = cleanup_exc
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
    if prepared is not None and audit is not None:
        result = _run_exact_managed_process(
            context, prepared=prepared, audit=audit, session_id=session_id,
            risk_profile=risk_profile, host_identity=identity,
            operation_id=operation_id,
            absolute_deadline_monotonic_ns=absolute_deadline_monotonic_ns,
            immutable_input_request=immutable_input_request,
            immutable_input_context=current,
            immutable_input_inputs=a5_inputs,
        )
        if isinstance(result, _ExactPrestartRefusal):
            # This owner created and validated prepared before calling the sink.
            # An unbound direct sink call cannot trigger this cleanup boundary.
            try:
                dispatch = prepared["startReceiptPath"].with_name("attempt-result-dispatched.json")
                if dispatch.exists() or dispatch.is_symlink():
                    raise LifecycleError("codex-exact-start-uncertain", "existing dispatch forbids no-start cleanup")
                cleanup_prestart_raw(context.root, run_id=prepared["runId"], task_id=prepared["taskId"],
                    attempt_id=prepared["attemptId"], staging_source=None, proven_no_start=True)
                record_proven_no_start(context.root, prepared["startReceiptPath"])
            except (LifecycleError, OSError, ValueError) as exc:
                raise LifecycleError("codex-exact-start-uncertain", "owned no-start cleanup could not be persisted",
                    {"costStatus": "UNAVAILABLE", "retryAuthorized": False}) from exc
            return dict(result)
        return result
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
        immutable_input_request=immutable_input_request,
        immutable_input_context=current,
    )


def _run_exact_managed_process(
    context: _LaunchContext, *, prepared: dict[str, Any], audit: dict[str, Any],
    session_id: str, risk_profile: dict[str, Any], host_identity: dict[str, Any],
    operation_id: str, absolute_deadline_monotonic_ns: int | None = None,
    immutable_input_request: dict[str, Any] | None = None,
    immutable_input_context: dict[str, Any] | None = None,
    immutable_input_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        require_no_strong_protection(immutable_input_request, expected_protection="NONE")
        if (immutable_input_context is None or type(immutable_input_inputs) is not dict
                or set(immutable_input_inputs) != {"state_path", "manifest_path", "lock_path",
                                                   "task_id", "operation_id", "source_revision"}
                or immutable_input_inputs["operation_id"] != operation_id):
            raise LifecycleError("a5-context-invalid", "Exact managed sink lacks a bound current invocation")
        current = current_managed_invocation(
            project_root=context.root, adapter_id=context.profile_adapter, session_id=session_id,
            request=immutable_input_request, profile=context.profile, profile_digest=context.profile_digest,
            risk_profile=risk_profile, **immutable_input_inputs,
        )
        validate_current_invocation(immutable_input_context, immutable_input_request, current_context=current)
    except (LifecycleError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, LifecycleError) else "a5-context-invalid"
        return _ExactPrestartRefusal(_blocked_local_launch(adapter_id=context.profile_adapter, session_id=session_id,
            timeout_seconds=context.timeout_seconds, env_receipt=context.env_receipt,
            blockers=[{"code": code}], profile_digest=context.profile_digest,
            risk_profile=risk_profile, host_identity=host_identity))
    try:
        prepared["verifyBeforeStart"]()
        if not isinstance(prepared.get("intentPath"), Path):
            raise LifecycleError("r11-result-reservation-missing", "prepared launch lacks a terminal reservation")
        verify_fresh_task_gate(context.root, audit=audit, intent_path=prepared["intentPath"],
                              profile=context.profile, executable_identity=host_identity,
                              process_env=context.env)
        if type(absolute_deadline_monotonic_ns) is not int or time.monotonic_ns() >= absolute_deadline_monotonic_ns:
            raise LifecycleError("codex-exact-deadline-unavailable", "original attempt deadline is unavailable or expired")
        claim_attempt_start(context.root, intent_path=prepared["intentPath"])
    except (LifecycleError, OSError, ValueError) as caught:
        exc = caught if isinstance(caught, LifecycleError) else LifecycleError(
            "codex-exact-raw-inventory-stale", "prelaunch source recheck failed")
        if exc.code == "codex-exact-start-uncertain":
            raise exc
        try:
            dispatch = prepared["startReceiptPath"].with_name("attempt-result-dispatched.json")
            if dispatch.exists() or dispatch.is_symlink():
                raise LifecycleError("codex-exact-start-uncertain", "existing dispatch forbids preflight no-start cleanup")
            cleanup_prestart_raw(
                context.root, run_id=prepared["runId"], task_id=prepared["taskId"],
                attempt_id=prepared["attemptId"], staging_source=None,
                proven_no_start=True)
            record_proven_no_start(context.root, prepared["startReceiptPath"])
        except (LifecycleError, OSError, ValueError) as cleanup_exc:
            exc = cleanup_exc if isinstance(cleanup_exc, LifecycleError) else LifecycleError(
                "codex-exact-start-uncertain", "preflight no-start proof could not be persisted")
        if exc.code == "codex-exact-start-uncertain":
            raise exc
        return _blocked_local_launch(
            adapter_id="codex", session_id=session_id,
            timeout_seconds=context.timeout_seconds, env_receipt=context.env_receipt,
            blockers=[{"code": exc.code, "message": exc.message}],
            profile_digest=context.profile_digest, risk_profile=risk_profile,
            host_identity=host_identity,
        )
    env = {**context.env, "CODEX_HOME": prepared["codexHome"]}
    try:
        result = context.runner(
            prepared["argv"], env=env, cwd=context.root,
            timeout_seconds=context.timeout_seconds, stdin_text=prepared["stdinText"],
            absolute_deadline_monotonic_ns=absolute_deadline_monotonic_ns,
            max_input_bytes=65_536, operation_id=operation_id,
            attempt_id=prepared["attemptId"], adapter_id="codex",
            on_started=prepared["onStarted"], on_input=prepared["onInput"],
        )
        if type(result.get("processStarted")) is not bool:
            raise LifecycleError("codex-exact-start-uncertain", "runner did not establish whether a child started")
    except Exception as exc:
        try:
            record_uncertain_attempt(context.root, intent_path=prepared["intentPath"])
        finally:
            raise LifecycleError("codex-exact-start-uncertain",
                                 "runner failed after possible child start; raw input and unknown cost retained",
                                 {"costStatus": "UNAVAILABLE", "retryAuthorized": False}) from exc
    started = result["processStarted"]
    terminal = None
    if not started:
        try:
            cleanup_prestart_raw(
                context.root, run_id=prepared["runId"], task_id=prepared["taskId"],
                attempt_id=prepared["attemptId"], staging_source=None,
                proven_no_start=True)
            record_proven_no_start(context.root, prepared["startReceiptPath"])
        except LifecycleError as exc:
            if exc.code == "codex-exact-start-uncertain":
                raise
            result = {**result, "status":"BLOCKED",
                      "blockers":[*result.get("blockers",[]), {"code":exc.code}]}
    if started and result.get("status") == "PASS":
        try:
            start = read_json_object(prepared["startReceiptPath"], label="observed process start")
            delivered = read_json_object(prepared["inputReceiptPath"], label="observed process input")
            if (start.get("stdinStatus") != "PENDING"
                    or delivered.get("status") != "COMPLETE"
                    or delivered.get("acceptedSha256") != prepared["finalPromptSha256"]):
                raise LifecycleError("codex-exact-process-join-invalid", "process start/input receipts differ")
        except (LifecycleError, OSError) as exc:
            code = exc.code if isinstance(exc, LifecycleError) else "codex-exact-process-join-missing"
            result = {**result, "status":"FAIL",
                      "blockers":[*result.get("blockers",[]), {"code":code,"costStatus":"UNAVAILABLE"}]}
    if started:
        try:
            terminal = publish_attempt_result(context.root, intent_path=prepared["intentPath"],
                                              process_result=result)
            if result["status"] == "PASS":
                terminal = require_positive_attempt_result(
                    context.root, intent_path=prepared["intentPath"], process_result=result)
        except (LifecycleError, OSError, ValueError, TypeError) as exc:
            terminal = None
            code = exc.code if isinstance(exc, LifecycleError) else "r11-result-publication-failed"
            blockers = [*result.get("blockers", []), {"code": code, "costStatus": "UNAVAILABLE"}]
            try:
                record_uncertain_attempt(context.root, intent_path=prepared["intentPath"])
            except (LifecycleError, OSError, ValueError):
                blockers.append({"code": "r11-result-uncertain-marker-failed", "costStatus": "UNAVAILABLE"})
            result = {**result, "status": "BLOCKED", "blockers": blockers}
    payload = build_launch_receipt(
        status=str(result["status"]), adapter_id="codex", session_id=session_id,
        launch_mode="managedTask", argv=prepared["argv"],
        timeout_seconds=context.timeout_seconds, env=context.env_receipt,
        exit_code=result.get("exitCode"), timed_out=bool(result.get("timedOut")),
        stdout_tail=str(result.get("stdoutTail", "")),
        stderr_tail=str(result.get("stderrTail", "")),
        stdout_redacted=bool(result.get("stdoutRedacted")),
        stderr_redacted=bool(result.get("stderrRedacted")),
        host_launch_started=started, blockers=list(result.get("blockers", [])),
        profile_digest=context.profile_digest,
        risk_profile_digest=str(risk_profile["profileDigest"]),
        receipt_argv=["codex", "exec", "--json", "--ephemeral", "-m", "<model>", "-C", "<cwd>", "-"],
        host_identity=host_identity,
    )
    payload["exactPrompt"] = {
        "routeId":CODEX_EXACT_ROUTE, "requestedClaim":CODEX_SCOPED_CLAIM,
        "scope":"ALK_CONTROLLED_OUTBOUND_INPUT_FIT", "hostOwnedInput":"UNAVAILABLE",
        "wholeCallUpperBoundU":"UNAVAILABLE", "fullFinancial":False,
        "sealedRequestSha256":prepared["sealedSha256"],
        "finalPromptSha256":prepared["finalPromptSha256"],
        "fitReceiptDigest":prepared["fitReceiptDigest"],
        "bootstrapAuditSha256":audit["auditSha256"],
        "startReceiptSha256":_optional_receipt_sha(prepared["startReceiptPath"]) if started else None,
        "inputReceiptSha256":_optional_receipt_sha(prepared["inputReceiptPath"]) if started else None,
        "terminalResultSha256":_optional_receipt_sha(
            prepared["intentPath"].with_name("attempt-result-terminal.json")) if terminal else None,
        "terminalStatus":terminal["status"] if terminal else ("START_UNCERTAIN" if started else "NOT_STARTED"),
        "retryAuthorized":False,
        "costStatus":"UNAVAILABLE" if started else "NOT_STARTED",
    }
    payload["modelCallsStarted"] = started
    payload["receiptDigest"] = canonical_digest({k:v for k,v in payload.items() if k != "receiptDigest"})
    return payload


def _optional_receipt_sha(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest() if data else None


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
    qualification_receipt: dict[str, Any] | None,
    host_identity: dict[str, Any],
    immutable_input_request: dict[str, Any] | None = None,
    immutable_input_context: dict[str, Any] | None = None,
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
        require_no_strong_protection(immutable_input_request, expected_protection="NONE")
        if immutable_input_context is None:
            raise LifecycleError("a5-context-invalid", "Managed sink lacks a bound current invocation")
        current = current_managed_invocation(
            project_root=context.root, state_path=state_path, manifest_path=manifest_path, lock_path=lock_path,
            task_id=task_id, operation_id=operation_id, source_revision=source_revision,
            adapter_id=context.profile_adapter, session_id=session_id, request=immutable_input_request,
            profile=context.profile, profile_digest=context.profile_digest, risk_profile=risk_profile,
        )
        validate_current_invocation(immutable_input_context, immutable_input_request, current_context=current)
        state = read_json_object(state_path, label="workflow state")
        validate_task_risk_profile(state, _state_task(state, task_id), risk_profile,
                                   operation_id=operation_id, source_revision=source_revision)
        argv = render_local_launch_argv(context.profile, bindings)
    except (LifecycleError, OSError, ValueError) as caught:
        exc = caught if isinstance(caught, LifecycleError) else LifecycleError(
            "a5-context-invalid", "Managed sink could not reopen current authority")
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
    try:
        result = context.runner(argv, env=context.env, timeout_seconds=context.timeout_seconds)
        if not isinstance(result, dict) or type(result.get("processStarted")) is not bool or (
            result["processStarted"] is False and (result.get("status") == "PASS"
                or result.get("startedFailure") is True or result.get("processReceipt") is not None)
        ):
            raise ValueError("runner did not establish a consistent physical start")
    except Exception as exc:
        raise LifecycleError("local-launch-start-uncertain", "runner result cannot establish physical start",
                             {"costStatus": "UNAVAILABLE", "retryAuthorized": False}) from exc
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
        host_launch_started=result["processStarted"],
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
