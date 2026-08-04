"""Descriptor-driven managed adapter launcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import build_launch_receipt
from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.contracts import LifecycleError, read_json_object


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
    profile = managed_launch_profile(descriptor)
    adapter_id = descriptor["adapterId"]
    timeout_seconds = float(profile.get("timeoutSeconds", 30.0))
    status = profile.get("status")
    if status != "SUPPORTED":
        reason = profile.get("reason") or f"managed launch profile is {status}"
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
            blockers=[{"code": "adapter-managed-launch-unsupported", "profileStatus": status, "reason": reason}],
        )
    argv = _resolve_argv(profile, launch_mode=launch_mode, task_id=task_id, state_path=state_path)
    env, env_receipt = resolve_launch_env(profile, policy_path=policy_path, process_env=process_env)
    result = run_process(argv, env=env, timeout_seconds=timeout_seconds)
    return build_launch_receipt(
        status=result["status"],
        adapter_id=adapter_id,
        session_id=session_id,
        launch_mode=launch_mode,
        argv=argv,
        timeout_seconds=timeout_seconds,
        env=env_receipt,
        exit_code=result["exitCode"],
        timed_out=result["timedOut"],
        stdout_tail=result["stdoutTail"],
        stderr_tail=result["stderrTail"],
        host_launch_started=True,
        blockers=result["blockers"],
    )


def _resolve_argv(
    profile: dict[str, Any],
    *,
    launch_mode: str,
    task_id: str | None,
    state_path: Path | None,
) -> list[str]:
    templates = profile.get("argvTemplates")
    if not isinstance(templates, dict):
        raise LifecycleError("adapter-managed-launch-argv-missing", "managed launch profile needs argvTemplates")
    raw = templates.get(launch_mode)
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise LifecycleError("adapter-managed-launch-argv-invalid", f"argv template missing for {launch_mode}")
    values = {
        "taskId": task_id or "",
        "state": state_path.as_posix() if state_path else "",
    }
    return [_render_template(item, values) for item in raw]


def _render_template(value: str, values: dict[str, str]) -> str:
    rendered = value
    for key, replacement in values.items():
        rendered = rendered.replace("{{" + key + "}}", replacement)
    return rendered
