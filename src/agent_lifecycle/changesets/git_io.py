"""Bounded, interruptible byte transport for local Git and inspection commands.

This module owns pipe reads and its direct subprocess. Adapter lifecycle,
qualification and process-group attestation remain at their existing owners.
"""

from __future__ import annotations

import math
import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import IO

from agent_lifecycle.contracts import LifecycleError

_CHUNK_BYTES = 65536
_POLL_SECONDS = 0.02
_CLEANUP_SECONDS = 0.5


def _windows_cleanup(process: subprocess.Popen[bytes]) -> Callable[[], None] | None:
    """Retain a Job handle so a recursive local command can be reaped as a tree."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    win_dll = getattr(ctypes, "WinDLL", None)
    if not callable(win_dll):
        raise LifecycleError("bounded-process-group-unavailable", "Windows group API is unavailable")
    kernel = win_dll("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        native_error = getattr(ctypes, "get_last_error")()
        raise LifecycleError(
            "bounded-process-group-unavailable",
            "Cannot own the Windows child group",
            {"nativeStage": "CreateJobObjectW", "winError": native_error},
        )
    if not kernel.AssignProcessToJobObject(handle, getattr(process, "_handle", None)):
        native_error = getattr(ctypes, "get_last_error")()
        kernel.CloseHandle(handle)
        raise LifecycleError(
            "bounded-process-group-unavailable",
            "Cannot own the Windows child group",
            {"nativeStage": "AssignProcessToJobObject", "winError": native_error},
        )

    def cleanup() -> None:
        terminated = kernel.TerminateJobObject(handle, 1)
        closed = kernel.CloseHandle(handle)
        if not terminated or not closed:
            raise LifecycleError("bounded-process-cleanup-failed", "Windows child group cleanup failed")

    return cleanup


class _PipeReader:
    def __init__(self, owner: BoundedProcess, stream: IO[bytes], limit: int) -> None:
        self.owner = owner
        self.stream = stream
        self.limit = limit
        self.chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
        self.buffer = bytearray()
        self.eof = False
        self.thread = threading.Thread(target=self._pump, name="alk-bounded-pipe", daemon=True)

    def _pump(self) -> None:
        total = 0
        try:
            while not self.owner.stopping.is_set():
                data = os.read(self.stream.fileno(), min(_CHUNK_BYTES, self.limit - total + 1))
                total += len(data)
                if total > self.limit:
                    self.owner.fail("bounded-process-output-limit")
                    return
                while not self.owner.stopping.is_set():
                    try:
                        self.chunks.put(data or None, timeout=_POLL_SECONDS)
                        break
                    except queue.Full:
                        continue
                if not data:
                    return
        except OSError:
            if not self.owner.stopping.is_set():
                self.owner.fail("bounded-process-read-failed")

    def _fill(self) -> None:
        while not self.eof:
            self.owner.check()
            try:
                chunk = self.chunks.get(timeout=self.owner.remaining())
            except queue.Empty:
                continue
            if chunk is None:
                self.eof = True
            else:
                self.buffer.extend(chunk)
            return

    def readline(self, max_bytes: int) -> bytes:
        while True:
            self.owner.check()
            end = self.buffer.find(b"\n")
            size = end + 1 if end >= 0 else len(self.buffer)
            if size > max_bytes:
                raise LifecycleError("bounded-process-line-limit", "Process line exceeds its byte limit")
            if end >= 0 or self.eof:
                value = bytes(self.buffer[:size])
                del self.buffer[:size]
                return value
            self._fill()

    def read(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            self.owner.check()
            if not self.buffer and not self.eof:
                self._fill()
            if not self.buffer:
                break
            value = bytes(self.buffer[:remaining])
            del self.buffer[: len(value)]
            chunks.append(value)
            remaining -= len(value)
        return b"".join(chunks)

    def read_all(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = self.read(_CHUNK_BYTES)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)


class BoundedProcess:
    """Keep one absolute deadline across a streaming request/response session."""

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        deadline: float,
        max_stdout_bytes: int,
        max_stderr_bytes: int = 65536,
        writable: bool = False,
    ) -> None:
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= time.monotonic():
            raise LifecycleError("bounded-process-timeout", "Process deadline is invalid or expired")
        if not argv or any(not isinstance(value, str) or "\0" in value for value in argv):
            raise LifecycleError("bounded-process-argv-invalid", "A shell-free argument vector is required")
        if any(type(value) is not int or value < 1 for value in (max_stdout_bytes, max_stderr_bytes)):
            raise LifecycleError("bounded-process-limit-invalid", "Positive byte limits are required")
        self.deadline = deadline
        self.closed = False
        self.stopping = threading.Event()
        self.failure: str | None = None
        self.stderr = bytearray()
        self.max_stderr_bytes = max_stderr_bytes
        self.writes: queue.Queue[tuple[bytes | None, threading.Event]] = queue.Queue(maxsize=1)
        env = dict(os.environ)
        if Path(argv[0]).stem.lower() == "git":
            env.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
        self.process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE if writable else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            bufsize=0,
            start_new_session=os.name == "posix",
        )
        self.threads: list[threading.Thread] = []
        self.windows_cleanup: Callable[[], None] | None = None
        try:
            self.windows_cleanup = _windows_cleanup(self.process)
            assert self.process.stdout is not None
            self.stdout = _PipeReader(self, self.process.stdout, max_stdout_bytes)
            self.threads.append(self.stdout.thread)
            self.stdout.thread.start()
            reader = threading.Thread(target=self._drain_stderr, name="alk-bounded-stderr", daemon=True)
            self.threads.append(reader)
            reader.start()
            if writable:
                writer = threading.Thread(target=self._write_requests, name="alk-bounded-input", daemon=True)
                self.threads.append(writer)
                writer.start()
        except BaseException:
            self.close()
            raise

    def fail(self, code: str) -> None:
        if self.failure is None:
            self.failure = code

    def check(self) -> None:
        if self.failure:
            raise LifecycleError(self.failure, "Bounded process transport failed")
        if time.monotonic() >= self.deadline:
            raise LifecycleError("bounded-process-timeout", "Process exceeded its deadline")

    def remaining(self) -> float:
        self.check()
        return min(_POLL_SECONDS, max(0.0001, self.deadline - time.monotonic()))

    def _drain_stderr(self) -> None:
        assert self.process.stderr is not None
        try:
            while not self.stopping.is_set():
                data = os.read(
                    self.process.stderr.fileno(), min(_CHUNK_BYTES, self.max_stderr_bytes - len(self.stderr) + 1)
                )
                if not data:
                    return
                if len(self.stderr) + len(data) > self.max_stderr_bytes:
                    self.fail("bounded-process-stderr-limit")
                    return
                self.stderr.extend(data)
        except OSError:
            if not self.stopping.is_set():
                self.fail("bounded-process-read-failed")

    def _write_requests(self) -> None:
        assert self.process.stdin is not None
        while not self.stopping.is_set():
            try:
                data, done = self.writes.get(timeout=_POLL_SECONDS)
            except queue.Empty:
                continue
            try:
                if data is None:
                    self.process.stdin.close()
                    return
                view = memoryview(data)
                while view:
                    written = self.process.stdin.write(view.tobytes())
                    if not written:
                        raise BrokenPipeError
                    view = view[written:]
                self.process.stdin.flush()
            except (OSError, ValueError):
                self.fail("bounded-process-write-failed")
                return
            finally:
                done.set()

    def write_request(self, data: bytes | None) -> None:
        """Deliver one small batch request, or close its input, under the same clock."""
        if self.process.stdin is None or (data is not None and len(data) > 1024):
            raise LifecycleError("bounded-process-request-invalid", "A bounded batch request is required")
        done = threading.Event()
        while True:
            self.check()
            try:
                self.writes.put((data, done), timeout=self.remaining())
                break
            except queue.Full:
                continue
        while not done.wait(self.remaining()):
            self.check()
        self.check()

    def wait(self) -> int:
        while self.process.poll() is None:
            time.sleep(self.remaining())
        for thread in self.threads[1:2]:
            while thread.is_alive():
                thread.join(self.remaining())
        self.check()
        returncode = self.process.returncode
        assert returncode is not None
        return returncode

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stopping.set()
        cleanup_error: LifecycleError | None = None
        if os.name == "posix":
            with suppress(ProcessLookupError):
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except PermissionError:
                    # A reaped child must not prevent closing our descriptors.
                    # Reader shutdown below still refuses a pipe held by a survivor.
                    if self.process.poll() is None:
                        self.process.kill()
                        cleanup_error = LifecycleError(
                            "bounded-process-cleanup-failed",
                            "Child group signal was denied",
                        )
        else:
            if self.windows_cleanup is not None:
                try:
                    self.windows_cleanup()
                except LifecycleError as exc:
                    cleanup_error = exc
            if self.process.poll() is None:
                self.process.kill()
        try:
            self.process.wait(timeout=_CLEANUP_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise LifecycleError("bounded-process-cleanup-failed", "Process did not exit during cleanup") from exc
        deadline = time.monotonic() + _CLEANUP_SECONDS
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            raise LifecycleError("bounded-process-cleanup-failed", "Process pipes did not finish during cleanup")
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None:
                stream.close()
        if cleanup_error is not None:
            raise cleanup_error

    def __enter__(self) -> BoundedProcess:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def run_bounded_command(
    argv: list[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int = 65536,
) -> subprocess.CompletedProcess[bytes]:
    """Capture a bounded command without allowing communicate() to grow unbounded."""
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise LifecycleError("bounded-process-timeout-invalid", "A finite positive timeout is required")
    with BoundedProcess(
        argv,
        cwd=cwd,
        deadline=time.monotonic() + timeout_seconds,
        max_stdout_bytes=max_stdout_bytes,
        max_stderr_bytes=max_stderr_bytes,
    ) as transport:
        stdout = transport.stdout.read_all()
        returncode = transport.wait()
        return subprocess.CompletedProcess(argv, returncode, stdout, bytes(transport.stderr))


__all__ = ["BoundedProcess", "run_bounded_command"]
