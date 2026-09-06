"""Canonical JSON, digest and write-once artifact helpers."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.authority_io import (
    create_authority_bytes,
    ensure_authority_directory,
    open_authority_read,
    replace_authority_bytes,
)
from agent_lifecycle.contracts.errors import LifecycleError

MAX_JSON_INPUT_BYTES = 1_048_576
MAX_JSON_NESTING = 128
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700


class DuplicateJsonMemberError(LifecycleError):
    """Distinguish ambiguous JSON internally without changing its public error."""

    def __init__(self) -> None:
        super().__init__("invalid-json", "JSON input is invalid")


def canonical_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes for lifecycle contracts."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (MemoryError, RecursionError, UnicodeError, ValueError) as exc:
        raise LifecycleError("json-output-invalid", "JSON output cannot be canonicalized") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256_hex(canonical_bytes(value))


def load_json_object(data: bytes, *, label: str = "JSON document") -> dict[str, Any]:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise LifecycleError("invalid-json-input", "JSON input must be bytes")
    raw = bytes(data)
    if len(raw) > MAX_JSON_INPUT_BYTES:
        raise LifecycleError(
            "json-input-too-large",
            "JSON input exceeds the configured byte limit",
            {"byteCount": len(raw), "maxBytes": MAX_JSON_INPUT_BYTES},
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except RecursionError as exc:
        raise LifecycleError(
            "json-input-depth-exceeded",
            "JSON input is nested beyond the configured limit",
            {"maxDepth": MAX_JSON_NESTING},
        ) from exc
    except MemoryError as exc:
        raise LifecycleError("json-input-memory-limit", "JSON input could not be safely allocated") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise LifecycleError("invalid-json", "JSON input is invalid") from None
    _validate_json_nesting(value)
    if not isinstance(value, dict):
        raise LifecycleError("invalid-json-object", f"{label}: expected object")
    return value


def read_json_object(path: Path, *, label: str | None = None) -> dict[str, Any]:
    try:
        with open_authority_read(path) as handle:
            data = handle.read(MAX_JSON_INPUT_BYTES + 1)
    except OSError:
        raise LifecycleError("json-input-unavailable", "JSON input is unavailable") from None
    return load_json_object(data, label=label or "JSON document")


def write_json_create(path: Path, value: Any) -> bytes:
    data = canonical_bytes(value) + b"\n"
    return create_authority_bytes(path, data, private=_is_private_local_path(path))


def ensure_private_directory(path: Path) -> Path:
    """Create or validate a private local directory without overclaiming Windows ACLs."""

    return ensure_authority_directory(path, private=True)


def require_private_file(path: Path) -> Path:
    """Require a regular private file; exact mode is authoritative only on POSIX."""

    try:
        with open_authority_read(path) as handle:
            if os.name != "nt" and stat.S_IMODE(os.fstat(handle.fileno()).st_mode) != PRIVATE_FILE_MODE:
                raise LifecycleError("private-file-mode-invalid", "private storage file does not use owner-only mode")
    except FileNotFoundError:
        raise LifecycleError("private-file-invalid", "private storage file is invalid") from None
    return path


def write_json_create_private(path: Path, value: Any) -> bytes:
    """Write one canonical JSON artifact with owner-only POSIX permissions."""

    data = canonical_bytes(value) + b"\n"
    return create_authority_bytes(path, data, private=True)


def write_json_replace_private(path: Path, value: Any) -> bytes:
    """Atomically replace a canonical JSON artifact with owner-only permissions."""

    data = canonical_bytes(value) + b"\n"
    return replace_authority_bytes(path, data)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonMemberError() from None
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _is_private_local_path(path: Path) -> bool:
    return ".alk" in path.parts


def _validate_json_nesting(value: Any) -> None:
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if not isinstance(current, (dict, list)):
            continue
        if depth > MAX_JSON_NESTING:
            raise LifecycleError(
                "json-input-depth-exceeded",
                "JSON input is nested beyond the configured limit",
                {"maxDepth": MAX_JSON_NESTING},
            )
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        else:
            pending.extend((child, depth + 1) for child in current)
