"""Shared private persistence primitives for local lifecycle state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.canonical import (
    ensure_private_directory,
    require_private_file,
    write_json_create_private,
    write_json_replace_private,
)


def create_private_json(path: Path, value: Any) -> bytes:
    """Create one owner-only JSON artifact without replacing an existing file."""

    ensure_private_directory(path.parent)
    return write_json_create_private(path, value)


def replace_private_json(path: Path, value: Any) -> bytes:
    """Atomically replace one owner-only JSON artifact and sync its directory."""

    ensure_private_directory(path.parent)
    return write_json_replace_private(path, value)


def require_private_json(path: Path) -> Path:
    """Require a regular owner-only JSON path before reading or replacing it."""

    return require_private_file(path)


__all__ = ["create_private_json", "replace_private_json", "require_private_json"]
