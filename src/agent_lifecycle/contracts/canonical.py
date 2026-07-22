"""Canonical JSON, digest and write-once artifact helpers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError


def canonical_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for lifecycle contracts."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def load_json_object(data: bytes, *, label: str = "JSON document") -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LifecycleError("invalid-json", f"{label}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LifecycleError("invalid-json-object", f"{label}: expected object")
    return value


def read_json_object(path: Path, *, label: str | None = None) -> dict[str, Any]:
    return load_json_object(path.read_bytes(), label=label or path.as_posix())


def write_json_create(path: Path, value: Any) -> bytes:
    data = canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o644), "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return data
