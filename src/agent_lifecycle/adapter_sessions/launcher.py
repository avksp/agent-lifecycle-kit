"""Descriptor-driven managed adapter launcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import (
    build_launch_receipt,
    build_local_launch_probe_receipt,
    build_local_launch_profile_receipt,
)
from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.local_launch_profile import (
    load_local_launch_profile,
    local_receipt_argv,
    local_profile_summary,
    render_local_launch_argv,
)
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.qualification import (
    build_qualification_receipt,
    require_qualification_receipt,
    write_qualification_receipt,
)
from agent_lifecycle.contracts import LifecycleError, canonical_digest, read_json_object
from agent_lifecycle.freeze import verify_plan_lock
from agent_lifecycle.host_protocol.validation import validate_managed_launch_profile
from agent_lifecycle.workflow.risk_execution_gate import validate_task_risk_profile


def load_adapter_descriptor(adapter_id: str, descriptor_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    path = descriptor_path or Path("adapters") / adapter_id / "adapter.descriptor.json"
    descriptor = read_json_object(path, label="adapter descriptor")
    if descriptor.get("adapterId") != adapter_id:
        raise LifecycleError("adapter-descriptor-id-mismatch", "descriptor adapterId does not match requested adapter")
    return path, descriptor


def managed_launch_profile(descriptor: dict[str, Any]) -> dict[str, Any]:
    profile = descriptor.get("managedLaunch")
    if not isinstance(profile, dict):
        raise LifecycleError("adapter-managed-launch-missing", "adapter descriptor must declare managedLaunch")
    return profile


def launch_from_descriptor(
    *,
    descriptor: dict[str, Any],
    session_id: str,
    launch_mode: str,
    task_id: str | None = None,
    state_path: Path | None = None,
    policy_path: Path | None = None,
    process_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Block generic descriptor-driven launch until the qualified local route exists."""

    del task_id, state_path, policy_path, process_env
    raw_profile = descriptor.get("managedLaunch")
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    validation = validate_managed_launch_profile(profile)
    adapter_id = descriptor.get("adapterId") if isinstance(descriptor.get("adapterId"), str) else "unknown"
    timeout_seconds = _timeout_seconds(profile)
    blockers: list[dict[str, Any]] = []
    if validation["status"] != "PASS":
        blockers.append(
            {
                "code": "adapter-generic-launch-invalid-descriptor",
                "validationBlockers": validation["blockers"],
            }
        )
    blockers.append(
        {
            "code": "adapter-generic-launch-disabled",
            "profileStatus": profile.get("status"),
            "reason": "generic descriptor-driven launch is disabled until a qualified local-profile route exists",
        }
    )
    return build_launch_receipt(
        status="BLOCKED",
        adapter_id=adapter_id,
        session_id=session_id,
        launch_mode=launch_mode,
        argv=[],
        timeout_seconds=timeout_seconds,
        env={"includedNames": [], "valuesRedacted": True, "secretValuesStored": False},
        exit_code=None,
        timed_out=False,
        blockers=blockers,
    )


def inspect_local_launch_profile(
    profile_path: Path,
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Inspect a local profile without reaching the process boundary."""

    root = (project_root or Path.cwd()).absolute()
    relative, profile, validation = load_local_launch_profile(profile_path, project_root=root)
    return build_local_launch_profile_receipt(
        status="PASS",
        operation="INSPECT",
        profile_path=relative.as_posix(),
        profile_summary=local_profile_summary(profile),
        profile_digest=validation["profileDigest"],
        process_calls=0,
    )


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
) -> dict[str, Any]:
    """Run one bounded probe or one fully bound managed host process."""

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
    timeout_seconds = float(profile["timeoutSeconds"])

    if operation == "preflight":
        argv = [str(profile["executable"]), *profile["versionProbeArgs"]]
        probe_timeout = min(timeout_seconds, 10.0)
        result = run_process(argv, env=env, timeout_seconds=probe_timeout)
        probe = build_local_launch_probe_receipt(
            argv=[local_receipt_argv(profile)[0], *profile["versionProbeArgs"]],
            timeout_seconds=probe_timeout,
            env=env_receipt,
            result=result,
        )
        qualification_receipt = None
        blockers = list(result.get("blockers", []))
        if isinstance(profile.get("qualification"), dict):
            qualification_receipt = build_qualification_receipt(
                profile=profile,
                profile_digest=profile_digest,
                probe_receipt=probe,
            )
            blockers.extend(qualification_receipt["blockers"])
            write_qualification_receipt(root, profile, qualification_receipt)
        payload = build_local_launch_profile_receipt(
            status="PASS" if result["status"] == "PASS" and not blockers else "FAIL",
            operation="PREFLIGHT",
            profile_path=relative.as_posix(),
            profile_summary=local_profile_summary(profile),
            profile_digest=profile_digest,
            process_calls=1,
            probe_receipt=probe,
            blockers=blockers,
        )
        return _attach_qualification_receipt(payload, qualification_receipt)
    if operation != "managedTask":
        raise LifecycleError("local-launch-operation-invalid", "local launch operation is unsupported")

    blockers = _managed_launch_blockers(
        explicit_launch=explicit_launch,
        state_path=state_path,
        manifest_path=manifest_path,
        lock_path=lock_path,
        task_id=task_id,
        operation_id=operation_id,
        source_revision=source_revision,
        risk_profile=risk_profile,
        adapter_id=profile_adapter,
    )
    if blockers:
        return _blocked_local_launch(
            adapter_id=profile_adapter,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            env_receipt=env_receipt,
            blockers=blockers,
            profile_digest=profile_digest,
            risk_profile=risk_profile,
        )

    assert state_path is not None
    assert manifest_path is not None
    assert lock_path is not None
    assert task_id is not None
    assert operation_id is not None
    assert source_revision is not None
    assert risk_profile is not None
    manifest = read_json_object(manifest_path, label="frozen plan manifest")
    state = read_json_object(state_path, label="workflow state")
    lock = read_json_object(lock_path, label="plan lock")
    try:
        verify_plan_lock(manifest, lock)
        if manifest.get("status") != "FROZEN":
            raise LifecycleError("local-launch-frozen-plan-required", "local launch requires a frozen plan")
        task = _state_task(state, task_id)
        validate_task_risk_profile(
            state,
            task,
            risk_profile,
            operation_id=operation_id,
            source_revision=source_revision,
        )
        qualification_receipt = require_qualification_receipt(
            project_root=root,
            profile=profile,
            profile_digest=profile_digest,
        )
    except LifecycleError as exc:
        return _blocked_local_launch(
            adapter_id=profile_adapter,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            env_receipt=env_receipt,
            blockers=[{"code": exc.code, "message": exc.message, "context": exc.details}],
            profile_digest=profile_digest,
            risk_profile=risk_profile,
        )

    bindings = {
        "adapter_id": profile_adapter,
        "state_path": state_path.as_posix(),
        "manifest_path": manifest_path.as_posix(),
        "lock_path": lock_path.as_posix(),
        "task_id": task_id,
        "operation_id": operation_id,
        "source_revision": source_revision,
        "risk_profile_digest": str(risk_profile["profileDigest"]),
    }
    try:
        argv = render_local_launch_argv(profile, bindings)
    except LifecycleError as exc:
        return _blocked_local_launch(
            adapter_id=profile_adapter,
            session_id=session_id,
            timeout_seconds=timeout_seconds,
            env_receipt=env_receipt,
            blockers=[{"code": exc.code, "message": exc.message, "context": exc.details}],
            profile_digest=profile_digest,
            risk_profile=risk_profile,
        )
    result = run_process(argv, env=env, timeout_seconds=timeout_seconds)
    payload = build_launch_receipt(
        status=str(result["status"]),
        adapter_id=profile_adapter,
        session_id=session_id,
        launch_mode="managedTask",
        argv=argv,
        timeout_seconds=timeout_seconds,
        env=env_receipt,
        exit_code=result.get("exitCode"),
        timed_out=bool(result.get("timedOut")),
        stdout_tail=str(result.get("stdoutTail", "")),
        stderr_tail=str(result.get("stderrTail", "")),
        stdout_redacted=bool(result.get("stdoutRedacted")),
        stderr_redacted=bool(result.get("stderrRedacted")),
        host_launch_started=True,
        blockers=list(result.get("blockers", [])),
        profile_digest=profile_digest,
        risk_profile_digest=str(risk_profile["profileDigest"]),
        receipt_argv=local_receipt_argv(profile),
    )
    return _attach_qualification_receipt(payload, qualification_receipt)


def _attach_qualification_receipt(payload: dict[str, Any], receipt: dict[str, Any] | None) -> dict[str, Any]:
    body = {key: value for key, value in payload.items() if key != "receiptDigest"}
    body["qualificationReceipt"] = receipt
    return {**body, "receiptDigest": canonical_digest(body)}
def _timeout_seconds(profile: dict[str, Any]) -> float:
    timeout = profile.get("timeoutSeconds")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
        return float(timeout)
    return 30.0


def _managed_launch_blockers(
    *,
    explicit_launch: bool,
    state_path: Path | None,
    manifest_path: Path | None,
    lock_path: Path | None,
    task_id: str | None,
    operation_id: str | None,
    source_revision: str | None,
    risk_profile: dict[str, Any] | None,
    adapter_id: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not explicit_launch:
        blockers.append({"code": "local-launch-explicit-flag-required"})
    missing = [
        field
        for field, value in {
            "state": state_path,
            "manifest": manifest_path,
            "lock": lock_path,
            "task": task_id,
            "operationId": operation_id,
            "sourceRevision": source_revision,
            "riskProfile": risk_profile,
        }.items()
        if value is None or value == ""
    ]
    if missing:
        blockers.append({"code": "local-launch-frozen-binding-missing", "fields": missing})
    if isinstance(risk_profile, dict) and risk_profile.get("adapterId") != adapter_id:
        blockers.append({"code": "local-launch-risk-profile-adapter-mismatch"})
    return blockers


def _blocked_local_launch(
    *,
    adapter_id: str,
    session_id: str,
    timeout_seconds: float,
    env_receipt: dict[str, Any],
    blockers: list[dict[str, Any]],
    profile_digest: str,
    risk_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    risk_digest = risk_profile.get("profileDigest") if isinstance(risk_profile, dict) else None
    return build_launch_receipt(
        status="BLOCKED",
        adapter_id=adapter_id,
        session_id=session_id,
        launch_mode="managedTask",
        argv=[],
        timeout_seconds=timeout_seconds,
        env=env_receipt,
        exit_code=None,
        timed_out=False,
        host_launch_started=False,
        blockers=blockers,
        profile_digest=profile_digest,
        risk_profile_digest=risk_digest if isinstance(risk_digest, str) else None,
    )


def _state_task(state: dict[str, Any], task_id: str) -> dict[str, Any]:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        raise LifecycleError("local-launch-state-tasks-missing", "workflow state tasks are missing")
    for task in tasks:
        if isinstance(task, dict) and task.get("id") == task_id:
            return task
    raise LifecycleError("local-launch-task-missing", "task is not present in workflow state", {"taskId": task_id})
