"""Public bounded process boundary with decomposed capture and receipt helpers."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from agent_lifecycle.adapter_sessions.process_capture import _CaptureState, _write_stdin
from agent_lifecycle.adapter_sessions.process_control import (
    DEFAULT_CLEANUP_GRACE_SECONDS,
    DEFAULT_OUTPUT_BYTES,
    _bounded_failure,
    _build_process_result,
    _invalid_limit_failure,
)
from agent_lifecycle.adapter_sessions.process_groups import ProcessGroupOwner, popen_group_kwargs
from agent_lifecycle.adapter_sessions.process_telemetry import ProcessTelemetry
from agent_lifecycle.contracts import canonical_digest


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
    """Run one shell-free child while retaining bounded cleanup and receipts."""

    input_bytes = (stdin_text or "").encode("utf-8")
    output_limit = max_output_bytes if max_output_bytes is not None else DEFAULT_OUTPUT_BYTES
    from agent_lifecycle.contracts.process_execution_schemas import command_identity_hash

    command_hash = command_identity_hash(argv)
    invalid = _invalid_limit_failure(
        input_bytes=input_bytes,
        output_limit=output_limit,
        max_input_bytes=max_input_bytes,
        command_hash=command_hash,
        operation_id=operation_id,
        attempt_id=attempt_id,
        adapter_id=adapter_id,
        retry=retry,
    )
    if invalid is not None:
        return invalid
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
            command_hash=command_hash,
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            retry=retry,
        )

    owner = ProcessGroupOwner(process)
    telemetry = ProcessTelemetry(pid=process.pid, group_id=owner.group_id)
    process_hash = _process_identity_hash(process.pid, telemetry.started_ns)
    group_hash = canonical_digest({"mode": owner.mode, "processIdentityHash": process_hash})
    capture = _CaptureState(output_limit)
    readers = capture.start(process)
    _write_stdin(process, input_bytes)
    timed_out = False
    cancelled = False
    while process.poll() is None:
        telemetry.sample()
        if capture.output_limit_exceeded.is_set():
            break
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        elapsed = time.monotonic() - telemetry.started_ns / 1_000_000_000
        if elapsed >= max(0.01, timeout_seconds):
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
    capture.finish(process, readers, cleanup_grace_seconds)
    telemetry_values = telemetry.finish()
    result = _build_process_result(
        process,
        capture=capture,
        telemetry_values=telemetry_values,
        cleanup=cleanup,
        timed_out=timed_out,
        cancelled=cancelled,
        timeout_seconds=timeout_seconds,
        output_limit=output_limit,
        max_input_bytes=max_input_bytes,
        input_bytes=input_bytes,
        command_hash=command_hash,
        process_hash=process_hash,
        group_hash=group_hash,
        operation_id=operation_id,
        attempt_id=attempt_id,
        adapter_id=adapter_id,
        retry=retry,
        cleanup_grace_seconds=cleanup_grace_seconds,
    )
    owner.close()
    return result


def _process_identity_hash(pid: int, started_ns: int) -> str:
    from agent_lifecycle.contracts.process_execution_schemas import process_identity_hash

    return process_identity_hash(pid=pid, started_ns=started_ns)
