"""Workflow artifact path and identity helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.canonical import canonical_bytes
from agent_lifecycle.contracts.paths import normalize_repo_path


def package_root(state_path: Path, state: dict[str, Any]) -> Path:
    raw = state.get("packageRoot")
    if isinstance(raw, str) and raw:
        return (state_path.parent / raw).resolve()
    return state_path.parent


def artifact_path(task: dict[str, Any], role: str, attempt: int) -> str:
    artifacts = task.get("artifactPaths")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get(role), str):
        raise LifecycleError(
            "missing-artifact-template",
            f"task {task.get('id')} has no {role} artifact template",
        )
    return normalize_repo_path(artifacts[role].replace("{attempt}", str(attempt)))


def artifact_identity(root: Path, path: str, value: dict[str, Any]) -> dict[str, Any]:
    data = canonical_bytes(value) + b"\n"
    actual = (root / path).read_bytes()
    if actual != data:
        raise LifecycleError(
            "non-canonical-artifact",
            f"artifact is not canonical JSON: {path}",
        )
    return {"path": path, "sha256": canonical_digest(value), "bytes": len(actual)}


def next_available_attempt(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
) -> int:
    max_attempts = int(state.get("budgets", {}).get("maxTaskAttempts", 1))
    current = int(task.get("attempt", 0))
    for attempt in range(current + 1, max_attempts + 1):
        if not attempt_artifacts_exist(state_path, state, task, attempt):
            return attempt
    raise LifecycleError(
        "task-attempt-output-conflict",
        f"task {task.get('id')} has no unoccupied attempt artifact path",
        {"maxTaskAttempts": max_attempts},
    )


def attempt_artifacts_exist(
    state_path: Path,
    state: dict[str, Any],
    task: dict[str, Any],
    attempt: int,
) -> bool:
    artifacts = task.get("artifactPaths", {})
    if not isinstance(artifacts, dict):
        return False
    root = package_root(state_path, state)
    for template in artifacts.values():
        if not isinstance(template, str):
            continue
        rendered = normalize_repo_path(template.replace("{attempt}", str(attempt)))
        if (root / rendered).exists():
            return True
    return False
