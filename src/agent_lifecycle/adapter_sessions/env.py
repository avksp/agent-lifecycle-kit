"""Allowlisted environment resolution for managed adapter launches."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, read_json_object
from agent_lifecycle.adapter_sessions.redaction import redact_env_names


def resolve_launch_env(
    profile: dict[str, Any],
    *,
    policy_path: Path | None = None,
    process_env: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Return only allowlisted environment values and a redacted receipt view."""

    env_policy = profile.get("env", {}) if isinstance(profile.get("env"), dict) else {}
    names = set(_strings(env_policy.get("allow")))
    _reject_wildcards(_strings(env_policy.get("allowPatterns")))
    if policy_path is not None:
        if not env_policy.get("projectPolicyAllowed", False):
            raise LifecycleError("adapter-env-policy-not-allowed", "descriptor does not allow project env policy extension")
        policy = read_json_object(policy_path, label="adapter env policy")
        names.update(_strings(policy.get("allow")))
        _reject_wildcards(_strings(policy.get("allowPatterns")))
    source = dict(os.environ if process_env is None else process_env)
    selected: dict[str, str] = {}
    for name, value in source.items():
        if name in names:
            selected[name] = value
    return selected, redact_env_names(list(selected))


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise LifecycleError("adapter-env-policy-invalid", "env policy entries must be non-empty strings")
    return value


def _reject_wildcards(patterns: list[str]) -> None:
    if patterns:
        raise LifecycleError(
            "adapter-env-wildcard-disallowed",
            "generic launcher accepts only exact environment variable names",
            {"patterns": sorted(set(patterns))},
        )
