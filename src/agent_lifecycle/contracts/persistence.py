"""Shared private persistence primitives for local lifecycle state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.canonical import (
    canonical_digest,
    prepare_json_object,
    require_private_file,
    write_json_create,
    write_json_create_private,
    write_json_replace_private,
)
from agent_lifecycle.contracts.errors import LifecycleError
from agent_lifecycle.contracts.paths import normalize_repo_path


def prepared_artifact_identity(path: str, value: dict[str, Any]) -> dict[str, Any]:
    """Derive a bounded canonical artifact identity without touching storage."""
    path = normalize_repo_path(path)
    data = prepare_json_object(value, label="prospective workflow artifact")
    return {"path": path, "sha256": canonical_digest(value), "bytes": len(data)}


def persist_json_artifact(root: Path, identity: dict[str, Any], value: dict[str, Any]) -> None:
    """Create the exact preflighted artifact using the existing authority writer."""
    if prepared_artifact_identity(identity["path"], value) != identity:
        raise LifecycleError("workflow-artifact-preparation-mismatch", "prepared artifact changed before persistence")
    write_json_create(root / identity["path"], value)


def create_private_json(path: Path, value: Any) -> bytes:
    """Create one owner-only JSON artifact without replacing an existing file."""

    return write_json_create_private(path, value)


def replace_private_json(path: Path, value: Any) -> bytes:
    """Atomically replace one owner-only JSON artifact and sync its directory."""

    return write_json_replace_private(path, value)


def require_private_json(path: Path) -> Path:
    """Require a regular owner-only JSON path before reading or replacing it."""

    return require_private_file(path)


__all__ = ["create_private_json", "replace_private_json", "require_private_json"]
