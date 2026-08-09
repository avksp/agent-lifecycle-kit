"""Portable path and stable-read checks."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import NeutralityError


class StableReadRaceError(NeutralityError):
    """The file identity changed while its bytes were being read."""


@dataclass(frozen=True)
class StableReadResult:
    data: bytes
    recovered_race: bool


def ensure_external_regular_file(
    path: Path,
    *,
    workspace_root: Path,
    artifact_root: Path,
    release_root: Path | None = None,
) -> Path:
    if not path.is_absolute():
        raise NeutralityError("external authority paths must be absolute")
    resolved = path.resolve(strict=True)
    roots = [workspace_root.resolve(), artifact_root.resolve()]
    git_root = workspace_root / ".git"
    if git_root.exists():
        roots.append(git_root.resolve())
    if release_root is not None:
        roots.append(release_root.resolve())
    for root in roots:
        if resolved == root or resolved.is_relative_to(root):
            raise NeutralityError("external authority path is inside a forbidden root")
    first = os.lstat(resolved)
    if stat.S_ISLNK(first.st_mode):
        raise NeutralityError("external authority path must not be a symlink")
    if not stat.S_ISREG(first.st_mode):
        raise NeutralityError("external authority path must be a regular file")
    if first.st_nlink > 1:
        raise NeutralityError("external authority path must not have multiple hard links")
    return resolved


def stable_read_bytes(path: Path, *, max_bytes: int | None = None) -> bytes:
    return _stable_read_once(path, max_bytes=max_bytes)


def stable_read_bytes_with_retry(path: Path, *, max_bytes: int | None = None) -> StableReadResult:
    """Read once, retrying exactly once only when the file identity changes."""

    try:
        return StableReadResult(_stable_read_once(path, max_bytes=max_bytes), False)
    except StableReadRaceError:
        return StableReadResult(_stable_read_once(path, max_bytes=max_bytes), True)


def _stable_read_once(path: Path, *, max_bytes: int | None = None) -> bytes:
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise NeutralityError(f"not a regular file: {path}")
    if max_bytes is not None and before.st_size > max_bytes:
        raise NeutralityError(f"file exceeds max bytes: {path}")
    with path.open("rb") as handle:
        data = handle.read()
    after = os.stat(path, follow_symlinks=False)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after:
        raise StableReadRaceError(f"stable read identity changed: {path}")
    if max_bytes is not None and len(data) > max_bytes:
        raise NeutralityError(f"read exceeds max bytes: {path}")
    return data


def validate_repository_relative_path(path: str) -> None:
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        raise NeutralityError(f"invalid repository-relative path: {path}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise NeutralityError(f"invalid repository-relative path: {path}")
    if any(part.endswith(".") or part.endswith(" ") for part in parts):
        raise NeutralityError(f"invalid repository-relative path: {path}")
    if len(path.encode("utf-8")) > 4096:
        raise NeutralityError(f"repository-relative path is too long: {path}")


def validate_output_paths(output_paths: list[Path]) -> list[str]:
    seen: dict[str, str] = {}
    normalized: list[str] = []
    for path in output_paths:
        path_text = path.as_posix()
        validate_repository_relative_path(path_text)
        key = path_text.casefold()
        if key in seen:
            raise NeutralityError(f"output path alias conflict: {seen[key]} vs {path_text}")
        seen[key] = path_text
        normalized.append(path_text)
    return normalized


def resolve_repository_relative_root(workspace_root: Path, value: str, *, label: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise NeutralityError(f"{label} must be repository-relative")
    normalized_workspace = workspace_root.resolve()
    resolved = (normalized_workspace / path).resolve()
    if not resolved.is_relative_to(normalized_workspace):
        raise NeutralityError(f"{label} escapes workspace")
    return resolved
