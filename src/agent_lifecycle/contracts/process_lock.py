"""Bounded OS locks for cooperating processes on one local file."""

from __future__ import annotations

import errno
import math
import os
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, cast

from agent_lifecycle.contracts.authority_io import authority_location, ensure_authority_directory
from agent_lifecycle.contracts.errors import LifecycleError

_FD_GUARD = threading.Lock()
_LOCK_FDS: set[int] = set()
DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0


class _WindowsLock(Protocol):
    LK_NBLCK: int

    def locking(self, fd: int, mode: int, nbytes: int) -> None: ...


def _after_fork_child() -> None:
    for fd in _LOCK_FDS:
        os.close(fd)
    _LOCK_FDS.clear()
    _FD_GUARD.release()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_FD_GUARD.acquire,
        after_in_parent=_FD_GUARD.release,
        after_in_child=_after_fork_child,
    )


def _identity(path: Path, fd: int) -> tuple[int, int]:
    actual = os.fstat(fd)
    named = path.lstat()
    if (
        not stat.S_ISREG(named.st_mode)
        or not stat.S_ISREG(actual.st_mode)
        or actual.st_nlink != 1
        or (actual.st_dev, actual.st_ino) != (named.st_dev, named.st_ino)
        or (os.name != "nt" and stat.S_IMODE(actual.st_mode) != 0o600)
    ):
        raise LifecycleError("process-lock-unsafe", "process lock must remain a private regular file")
    return actual.st_dev, actual.st_ino


def _try_lock(fd: int) -> bool:
    try:
        if os.name == "posix":
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif os.name == "nt":
            import msvcrt

            windows = cast("_WindowsLock", msvcrt)
            os.lseek(fd, 0, os.SEEK_SET)
            windows.locking(fd, windows.LK_NBLCK, 1)
        else:
            raise LifecycleError("process-lock-unsupported", "local process locking is unsupported")
        return True
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise


@contextmanager
def exclusive_process_lock(
    path: Path,
    *,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Hold a stable lock through the caller's operation; never remove its file.

    Closing the OS handle releases a crashed process's lock. File age, PID text
    and elapsed time never authorize stealing a live lock.
    """
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise LifecycleError("process-lock-timeout-invalid", "lock timeout must be nonnegative")
    root, relative = authority_location(path)
    path = root / relative
    ensure_authority_directory(path.parent)
    owner_pid = os.getpid()
    fd = -1
    try:
        with _FD_GUARD:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            _LOCK_FDS.add(fd)
        identity = _identity(path, fd)
        deadline = time.monotonic() + timeout_seconds
        while not _try_lock(fd):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LifecycleError("process-lock-timeout", "another process holds the operation lock")
            time.sleep(min(0.01, remaining))
        if _identity(path, fd) != identity:
            raise LifecycleError("process-lock-unsafe", "process lock identity changed")
    except OSError as error:
        raise LifecycleError("process-lock-unavailable", "local process lock is unavailable") from error
    else:
        yield
    finally:
        if fd >= 0 and owner_pid == os.getpid():
            with _FD_GUARD:
                _LOCK_FDS.discard(fd)
                os.close(fd)
