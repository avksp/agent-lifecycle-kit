"""Secure process execution for managed adapter sessions."""

from __future__ import annotations

import subprocess
import threading
from typing import Any

from agent_lifecycle.adapter_sessions.redaction import redact_process_text


def run_process(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: float,
    stdin_text: str | None = None,
    max_input_bytes: int | None = None,
    max_output_bytes: int | None = None,
) -> dict[str, Any]:
    if stdin_text is not None or max_output_bytes is not None:
        return _run_bounded_process(
            argv,
            env=env,
            timeout_seconds=timeout_seconds,
            stdin_text=stdin_text or "",
            max_input_bytes=max_input_bytes,
            max_output_bytes=max_output_bytes,
        )
    try:
        result = subprocess.run(
            argv,
            shell=False,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        stdout_tail, stdout_redacted = redact_process_text(result.stdout[-2000:])
        stderr_tail, stderr_redacted = redact_process_text(result.stderr[-2000:])
        return {
            "status": "PASS" if result.returncode == 0 else "FAIL",
            "exitCode": result.returncode,
            "timedOut": False,
            "stdoutTail": stdout_tail,
            "stdoutRedacted": stdout_redacted,
            "stderrTail": stderr_tail,
            "stderrRedacted": stderr_redacted,
            "blockers": [] if result.returncode == 0 else [{"code": "adapter-process-nonzero-exit", "exitCode": result.returncode}],
        }
    except subprocess.TimeoutExpired as exc:
        stdout_tail, stdout_redacted = redact_process_text(
            (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else ""
        )
        stderr_tail, stderr_redacted = redact_process_text(
            (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else ""
        )
        return {
            "status": "FAIL",
            "exitCode": None,
            "timedOut": True,
            "stdoutTail": stdout_tail,
            "stdoutRedacted": stdout_redacted,
            "stderrTail": stderr_tail,
            "stderrRedacted": stderr_redacted,
            "blockers": [{"code": "adapter-process-timeout", "timeoutSeconds": timeout_seconds}],
        }
    except OSError as exc:
        return {
            "status": "FAIL",
            "exitCode": None,
            "timedOut": False,
            "stdoutTail": "",
            "stdoutRedacted": False,
            "stderrTail": "",
            "stderrRedacted": False,
            "blockers": [{"code": "adapter-process-start-failed", "errorType": type(exc).__name__}],
        }


def _run_bounded_process(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: float,
    stdin_text: str,
    max_input_bytes: int | None,
    max_output_bytes: int | None,
) -> dict[str, Any]:
    input_bytes = stdin_text.encode("utf-8")
    if max_input_bytes is not None and len(input_bytes) > max_input_bytes:
        return _bounded_failure(
            "adapter-process-input-limit",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={"maxInputBytes": max_input_bytes},
        )
    output_limit = max_output_bytes if max_output_bytes is not None else 262_144
    if output_limit < 1:
        return _bounded_failure(
            "adapter-process-output-limit-invalid",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={"maxOutputBytes": output_limit},
        )
    try:
        process = subprocess.Popen(
            argv,
            shell=False,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        return _bounded_failure(
            "adapter-process-start-failed",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={"errorType": type(exc).__name__},
        )

    captures: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0
    limit_exceeded = threading.Event()
    lock = threading.Lock()

    def read_stream(name: str, stream: Any) -> None:
        nonlocal total
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with lock:
                remaining = max(output_limit - total, 0)
                if remaining:
                    captures[name].extend(chunk[:remaining])
                    total += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    limit_exceeded.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return

    readers = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    assert process.stdin is not None
    try:
        process.stdin.write(input_bytes)
        process.stdin.close()
    except BrokenPipeError:
        pass

    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    for reader in readers:
        reader.join(timeout=1)
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdout.close()
    process.stderr.close()

    stdout = captures["stdout"].decode("utf-8", errors="replace")
    stderr = captures["stderr"].decode("utf-8", errors="replace")
    stdout_tail, stdout_redacted = redact_process_text(stdout[-2000:])
    stderr_tail, stderr_redacted = redact_process_text(stderr[-2000:])
    blockers: list[dict[str, Any]] = []
    if limit_exceeded.is_set():
        blockers.append({"code": "adapter-process-output-limit", "maxOutputBytes": output_limit})
    elif timed_out:
        blockers.append({"code": "adapter-process-timeout", "timeoutSeconds": timeout_seconds})
    elif process.returncode != 0:
        blockers.append({"code": "adapter-process-nonzero-exit", "exitCode": process.returncode})
    return {
        "status": "PASS" if not blockers else "FAIL",
        "exitCode": process.returncode,
        "timedOut": timed_out,
        "processStarted": True,
        "inputBytes": len(input_bytes),
        "outputBytes": total,
        "outputLimitExceeded": limit_exceeded.is_set(),
        "stdout": stdout,
        "stderr": stderr,
        "stdoutTail": stdout_tail,
        "stdoutRedacted": stdout_redacted,
        "stderrTail": stderr_tail,
        "stderrRedacted": stderr_redacted,
        "blockers": blockers,
    }


def _bounded_failure(
    code: str,
    *,
    input_bytes: int,
    output_bytes: int,
    process_started: bool,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "exitCode": None,
        "timedOut": False,
        "processStarted": process_started,
        "inputBytes": input_bytes,
        "outputBytes": output_bytes,
        "outputLimitExceeded": code == "adapter-process-output-limit",
        "stdout": "",
        "stderr": "",
        "stdoutTail": "",
        "stdoutRedacted": False,
        "stderrTail": "",
        "stderrRedacted": False,
        "blockers": [{"code": code, **details}],
    }
