"""Compatibility reads with explicit caller-owned permissions and error codes."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .errors import LifecycleError


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns


def read_compat_private_bytes(
    path: Path,
    *,
    root: Path,
    allowed_modes: tuple[int, ...] = (0o600,),
    max_bytes: int = 131_072,
    shared_parents: frozenset[tuple[str, ...]] = frozenset(),
    unsafe_code: str = "private-storage-unsafe",
    overflow_code: str = "private-storage-overflow",
) -> bytes:
    """Preserve legacy reads without changing the modern storage policy."""
    if os.name == "nt":
        from .private_storage import read_private_bytes

        try:
            return read_private_bytes(path, root=root, modes=allowed_modes, max_bytes=max_bytes)
        except LifecycleError as exc:
            raise LifecycleError(unsafe_code, exc.message) from exc
    if not path.is_relative_to(root):
        raise LifecycleError(unsafe_code, "private artifact lies outside root")
    current = path.parent
    while current != root:
        info = current.lstat()
        shared = current.relative_to(root).parts in shared_parents
        if not stat.S_ISDIR(info.st_mode) or (not shared and stat.S_IMODE(info.st_mode) != 0o700):
            raise LifecycleError(unsafe_code, "private parent is not mode 0700")
        current = current.parent
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) not in allowed_modes or info.st_size > max_bytes:
        raise LifecycleError(unsafe_code, "private file has unsafe mode, type or size")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(opened) != _identity(info):
            raise LifecycleError(unsafe_code, "private file changed before reading")
        raw = stream.read(max_bytes + 1)
        if _identity(os.fstat(stream.fileno())) != _identity(opened):
            raise LifecycleError(unsafe_code, "private file changed while reading")
    if len(raw) > max_bytes:
        raise LifecycleError(overflow_code, "private artifact exceeds byte limit")
    return raw
