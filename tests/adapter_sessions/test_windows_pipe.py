"""Actual Windows pipe witnesses and explicit Python fixture process support."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import selectors
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.process import run_process
from agent_lifecycle.adapter_sessions.windows_pipe import (
    PipeSelector,
    configure_pipe,
    read_pipe,
    write_pipe,
)

_REAL_POPEN = subprocess.Popen


def install_windows_fixture_process(case: unittest.TestCase) -> None:
    """Execute only explicit current-Python shebang fixtures via Python.

    The caller's logical argv and selected fixture hash remain unchanged.
    This is test process injection, never a native Codex qualification.
    """
    if os.name != "nt":
        return

    def start(argv, *args, **kwargs):
        physical = argv
        if isinstance(argv, (list, tuple)) and argv:
            path = Path(argv[0])
            if path.is_file():
                with path.open("rb") as stream:
                    first = stream.readline(4096).rstrip(b"\r\n")
                if first == b"#!" + os.fsencode(sys.executable):
                    interpreter = getattr(sys, "_base_executable", sys.executable)
                    physical = [interpreter, "-B", str(path), *argv[1:]]
                    if os.path.normcase(interpreter) != os.path.normcase(sys.executable):
                        # Match CPython multiprocessing: direct PID, selected venv.
                        supplied = kwargs.get("env")
                        environment = dict(os.environ if supplied is None else supplied)
                        environment["__PYVENV_LAUNCHER__"] = sys.executable
                        kwargs["env"] = environment
        return _REAL_POPEN(physical, *args, **kwargs)

    injected = patch.object(subprocess, "Popen", side_effect=start)
    injected.start()
    case.addCleanup(injected.stop)


def assert_private_path(case: unittest.TestCase, path: Path, mode: int) -> None:
    if os.name == "nt":
        from agent_lifecycle.contracts.private_storage import private_mode

        case.assertTrue(private_mode(path, path.lstat(), (mode,)))
    else:
        case.assertEqual(path.stat().st_mode & 0o777, mode)


def process_is_running(pid: int) -> bool:
    """Inspect liveness without Windows os.kill(pid, 0) side effects."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes as c
    from ctypes import wintypes as w

    api = c.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    api.OpenProcess.restype = w.HANDLE
    api.GetExitCodeProcess.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
    api.GetExitCodeProcess.restype = w.BOOL
    api.CloseHandle.argtypes = [w.HANDLE]
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        error = c.get_last_error()
        if error in {87, 1168}:
            return False
        raise c.WinError(error)
    try:
        code = w.DWORD()
        if not api.GetExitCodeProcess(handle, c.byref(code)):
            raise c.WinError(c.get_last_error())
        return code.value == 259
    finally:
        api.CloseHandle(handle)


@unittest.skipUnless(os.name == "nt", "Requires actual Windows pipe APIs")
class WindowsPipeTests(unittest.TestCase):
    def test_live_empty_read_differs_from_closed_writer_eof(self):
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
            configure_pipe(reader.fileno())
            configure_pipe(writer.fileno())
            with self.assertRaises(BlockingIOError) as empty:
                read_pipe(reader.fileno(), 8)
            self.assertEqual(empty.exception.errno, errno.EAGAIN)
            self.assertEqual(write_pipe(writer.fileno(), b"a"), 1)
            self.assertEqual(write_pipe(writer.fileno(), b"\xc3\xa9\n"), 3)
            self.assertEqual(read_pipe(reader.fileno(), 8), b"a\xc3\xa9\n")
            writer.close()
            self.assertEqual(read_pipe(reader.fileno(), 8), b"")

    def test_full_byte_pipe_zero_write_is_would_block_not_completion(self):
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
            configure_pipe(reader.fileno())
            configure_pipe(writer.fileno())
            accepted = 0
            began = time.monotonic()
            while accepted < 1_048_576:
                try:
                    accepted += write_pipe(writer.fileno(), b"x" * 4096)
                except BlockingIOError as full:
                    self.assertEqual(full.errno, errno.EAGAIN)
                    break
            else:
                self.fail("A pipe with no reader never applied backpressure")
            self.assertGreater(accepted, 0)
            self.assertLess(time.monotonic() - began, 1)
            recovered = read_pipe(reader.fileno(), min(accepted, 65536))
            self.assertEqual(recovered, b"x" * len(recovered))
            self.assertGreater(len(recovered), 0)

    def test_selector_observes_data_and_eof_without_closing_owned_streams(self):
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd, "rb", buffering=0) as reader, os.fdopen(write_fd, "wb", buffering=0) as writer:
            configure_pipe(reader.fileno())
            configure_pipe(writer.fileno())
            with PipeSelector() as selector:
                key = selector.register(reader, selectors.EVENT_READ, "owned")
                self.assertEqual(selector.get_key(reader), key)
                self.assertEqual(selector.select(0.02), [])
                self.assertEqual(write_pipe(writer.fileno(), b"{}\n"), 3)
                self.assertEqual(selector.select(0.2), [(key, selectors.EVENT_READ)])
                self.assertEqual(read_pipe(reader.fileno(), 8), b"{}\n")
                writer.close()
                self.assertEqual(selector.select(0.2), [(key, selectors.EVENT_READ)])
                self.assertEqual(read_pipe(reader.fileno(), 8), b"")
            self.assertFalse(reader.closed)

    def test_selector_rejects_unbounded_wait_and_closed_use(self):
        selector = PipeSelector()
        for timeout in (None, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                selector.select(timeout)
        self.assertEqual(selector.select(0), [])
        selector.close()
        with self.assertRaises(RuntimeError):
            selector.select(0)

    def test_observed_large_utf8_input_keeps_exact_prefix_hash_and_child_bytes(self):
        payload = "é" * 131072
        inputs, starts = [], []
        script = (
            "import hashlib,json,sys;body=sys.stdin.buffer.read();"
            "print(json.dumps({'bytes':len(body),"
            "'sha256':hashlib.sha256(body).hexdigest()}))"
        )
        result = run_process(
            [sys.executable, "-B", "-c", script],
            env=dict(os.environ),
            timeout_seconds=5,
            cleanup_grace_seconds=0.2,
            stdin_text=payload,
            on_started=starts.append,
            on_input=inputs.append,
        )
        raw = payload.encode("utf-8")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(len(starts), 1)
        self.assertEqual(inputs[0]["status"], "COMPLETE")
        self.assertEqual(inputs[0]["acceptedBytes"], len(raw))
        self.assertEqual(inputs[0]["acceptedSha256"], hashlib.sha256(raw).hexdigest())
        self.assertFalse(inputs[0]["hostConsumptionProven"])
        self.assertEqual(json.loads(result["stdout"]), {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertFalse(process_is_running(starts[0]["pid"]))

    def test_diagnostic_stdout_fragments_utf8_and_enforces_overflow_and_exit(self):
        from agent_lifecycle.adapter_sessions.codex_input_diagnostics import _bounded_codex_debug_output
        from agent_lifecycle.contracts import LifecycleError

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = "import os,time;os.write(1,b'\\xc3');time.sleep(.02);os.write(1,b'\\xa9\\n')"
            result = _bounded_codex_debug_output(
                Path(sys.executable),
                ("-B", "-c", script),
                root=root,
                process_env=dict(os.environ),
                limit=3,
            )
            self.assertEqual(result, "é\n".encode())
            for script, code in (
                ("print('overflow')", "codex-exact-catalog-overflow"),
                ("raise SystemExit(2)", "codex-exact-catalog-unavailable"),
            ):
                with self.subTest(script=script), self.assertRaises(LifecycleError) as error:
                    _bounded_codex_debug_output(
                        Path(sys.executable),
                        ("-B", "-c", script),
                        root=root,
                        process_env=dict(os.environ),
                        limit=3,
                    )
                self.assertEqual(error.exception.code, code)

    def test_diagnostic_ready_bytes_cannot_erase_deadline_and_child_is_reaped(self):
        from agent_lifecycle.adapter_sessions import codex_input_diagnostics as diagnostic
        from agent_lifecycle.adapter_sessions import windows_pipe
        from agent_lifecycle.contracts import LifecycleError

        real_clock, real_read = time.monotonic, windows_pipe.read_pipe
        offset = [0.0]

        def advance_after_read(*args):
            chunk = real_read(*args)
            if chunk:
                offset[0] = 16.0
            return chunk

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = (
                "import os,pathlib,time;pathlib.Path('child.pid').write_text(str(os.getpid()));"
                "os.write(1,b'x');time.sleep(30)"
            )
            with (
                patch.object(diagnostic.time, "monotonic", side_effect=lambda: real_clock() + offset[0]),
                patch.object(windows_pipe, "read_pipe", side_effect=advance_after_read),
                self.assertRaises(LifecycleError) as error,
            ):
                diagnostic._bounded_codex_debug_output(
                    Path(sys.executable),
                    ("-B", "-c", script),
                    root=root,
                    process_env=dict(os.environ),
                    limit=3,
                )
            self.assertEqual(error.exception.code, "codex-exact-catalog-unavailable")
            self.assertIn("timed out", str(error.exception))
            self.assertFalse(process_is_running(int((root / "child.pid").read_text())))

    def test_stalled_peer_timeout_and_cancel_preserve_partial_input_and_reap(self):
        payload = "x" * 1_048_576
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                cancelled = threading.Event()
                timer = threading.Timer(0.05, cancelled.set)
                inputs, starts = [], []

                def started(event, starts=starts, cancel=cancel, timer=timer):
                    starts.append(event)
                    if cancel:
                        timer.start()

                began = time.monotonic()
                try:
                    result = run_process(
                        [sys.executable, "-B", "-c", "import time;time.sleep(30)"],
                        env=dict(os.environ),
                        timeout_seconds=5 if cancel else 1.0,
                        cleanup_grace_seconds=0.2,
                        stdin_text=payload,
                        cancel_event=cancelled,
                        on_started=started,
                        on_input=inputs.append,
                    )
                finally:
                    timer.cancel()
                    if cancel:
                        timer.join(timeout=1)
                self.assertLess(time.monotonic() - began, 3)
                self.assertTrue(result["processStarted"])
                self.assertEqual(result["cancelled"], cancel)
                self.assertEqual(result["timedOut"], not cancel)
                self.assertEqual(result["cleanup"]["status"], "PASS")
                observation = result["inputObservation"]
                self.assertEqual(observation["status"], "PARTIAL_OR_FAILED")
                # An expired deadline forbids starting an external callback.
                if inputs:
                    self.assertEqual(inputs[0], observation)
                else:
                    self.assertTrue(result["timedOut"])
                count = observation["acceptedBytes"]
                self.assertLess(count, len(payload))
                self.assertEqual(observation["acceptedSha256"], hashlib.sha256(payload[:count].encode()).hexdigest())
                self.assertFalse(process_is_running(starts[0]["pid"]))


if __name__ == "__main__":
    unittest.main()
