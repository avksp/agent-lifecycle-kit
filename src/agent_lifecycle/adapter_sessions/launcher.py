"""Descriptor-driven managed adapter launcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.contracts import build_launch_receipt
from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.host_protocol.validation import validate_managed_launch_profile


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


def _timeout_seconds(profile: dict[str, Any]) -> float:
    timeout = profile.get("timeoutSeconds")
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0:
        return float(timeout)
    return 30.0
