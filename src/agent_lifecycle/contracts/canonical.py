"""Canonical JSON, digest and write-once artifact helpers."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from pathlib import Path
from typing import Any

from agent_lifecycle.contracts.errors import LifecycleError

MAX_JSON_INPUT_BYTES = 1_048_576
MAX_JSON_NESTING = 128
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700


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
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
    except RecursionError as exc:
        raise LifecycleError(
            "json-input-depth-exceeded",
            "JSON input is nested beyond the configured limit",
            {"maxDepth": MAX_JSON_NESTING},
        ) from exc
    except MemoryError as exc:
        raise LifecycleError("json-input-memory-limit", "JSON input could not be safely allocated") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise LifecycleError("invalid-json", "JSON input is invalid") from exc
    _validate_json_nesting(value)
    if not isinstance(value, dict):
        raise LifecycleError("invalid-json-object", f"{label}: expected object")
    return value


def read_json_object(path: Path, *, label: str | None = None) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_JSON_INPUT_BYTES + 1)
    except OSError as exc:
        raise LifecycleError("json-input-unavailable", "JSON input is unavailable") from exc
    return load_json_object(data, label=label or "JSON document")


def write_json_create(path: Path, value: Any) -> bytes:
    data = canonical_bytes(value) + b"\n"
    if _is_private_local_path(path):
        return write_json_create_private(path, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(path, flags, 0o644), "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return data


def ensure_private_directory(path: Path) -> Path:
    """Create or validate a private local directory without overclaiming Windows ACLs."""

    try:
        for directory in _private_directory_chain(path):
            if directory.is_symlink():
                raise LifecycleError("private-directory-symlink", "private directory must not be a symlink")
            directory.mkdir(mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
            if directory.is_symlink():
                raise LifecycleError("private-directory-symlink", "private directory must not be a symlink")
            if not directory.is_dir():
                raise LifecycleError("private-directory-invalid", "private storage path is not a directory")
            if os.name != "nt":
                directory.chmod(PRIVATE_DIRECTORY_MODE)
    except LifecycleError:
        raise
    except OSError as exc:
        raise LifecycleError("private-directory-unavailable", "private storage directory is unavailable") from exc
    return path


def require_private_file(path: Path) -> Path:
    """Require a regular private file; exact mode is authoritative only on POSIX."""

    if path.is_symlink() or not path.is_file():
        raise LifecycleError("private-file-invalid", "private storage file is invalid")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) != PRIVATE_FILE_MODE:
        raise LifecycleError("private-file-mode-invalid", "private storage file does not use owner-only mode")
    return path


def write_json_create_private(path: Path, value: Any) -> bytes:
    """Write one canonical JSON artifact with owner-only POSIX permissions."""

    ensure_private_directory(path.parent)
    data = canonical_bytes(value) + b"\n"
    if path.is_symlink():
        raise LifecycleError("private-file-invalid", "private storage file must not be a symlink")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        with os.fdopen(os.open(path, flags, PRIVATE_FILE_MODE), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            path.chmod(PRIVATE_FILE_MODE)
    except FileExistsError:
        raise
    except OSError as exc:
        raise LifecycleError("private-file-write-failed", "private storage file could not be written") from exc
    return data


def write_json_replace_private(path: Path, value: Any) -> bytes:
    """Atomically replace a canonical JSON artifact with owner-only permissions."""

    ensure_private_directory(path.parent)
    if path.is_symlink():
        raise LifecycleError("private-file-invalid", "private storage file must not be a symlink")
    data = canonical_bytes(value) + b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        with os.fdopen(os.open(temporary, flags, PRIVATE_FILE_MODE), "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            path.chmod(PRIVATE_FILE_MODE)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        raise LifecycleError("private-file-write-failed", "private storage file could not be replaced") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return data


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _is_private_local_path(path: Path) -> bool:
    return ".alk" in path.parts


def _private_directory_chain(path: Path) -> list[Path]:
    """Return private directories from the controlled root through ``path``."""

    if ".alk" in path.parts:
        chain = [path]
        current = path
        while current.name != ".alk":
            parent = current.parent
            if parent == current:
                return [path]
            current = parent
            chain.append(current)
        return list(reversed(chain))

    missing: list[Path] = []
    current = path
    while not current.exists() and current.parent != current:
        missing.append(current)
        current = current.parent
    return list(reversed(missing)) or [path]


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
