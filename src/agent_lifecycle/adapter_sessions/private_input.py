"""Private input storage with bounded reads and exact filesystem checks."""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError

_MAX_REQUEST_BYTES = 131_072


def _private_dir(path: Path, *, boundary: Path) -> None:
    if path == boundary:
        return
    _private_dir(path.parent, boundary=boundary)
    with contextlib.suppress(FileExistsError):
        path.mkdir(mode=0o700)
    info = path.lstat()
    relative = path.relative_to(boundary).parts
    shared_parent = relative in {("work",), ("work", "release-2-16"), ("work", "release-2-16", "evidence")}
    if not stat.S_ISDIR(info.st_mode) or (not shared_parent and stat.S_IMODE(info.st_mode) != 0o700):
        raise LifecycleError("codex-exact-private-path-unsafe", "private directory is not mode 0700")


def _verify_private_ancestors(path: Path, *, root: Path) -> None:
    """Refuse an existing snapshot reached through a symlink or open parent."""
    _require(
        path.is_relative_to(root) and path != root, "codex-exact-private-path-unsafe", "private path lies outside root"
    )
    current = path.parent
    while current != root:
        info = current.lstat()
        relative = current.relative_to(root).parts
        shared = relative in {("work",), ("work", "release-2-16"), ("work", "release-2-16", "evidence")}
        _require(
            stat.S_ISDIR(info.st_mode) and (shared or stat.S_IMODE(info.st_mode) == 0o700),
            "codex-exact-private-path-unsafe",
            "snapshot ancestor is unsafe",
        )
        current = current.parent


def _write_exclusive(path: Path, raw: bytes, *, root: Path) -> None:
    if len(raw) > _MAX_REQUEST_BYTES:
        raise LifecycleError("codex-exact-private-overflow", "private artifact exceeds byte limit")
    _private_dir(path.parent, boundary=root)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise LifecycleError("codex-exact-private-create-failed", "private artifact cannot be created") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _read_private(
    path: Path,
    *,
    root: Path,
    allowed_modes: tuple[int, ...] = (0o600,),
    max_bytes: int = _MAX_REQUEST_BYTES,
) -> bytes:
    if not path.is_relative_to(root):
        raise LifecycleError("codex-exact-private-path-unsafe", "private artifact lies outside root")
    current = path.parent
    while current != root:
        info = current.lstat()
        relative = current.relative_to(root).parts
        shared_parent = relative in {("work",), ("work", "release-2-16"), ("work", "release-2-16", "evidence")}
        if not stat.S_ISDIR(info.st_mode) or (not shared_parent and stat.S_IMODE(info.st_mode) != 0o700):
            raise LifecycleError("codex-exact-private-path-unsafe", "private parent is not mode 0700")
        current = current.parent
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in allowed_modes or info.st_size > max_bytes:
        raise LifecycleError("codex-exact-private-path-unsafe", "private file has unsafe mode, type or size")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())

        def identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
            return (item.st_dev, item.st_ino, item.st_mode, item.st_size, item.st_mtime_ns)

        if identity(opened) != identity(info):
            raise LifecycleError("codex-exact-private-path-unsafe", "private file changed before reading")
        raw = stream.read(max_bytes + 1)
        if identity(os.fstat(stream.fileno())) != identity(opened):
            raise LifecycleError("codex-exact-private-path-unsafe", "private file changed while reading")
    if len(raw) > max_bytes:
        raise LifecycleError("codex-exact-private-overflow", "private artifact exceeds byte limit")
    return raw


def _require(value: bool, code: str, message: str) -> None:
    if not value:
        raise LifecycleError(code, message)
