"""Secure, bounded and observable process execution for adapter sessions."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.process_groups import ProcessGroupOwner, popen_group_kwargs
from agent_lifecycle.adapter_sessions.process_telemetry import ProcessTelemetry
from agent_lifecycle.adapter_sessions.redaction import redact_process_text
from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.contracts.process_execution_schemas import (
    build_process_execution_receipt,
    command_identity_hash,
    process_identity_hash,
)

DEFAULT_OUTPUT_BYTES = 262_144
DEFAULT_CLEANUP_GRACE_SECONDS = 1.0


def run_process(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: float,
    cwd: Path | None = None,
    stdin_text: str | None = None,
    max_input_bytes: int | None = None,
    max_output_bytes: int | None = None,
    operation_id: str | None = None,
    attempt_id: str | None = None,
    adapter_id: str | None = None,
    cancel_event: threading.Event | None = None,
    cleanup_grace_seconds: float = DEFAULT_CLEANUP_GRACE_SECONDS,
    retry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one shell-free child and return legacy fields plus a typed receipt."""

    input_text = stdin_text or ""
    input_bytes = input_text.encode("utf-8")
    output_limit = max_output_bytes if max_output_bytes is not None else DEFAULT_OUTPUT_BYTES
    identity = command_identity_hash(argv)
    if stdin_text is not None and max_input_bytes is not None and len(input_bytes) > max_input_bytes:
        return _bounded_failure(
            "adapter-process-input-limit",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={"maxInputBytes": max_input_bytes},
            command_hash=identity,
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            retry=retry,
        )
    if output_limit < 1:
        return _bounded_failure(
            "adapter-process-output-limit-invalid",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={"maxOutputBytes": output_limit},
            command_hash=identity,
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            retry=retry,
        )

    try:
        process = subprocess.Popen(
            argv,
            shell=False,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            **popen_group_kwargs(),
        )
    except OSError as exc:
        return _bounded_failure(
            "adapter-process-start-failed",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={"errorType": type(exc).__name__},
            command_hash=identity,
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            retry=retry,
        )

    owner = ProcessGroupOwner(process)
    telemetry = ProcessTelemetry(pid=process.pid, group_id=owner.group_id)
    process_hash = process_identity_hash(pid=process.pid, started_ns=telemetry.started_ns)
    group_hash = canonical_digest({"mode": owner.mode, "processIdentityHash": process_hash})
    captures: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
    total_output = 0
    output_limit_exceeded = threading.Event()
    capture_lock = threading.Lock()

    def read_stream(name: str, stream: Any) -> None:
        nonlocal total_output
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            with capture_lock:
                remaining = max(output_limit - total_output, 0)
                if remaining:
                    captures[name].extend(chunk[:remaining])
                    total_output += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    output_limit_exceeded.set()
                    return

    readers = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    assert process.stdin is not None
    try:
        if input_bytes:
            process.stdin.write(input_bytes)
        process.stdin.close()
    except (BrokenPipeError, OSError):
        try:
            process.stdin.close()
        except OSError:
            pass

    timed_out = False
    cancelled = False
    while process.poll() is None:
        telemetry.sample()
        if output_limit_exceeded.is_set():
            break
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        if time.monotonic() - telemetry.started_ns / 1_000_000_000 >= max(0.01, timeout_seconds):
            timed_out = True
            break
        time.sleep(0.02)

    if process.poll() is None:
        cleanup = owner.terminate(grace_seconds=max(0.05, cleanup_grace_seconds))
    else:
        process.wait()
        cleanup = owner.verify()
        if cleanup.get("status") != "PASS":
            cleanup = owner.terminate(grace_seconds=max(0.05, cleanup_grace_seconds))
    for reader in readers:
        reader.join(timeout=max(0.1, cleanup_grace_seconds))
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()
    telemetry_values = telemetry.finish()
    exit_code = process.returncode
    owner.close()

    stdout = captures["stdout"].decode("utf-8", errors="replace")
    stderr = captures["stderr"].decode("utf-8", errors="replace")
    stdout_tail, stdout_redacted = redact_process_text(stdout[-2000:])
    stderr_tail, stderr_redacted = redact_process_text(stderr[-2000:])
    blockers: list[dict[str, Any]] = []
    if output_limit_exceeded.is_set():
        blockers.append({"code": "adapter-process-output-limit", "maxOutputBytes": output_limit})
    elif timed_out:
        blockers.append({"code": "adapter-process-timeout", "timeoutSeconds": timeout_seconds})
    elif cancelled:
        blockers.append({"code": "adapter-process-cancelled"})
    elif exit_code != 0:
        blockers.append({"code": "adapter-process-nonzero-exit", "exitCode": exit_code})
    if cleanup.get("status") != "PASS":
        blockers.append({"code": "adapter-process-cleanup-unverified", "cleanup": cleanup})
    status = "BLOCKED" if cleanup.get("status") != "PASS" else ("PASS" if not blockers else "FAIL")
    receipt = build_process_execution_receipt(
        status=status,
        operation_id=operation_id,
        attempt_id=attempt_id,
        adapter_id=adapter_id,
        command_identity_hash=identity,
        process_identity_hash=process_hash,
        group_identity_hash=group_hash,
        elapsed_ms=telemetry_values["elapsedMs"],
        cpu_ms=telemetry_values["cpuMs"],
        peak_memory_mb=telemetry_values["peakMemoryMb"],
        process_count=telemetry_values["processCount"],
        cleanup=cleanup,
        exit_code=exit_code,
        timed_out=timed_out,
        cancelled=cancelled,
        retry=retry,
        limits={
            "timeoutSeconds": timeout_seconds,
            "maxInputBytes": max_input_bytes,
            "maxOutputBytes": output_limit,
            "cleanupGraceSeconds": cleanup_grace_seconds,
        },
        blockers=blockers,
    )
    return {
        "status": status,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "cancelled": cancelled,
        "processStarted": True,
        "inputBytes": len(input_bytes),
        "outputBytes": total_output,
        "outputLimitExceeded": output_limit_exceeded.is_set(),
        "stdout": stdout,
        "stderr": stderr,
        "stdoutTail": stdout_tail,
        "stdoutRedacted": stdout_redacted,
        "stderrTail": stderr_tail,
        "stderrRedacted": stderr_redacted,
        "cleanup": cleanup,
        "processReceipt": receipt,
        "blockers": blockers,
    }


def _bounded_failure(
    code: str,
    *,
    input_bytes: int,
    output_bytes: int,
    process_started: bool,
    details: dict[str, Any],
    command_hash: str,
    operation_id: str | None,
    attempt_id: str | None,
    adapter_id: str | None,
    retry: dict[str, Any] | None,
) -> dict[str, Any]:
    blocker = {"code": code, **details}
    receipt = build_process_execution_receipt(
        status="FAIL",
        operation_id=operation_id,
        attempt_id=attempt_id,
        adapter_id=adapter_id,
        command_identity_hash=command_hash,
        process_identity_hash=None,
        group_identity_hash=None,
        elapsed_ms=0,
        cpu_ms={"value": None, "availability": "UNAVAILABLE", "source": "not-started"},
        peak_memory_mb={"value": None, "availability": "UNAVAILABLE", "source": "not-started"},
        process_count={"value": None, "availability": "UNAVAILABLE", "source": "not-started"},
        cleanup={"status": "PASS", "attestation": "NOT_STARTED"},
        exit_code=None,
        timed_out=False,
        cancelled=False,
        retry=retry,
        blockers=[blocker],
    )
    return {
        "status": "FAIL",
        "exitCode": None,
        "timedOut": False,
        "cancelled": False,
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
        "cleanup": {"status": "PASS", "attestation": "NOT_STARTED"},
        "processReceipt": receipt,
        "blockers": [blocker],
    }
