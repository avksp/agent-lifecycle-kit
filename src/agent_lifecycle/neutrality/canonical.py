"""Compatibility imports for neutrality canonical helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.canonical import (
    canonical_bytes,
    load_json_object,
    sha256_hex,
    write_json_create,
)
from agent_lifecycle.contracts.errors import LifecycleError


def load_json(data: bytes) -> dict[str, Any]:
    try:
        return load_json_object(data)
    except LifecycleError as exc:
        from .errors import NeutralityError

        raise NeutralityError(exc.message) from exc


def read_file_hash(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": path.as_posix(), "sha256": sha256_hex(data), "bytes": len(data)}
