"""Implementation of bounded, shell-free process control."""

from __future__ import annotations

import subprocess
import threading
from typing import Any

from agent_lifecycle.adapter_sessions.process_capture import _CaptureState
from agent_lifecycle.adapter_sessions.redaction import redact_process_text
from agent_lifecycle.contracts.process_execution_schemas import build_process_execution_receipt

DEFAULT_OUTPUT_BYTES = 262_144
DEFAULT_CLEANUP_GRACE_SECONDS = 1.0

def _invalid_limit_failure(
    *,
    input_bytes: bytes,
    output_limit: int,
    max_input_bytes: int | None,
    command_hash: str,
    operation_id: str | None,
    attempt_id: str | None,
    adapter_id: str | None,
    retry: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if max_input_bytes is not None and len(input_bytes) > max_input_bytes:
        return _bounded_failure(
            "adapter-process-input-limit",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={"maxInputBytes": max_input_bytes},
            command_hash=command_hash,
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
            command_hash=command_hash,
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            retry=retry,
        )
    return None

def _build_process_result(
    process: subprocess.Popen[Any],
    *,
    capture: _CaptureState,
    telemetry_values: dict[str, Any],
    cleanup: dict[str, Any],
    timed_out: bool,
    cancelled: bool,
    timeout_seconds: float,
    output_limit: int,
    max_input_bytes: int | None,
    input_bytes: bytes,
    command_hash: str,
    process_hash: str,
    group_hash: str,
    operation_id: str | None,
    attempt_id: str | None,
    adapter_id: str | None,
    retry: dict[str, Any] | None,
    cleanup_grace_seconds: float,
) -> dict[str, Any]:
    stdout = capture.captures["stdout"].decode("utf-8", errors="replace")
    stderr = capture.captures["stderr"].decode("utf-8", errors="replace")
    stdout_tail, stdout_redacted = redact_process_text(stdout[-2000:])
    stderr_tail, stderr_redacted = redact_process_text(stderr[-2000:])
    blockers = _process_blockers(
        capture.output_limit_exceeded,
        timed_out=timed_out,
        cancelled=cancelled,
        exit_code=process.returncode,
        cleanup=cleanup,
        timeout_seconds=timeout_seconds,
        output_limit=output_limit,
    )
    status = "BLOCKED" if cleanup.get("status") != "PASS" else ("PASS" if not blockers else "FAIL")
    receipt = build_process_execution_receipt(
        status=status,
        operation_id=operation_id,
        attempt_id=attempt_id,
        adapter_id=adapter_id,
        command_identity_hash=command_hash,
        process_identity_hash=process_hash,
        group_identity_hash=group_hash,
        elapsed_ms=telemetry_values["elapsedMs"],
        cpu_ms=telemetry_values["cpuMs"],
        peak_memory_mb=telemetry_values["peakMemoryMb"],
        process_count=telemetry_values["processCount"],
        cleanup=cleanup,
        exit_code=process.returncode,
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
        "exitCode": process.returncode,
        "timedOut": timed_out,
        "cancelled": cancelled,
        "processStarted": True,
        "inputBytes": len(input_bytes),
        "outputBytes": capture.total_output,
        "outputLimitExceeded": capture.output_limit_exceeded.is_set(),
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

def _process_blockers(
    output_limit_exceeded: threading.Event,
    *,
    timed_out: bool,
    cancelled: bool,
    exit_code: int | None,
    cleanup: dict[str, Any],
    timeout_seconds: float,
    output_limit: int,
) -> list[dict[str, Any]]:
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
    return blockers

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
