"""Finite nonblocking anonymous byte-pipe operations for existing callers."""

from __future__ import annotations

import errno
import math
import os
import selectors
import time
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Any, cast


def _ctypes() -> Any:
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows pipe operations unavailable")
    import ctypes

    return ctypes


@lru_cache(maxsize=1)
def _kernel() -> Any:
    if os.name != "nt":
        raise OSError(errno.ENOTSUP, "Windows pipe operations unavailable")
    c = _ctypes()
    from ctypes import wintypes as w

    api = c.WinDLL("kernel32", use_last_error=True)
    api.SetNamedPipeHandleState.argtypes = [w.HANDLE, c.POINTER(w.DWORD), w.LPVOID, w.LPVOID]
    api.SetNamedPipeHandleState.restype = w.BOOL
    api.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, c.POINTER(w.DWORD), w.LPVOID]
    api.ReadFile.restype = w.BOOL
    api.WriteFile.argtypes = api.ReadFile.argtypes
    api.WriteFile.restype = w.BOOL
    api.PeekNamedPipe.argtypes = [w.HANDLE, w.LPVOID, w.DWORD, w.LPVOID, c.POINTER(w.DWORD), w.LPVOID]
    api.PeekNamedPipe.restype = w.BOOL
    return api


def _handle(fd: int) -> int:
    _kernel()
    import msvcrt

    return int(cast(Any, msvcrt).get_osfhandle(fd))


def configure_pipe(fd: int) -> None:
    """Set this actual pipe handle to byte-read, nonblocking wait mode."""
    c = _ctypes()
    from ctypes import wintypes as w

    mode = w.DWORD(1)  # PIPE_READMODE_BYTE | PIPE_NOWAIT
    if not _kernel().SetNamedPipeHandleState(_handle(fd), c.byref(mode), None, None):
        raise c.WinError(c.get_last_error())


def read_pipe(fd: int, maximum: int) -> bytes:
    """Read at most one bounded chunk; an empty live pipe is not EOF."""
    c = _ctypes()
    from ctypes import wintypes as w

    if type(maximum) is not int or not 0 < maximum <= 65536:
        raise ValueError("Pipe read bound must be between 1 and 65536")
    buffer = c.create_string_buffer(maximum)
    count = w.DWORD()
    if not _kernel().ReadFile(_handle(fd), buffer, maximum, c.byref(count), None):
        error = c.get_last_error()
        if error == 232:  # ERROR_NO_DATA on a live PIPE_NOWAIT reader
            raise BlockingIOError(errno.EAGAIN, "Pipe has no data")
        if error == 109:  # ERROR_BROKEN_PIPE after the writer closes
            return b""
        raise c.WinError(error)
    if count.value > maximum:
        raise OSError(errno.EIO, "Invalid pipe read count")
    return buffer.raw[: count.value]


def write_pipe(fd: int, data: bytes | memoryview) -> int:
    """Report only accepted bytes; successful zero-byte writes would block."""
    c = _ctypes()
    from ctypes import wintypes as w

    chunk = bytes(data[:65536])
    if not chunk:
        return 0
    buffer = c.create_string_buffer(chunk)
    count = w.DWORD()
    if not _kernel().WriteFile(_handle(fd), buffer, len(chunk), c.byref(count), None):
        error = c.get_last_error()
        if error in {109, 232, 233}:
            raise BrokenPipeError(errno.EPIPE, "Pipe reader closed")
        raise c.WinError(error)
    if count.value == 0:
        raise BlockingIOError(errno.EAGAIN, "Pipe has no write capacity")
    if count.value > len(chunk):
        raise OSError(errno.EIO, "Invalid pipe write count")
    return count.value


def _read_ready(fd: int) -> bool:
    c = _ctypes()
    from ctypes import wintypes as w

    available = w.DWORD()
    if _kernel().PeekNamedPipe(_handle(fd), None, 0, None, c.byref(available), None):
        return available.value > 0
    error = c.get_last_error()
    if error == 109:
        return True  # Allow read_pipe to report EOF.
    if error == 232:
        return False
    raise c.WinError(error)


class PipeSelector(selectors.BaseSelector):
    """Finite polling for owned pipes, without a blocking reader thread.

    WRITE events permit a nonblocking attempt after a short backoff. They do
    not promise capacity: write_pipe may still raise BlockingIOError. The
    existing caller retains its original deadline and cancellation policy.
    """

    def __init__(self) -> None:
        self._keys: dict[int, selectors.SelectorKey] = {}
        self._closed = False

    @staticmethod
    def _fd(fileobj: Any) -> int:
        fd = fileobj if isinstance(fileobj, int) else fileobj.fileno()
        if not isinstance(fd, int) or fd < 0:
            raise ValueError("Invalid pipe descriptor")
        return fd

    def register(self, fileobj: Any, events: int, data: Any = None) -> selectors.SelectorKey:
        if self._closed:
            raise RuntimeError("Selector is closed")
        if not events or events & ~(selectors.EVENT_READ | selectors.EVENT_WRITE):
            raise ValueError("Invalid pipe events")
        fd = self._fd(fileobj)
        if fd in self._keys:
            raise KeyError("Pipe is already registered")
        key = selectors.SelectorKey(fileobj, fd, events, data)
        self._keys[fd] = key
        return key

    def unregister(self, fileobj: Any) -> selectors.SelectorKey:
        return self._keys.pop(self._fd(fileobj))

    def get_key(self, fileobj: Any) -> selectors.SelectorKey:
        if self._closed:
            raise RuntimeError("Selector is closed")
        return self._keys[self._fd(fileobj)]

    def get_map(self) -> Mapping[Any, selectors.SelectorKey]:
        if self._closed:
            raise RuntimeError("Selector is closed")
        return MappingProxyType(self._keys)

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        if self._closed:
            raise RuntimeError("Selector is closed")
        if timeout is None or not math.isfinite(timeout):
            raise ValueError("A finite pipe timeout is required")
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            ready = []
            for key in self._keys.values():
                events = key.events & selectors.EVENT_WRITE
                if key.events & selectors.EVENT_READ and _read_ready(key.fd):
                    events |= selectors.EVENT_READ
                if events:
                    ready.append((key, events))
            remaining = max(0.0, deadline - time.monotonic())
            if ready:
                if all(events == selectors.EVENT_WRITE for _, events in ready):
                    time.sleep(min(0.001, remaining))
                return ready
            if remaining == 0:
                return []
            time.sleep(min(0.002, remaining))

    def close(self) -> None:
        self._keys.clear()
        self._closed = True
