"""Stable launcher facade; generic descriptor launch remains ``adapter-generic-launch-disabled``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.planning_launch import run_planning_launch
from agent_lifecycle.adapter_sessions.launch_execution import (
    capture_git_worktree_identity as _capture_git_worktree_identity,
    inspect_local_launch_profile as _inspect_local_launch_profile,
    launch_from_descriptor as _launch_from_descriptor,
    load_adapter_descriptor as _load_adapter_descriptor,
    managed_launch_profile as _managed_launch_profile,
    run_planning_qualification_candidate as _run_planning_qualification_candidate,
)
from agent_lifecycle.adapter_sessions.launch_preflight import launch_from_local_profile as _launch_from_local_profile
from agent_lifecycle.adapter_sessions.qualification import require_planning_qualification_receipt
from agent_lifecycle.freeze import verify_plan_package_integrity

PLANNING_OPERATION = "planningTask"
PLANNING_EXPLICIT_FLAG = "explicit_launch"
PLANNING_TASK_FIELD = "task_text"
PLANNING_WORKTREE_DRIFT_CODE = "planning-launch-worktree-drift"
PLANNING_QUALIFIED_STATUS = "PLANNING_ONLY_QUALIFIED"
HOST_IDENTITY_FIELD = "host_identity"
EXECUTABLE_IDENTITY_UNAVAILABLE = "executable-identity-unavailable"


def load_adapter_descriptor(adapter_id: str, descriptor_path: Path | None = None) -> tuple[Path, dict[str, Any]]:
    """Load one adapter descriptor through the implementation module."""

    return _load_adapter_descriptor(adapter_id, descriptor_path)


def managed_launch_profile(descriptor: dict[str, Any]) -> dict[str, Any]:
    """Return the managed profile from one descriptor."""

    return _managed_launch_profile(descriptor)


def launch_from_descriptor(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run the descriptor entry point while preserving the public runner seam."""

    return _launch_from_descriptor(*args, **kwargs)


def inspect_local_launch_profile(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Inspect a local profile without starting a host process."""

    return _inspect_local_launch_profile(*args, **kwargs)


def launch_from_local_profile(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run a bounded local-profile operation using the public process runner."""

    kwargs["process_runner"] = run_process
    return _launch_from_local_profile(*args, **kwargs)


def run_planning_qualification_candidate(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run one explicitly approved planning qualification candidate."""

    kwargs["capture_identity"] = capture_git_worktree_identity
    kwargs["planning_runner"] = run_planning_launch
    return _run_planning_qualification_candidate(*args, **kwargs)


def capture_git_worktree_identity(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Capture a stable identity for the current worktree."""

    return _capture_git_worktree_identity(*args, **kwargs)


__all__ = [
    "capture_git_worktree_identity",
    "inspect_local_launch_profile",
    "launch_from_descriptor",
    "launch_from_local_profile",
    "load_adapter_descriptor",
    "managed_launch_profile",
    "require_planning_qualification_receipt",
    "run_planning_qualification_candidate",
    "run_planning_launch",
    "run_process",
]
