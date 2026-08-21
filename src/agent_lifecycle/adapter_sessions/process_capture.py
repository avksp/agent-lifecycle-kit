"""Bounded stdout, stderr and stdin process capture helpers."""

from __future__ import annotations

import subprocess
import threading
from typing import Any


class _CaptureState:
    """Bound stdout and stderr capture shared by two reader threads."""

    def __init__(self, output_limit: int) -> None:
        self.output_limit = output_limit
        self.captures: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        self.total_output = 0
        self.output_limit_exceeded = threading.Event()
        self._lock = threading.Lock()

    def start(self, process: subprocess.Popen[Any]) -> list[threading.Thread]:
        return [
            self._reader("stdout", process.stdout),
            self._reader("stderr", process.stderr),
        ]

    def _reader(self, name: str, stream: Any) -> threading.Thread:
        reader = threading.Thread(target=self._read_stream, args=(name, stream), daemon=True)
        reader.start()
        return reader

    def _read_stream(self, name: str, stream: Any) -> None:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with self._lock:
                remaining = max(self.output_limit - self.total_output, 0)
                if remaining:
                    self.captures[name].extend(chunk[:remaining])
                    self.total_output += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    self.output_limit_exceeded.set()
                    return

    def finish(
        self,
        process: subprocess.Popen[Any],
        readers: list[threading.Thread],
        cleanup_grace_seconds: float,
    ) -> None:
        for reader in readers:
            reader.join(timeout=max(0.1, cleanup_grace_seconds))
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _write_stdin(process: subprocess.Popen[Any], input_bytes: bytes) -> None:
    if process.stdin is None:
        return
    try:
        if input_bytes:
            process.stdin.write(input_bytes)
        process.stdin.close()
    except (BrokenPipeError, OSError):
        try:
            process.stdin.close()
        except OSError:
            pass
