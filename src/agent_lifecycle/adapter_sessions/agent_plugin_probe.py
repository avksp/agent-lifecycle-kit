"""Composition adapter that supplies bounded process execution to host protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.env import resolve_launch_env
from agent_lifecycle.adapter_sessions.process import run_process


def build_agent_plugin_probe_runner(
    profile: dict[str, Any],
    project_root: Path,
) -> Any:
    """Build the process runner used by the explicit qualification probe."""

    launch_profile = {**profile, "env": profile.get("environment", {})}
    env, _ = resolve_launch_env(launch_profile)
    timeout = float(profile["qualification"]["timeoutSeconds"])
    output_limit = int(profile["qualification"]["maxOutputBytes"])

    def runner(argv: list[str], _timeout: float) -> dict[str, Any]:
        return run_process(
            argv,
            env=env,
            timeout_seconds=timeout,
            cwd=project_root,
            max_output_bytes=output_limit,
        )

    return runner


__all__ = ["build_agent_plugin_probe_runner"]
