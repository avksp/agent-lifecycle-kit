"""Public bounded process boundary with decomposed capture and receipt helpers."""

from __future__ import annotations

import contextlib
import hashlib
import os
import select
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Generic, TypeVar
from typing import cast as _validated_cast

from agent_lifecycle.adapter_sessions.process_capture import _CaptureState
from agent_lifecycle.adapter_sessions.process_capture import _write_stdin as _write_stdin
from agent_lifecycle.adapter_sessions.process_control import (
    DEFAULT_CLEANUP_GRACE_SECONDS,
    DEFAULT_OUTPUT_BYTES,
    _bounded_failure,
    _build_process_result,
    _invalid_limit_failure,
)
from agent_lifecycle.adapter_sessions.process_groups import (
    ProcessGroupOwner,
    _wait_process_group_exit,
    popen_group_kwargs,
)
from agent_lifecycle.adapter_sessions.process_telemetry import ProcessTelemetry
from agent_lifecycle.contracts import canonical_digest

_Failure = TypeVar("_Failure", bound=BaseException)


class _CapturedFailure(Generic[_Failure]):
    """Retain one selected failure for the existing caller's error observation."""

    def __init__(self, capture_type: type[_Failure]) -> None:
        self.capture_type = capture_type
        self.error: _Failure | None = None

    def __enter__(self) -> _CapturedFailure[_Failure]:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, traceback: TracebackType | None
    ) -> bool:
        if error is None or not isinstance(error, self.capture_type):
            return False
        self.error = error
        return True


class _ObserverSlots:
    """Bound runs and live callback threads; reap only after Thread termination."""

    def __init__(self, limit: int = 8) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("observer capacity must be positive")
        self.limit = limit
        self._lock = threading.Lock()
        self._leases: list[_ObserverLease] = []

    def _reap_locked(self) -> None:
        self._leases[:] = [
            lease
            for lease in self._leases
            if not (lease.process_done and all(not thread.is_alive() for thread in lease.threads))
        ]

    def acquire(self, *, blocking: bool = False) -> _ObserverLease | None:
        if blocking:
            raise ValueError("observer admission must not wait")
        with self._lock:
            self._reap_locked()
            if len(self._leases) >= self.limit:
                return None
            lease = _ObserverLease(self)
            self._leases.append(lease)
            return lease


class _ObserverLease:
    def __init__(self, slots: _ObserverSlots) -> None:
        self.slots = slots
        self.threads: list[threading.Thread] = []
        self.process_done = False

    def register(self, thread: threading.Thread) -> None:
        with self.slots._lock:
            self.threads.append(thread)

    def process_finished(self) -> None:
        with self.slots._lock:
            self.process_done = True
            self.slots._reap_locked()


def _observe_process_before_deadline(
    callback: Callable[[dict[str, Any]], None], event: dict[str, Any], deadline: float, observer_lease
) -> tuple[bool, BaseException | None]:
    """Bound an observation without letting it hold child cleanup."""
    assert observer_lease is not None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return (True, None)
    errors: list[BaseException] = []
    completed_at: list[float] = []

    def invoke() -> None:
        _captured_failure_9 = _CapturedFailure(BaseException)
        try:
            with _captured_failure_9:
                callback(event)
            if _captured_failure_9.error is not None:
                exc = _captured_failure_9.error
                errors.append(exc)
        finally:
            completed_at.append(time.monotonic())

    thread = threading.Thread(target=invoke, name="alk-process-observer", daemon=True)
    observer_lease.register(thread)
    _captured_failure_8 = _CapturedFailure(Exception)
    with _captured_failure_8:
        thread.start()
    if _captured_failure_8.error is not None:
        exc = _captured_failure_8.error
        return (False, exc)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return (True, None)
    thread.join(remaining)
    if thread.is_alive() or not completed_at:
        return (True, None)
    if completed_at[0] > deadline:
        return (True, None)
    return (False, errors[0] if errors else None)


def _process_deadline_failure(
    absolute_deadline_monotonic_ns, adapter_id, attempt_id, command_hash, input_bytes, operation_id, retry
) -> dict[str, Any]:
    return _bounded_failure(
        "adapter-process-absolute-deadline-expired",
        input_bytes=len(input_bytes),
        output_bytes=0,
        process_started=False,
        details={"absoluteDeadlineMonotonicNs": absolute_deadline_monotonic_ns},
        command_hash=command_hash,
        operation_id=operation_id,
        attempt_id=attempt_id,
        adapter_id=adapter_id,
        retry=retry,
    )


def _record_process_clock(
    result: dict[str, Any], absolute_deadline_monotonic_ns, deadline_ns, started_ns
) -> dict[str, Any]:
    if absolute_deadline_monotonic_ns is not None:
        result["absoluteDeadlineMonotonicNs"] = absolute_deadline_monotonic_ns
        result["deadlineMonotonicNs"] = deadline_ns
        if result.get("processStarted") is True:
            result["startedMonotonicNs"] = started_ns
    return result


def _finish_started_process(
    *,
    adapter_id,
    attempt_id,
    cancel_event,
    capture,
    cleanup_grace_seconds,
    command_hash,
    deadline,
    deadline_ns,
    group_hash,
    input_bytes,
    input_observation,
    max_input_bytes,
    on_started,
    operation_id,
    output_limit,
    owner,
    process,
    process_hash,
    reader_errors,
    readers,
    retry,
    start_observation,
    telemetry,
    timeout_seconds,
):
    timed_out = False
    cancelled = False
    while process.poll() is None:
        if reader_errors:
            raise RuntimeError("process capture reader failed")
        telemetry.sample()
        if capture.output_limit_exceeded.is_set():
            break
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        if time.monotonic() >= deadline:
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
    _finish_capture(process, capture, readers, cleanup_grace_seconds)
    if reader_errors:
        raise RuntimeError("process capture reader failed")
    telemetry_values = telemetry.finish()
    timed_out = timed_out or time.monotonic() >= deadline
    cancelled = cancelled or (cancel_event is not None and cancel_event.is_set())
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
    result["deadlineMonotonicNs"] = deadline_ns
    result["observerDisposition"] = "COMPLETED" if on_started is not None else "NOT_REQUESTED"
    if start_observation is not None:
        result["startObservation"] = _public_start_observation(start_observation)
        result["inputObservation"] = input_observation
    return result


@dataclass(frozen=True, slots=True)
class _OwnedProcessInputs:
    absolute_deadline_monotonic_ns: int | None
    adapter_id: str | None
    argv: list[str]
    attempt_id: str | None
    cancel_event: threading.Event | None
    cleanup_grace_seconds: float
    command_hash: str
    cwd: Path | None
    deadline_ns: int
    env: dict[str, str]
    input_bytes: bytes
    max_input_bytes: int | None
    observer_lease: _ObserverLease | None
    on_input: Callable[[dict[str, Any]], None] | None
    on_started: Callable[[dict[str, Any]], None] | None
    operation_id: str | None
    output_limit: int
    retry: dict[str, Any] | None
    started_ns: int
    timeout_seconds: float


@dataclass(slots=True)
class _OwnedProcessState:
    process: subprocess.Popen[Any] | None = None
    owner: ProcessGroupOwner | None = None
    capture: _CaptureState | None = None
    telemetry: ProcessTelemetry | None = None
    start_observation: dict[str, Any] | None = None
    input_observation: dict[str, Any] | None = None
    process_hash: str | None = None
    group_hash: str | None = None
    deadline: float | None = None
    readers: list[threading.Thread] = field(default_factory=list)


def _owned_observed_failure(
    inputs: _OwnedProcessInputs,
    state: _OwnedProcessState,
    code: str,
    error: BaseException | None,
    start_observation: dict[str, Any] | None,
    input_observation: dict[str, Any] | None,
    *,
    timed_out: bool = False,
) -> dict[str, Any]:
    return _observed_failure(
        _validated_cast(subprocess.Popen[Any], state.process),
        _validated_cast(ProcessGroupOwner, state.owner),
        _validated_cast(_CaptureState, state.capture),
        _validated_cast(ProcessTelemetry, state.telemetry),
        inputs.command_hash,
        _validated_cast(str, state.process_hash),
        _validated_cast(str, state.group_hash),
        inputs.input_bytes,
        inputs.output_limit,
        inputs.timeout_seconds,
        inputs.cleanup_grace_seconds,
        inputs.operation_id,
        inputs.attempt_id,
        inputs.adapter_id,
        inputs.retry,
        code,
        error,
        start_observation,
        input_observation,
        state.readers,
        timed_out=timed_out,
    )


def _execute_started_owned_process(inputs: _OwnedProcessInputs, state: _OwnedProcessState) -> dict[str, Any]:
    absolute_deadline_monotonic_ns = inputs.absolute_deadline_monotonic_ns
    adapter_id = inputs.adapter_id
    argv = inputs.argv
    attempt_id = inputs.attempt_id
    command_hash = inputs.command_hash
    cwd = inputs.cwd
    deadline_ns = inputs.deadline_ns
    env = inputs.env
    input_bytes = inputs.input_bytes
    observer_lease = inputs.observer_lease
    on_started = inputs.on_started
    operation_id = inputs.operation_id
    output_limit = inputs.output_limit
    retry = inputs.retry
    started_ns = inputs.started_ns
    if absolute_deadline_monotonic_ns is not None and time.monotonic_ns() >= deadline_ns:
        return _process_deadline_failure(
            absolute_deadline_monotonic_ns, adapter_id, attempt_id, command_hash, input_bytes, operation_id, retry
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
        state.process = process
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
    state.owner = owner
    telemetry = ProcessTelemetry(pid=process.pid, group_id=owner.group_id)
    state.telemetry = telemetry
    telemetry.started_ns = started_ns
    process_hash = _process_identity_hash(process.pid, telemetry.started_ns)
    state.process_hash = process_hash
    group_hash = canonical_digest({"mode": owner.mode, "processIdentityHash": process_hash})
    state.group_hash = group_hash
    capture = _CaptureState(output_limit)
    state.capture = capture
    deadline = deadline_ns / 1000000000
    state.deadline = deadline
    if on_started is not None:
        start_observation = {
            "pid": process.pid,
            "processIdentityHash": process_hash,
            "groupIdentityHash": group_hash,
            "commandIdentityHash": command_hash,
            "argv": list(argv),
            "cwd": str(cwd) if cwd is not None else None,
            "codexHome": env.get("CODEX_HOME"),
            "environmentSha256": canonical_digest(env),
            "plannedStdinBytes": len(input_bytes),
            "plannedStdinSha256": hashlib.sha256(input_bytes).hexdigest(),
            "stdinStatus": "PENDING",
            "operationId": operation_id,
            "attemptId": attempt_id,
            "adapterId": adapter_id,
        }
        state.start_observation = start_observation
        start_timed_out, start_error = _observe_process_before_deadline(
            on_started, start_observation, deadline, observer_lease
        )
        start_timed_out = start_timed_out or time.monotonic() >= deadline
        if start_timed_out or start_error is not None:
            return _owned_observed_failure(
                inputs,
                state,
                "adapter-process-start-observation-timeout"
                if start_timed_out
                else "adapter-process-start-observation-failed",
                start_error,
                start_observation,
                None,
                timed_out=start_timed_out,
            )
    return _write_and_finish_owned_process(inputs, state)


def _write_and_finish_owned_process(inputs: _OwnedProcessInputs, state: _OwnedProcessState) -> dict[str, Any]:
    adapter_id = inputs.adapter_id
    attempt_id = inputs.attempt_id
    cancel_event = inputs.cancel_event
    cleanup_grace_seconds = inputs.cleanup_grace_seconds
    command_hash = inputs.command_hash
    deadline_ns = inputs.deadline_ns
    input_bytes = inputs.input_bytes
    max_input_bytes = inputs.max_input_bytes
    observer_lease = inputs.observer_lease
    on_input = inputs.on_input
    on_started = inputs.on_started
    operation_id = inputs.operation_id
    output_limit = inputs.output_limit
    retry = inputs.retry
    timeout_seconds = inputs.timeout_seconds
    capture = _validated_cast(_CaptureState, state.capture)
    deadline = _validated_cast(float, state.deadline)
    group_hash = _validated_cast(str, state.group_hash)
    input_observation = state.input_observation
    owner = _validated_cast(ProcessGroupOwner, state.owner)
    process = _validated_cast(subprocess.Popen[Any], state.process)
    process_hash = _validated_cast(str, state.process_hash)
    start_observation = state.start_observation
    telemetry = _validated_cast(ProcessTelemetry, state.telemetry)
    readers = state.readers
    reader_errors = _start_capture(process, capture, readers)
    if on_input is None and inputs.absolute_deadline_monotonic_ns is None:
        input_observation = _write_ordinary_stdin(inputs, state)
        state.input_observation = input_observation
        if input_observation is not None:
            failed = _owned_observed_failure(
                inputs,
                state,
                "adapter-process-input-incomplete",
                None,
                None,
                input_observation,
                timed_out=time.monotonic() >= deadline,
            )
            failed["observerDisposition"] = "NOT_REQUESTED"
            return failed
    elif on_input is None:
        input_observation = _write_observed_stdin(
            process,
            input_bytes,
            timeout_seconds,
            telemetry.started_ns / 1000000000,
            cancel_event,
            operation_id,
            attempt_id,
            adapter_id,
            process_hash,
            deadline_monotonic_ns=deadline_ns,
        )
        state.input_observation = input_observation
        if input_observation["status"] != "COMPLETE":
            failed = _owned_observed_failure(
                inputs,
                state,
                "adapter-process-input-incomplete",
                None,
                None,
                input_observation,
                timed_out=time.monotonic() >= deadline,
            )
            failed["observerDisposition"] = "NOT_REQUESTED"
            return failed
    else:
        input_observation = _write_observed_stdin(
            process,
            input_bytes,
            timeout_seconds,
            telemetry.started_ns / 1000000000,
            cancel_event,
            operation_id,
            attempt_id,
            adapter_id,
            process_hash,
            deadline_monotonic_ns=deadline_ns,
        )
        state.input_observation = input_observation
        input_timed_out, input_error = _observe_process_before_deadline(
            on_input, input_observation, deadline, observer_lease
        )
        input_timed_out = input_timed_out or time.monotonic() >= deadline
        input_cancelled = cancel_event is not None and cancel_event.is_set()
        if input_timed_out or input_cancelled or input_error is not None:
            return _owned_observed_failure(
                inputs,
                state,
                "adapter-process-input-observation-timeout"
                if input_timed_out
                else "adapter-process-input-observation-cancelled"
                if input_cancelled
                else "adapter-process-input-observation-failed",
                input_error,
                start_observation,
                input_observation,
                timed_out=input_timed_out,
            )
        if input_observation["status"] != "COMPLETE":
            return _owned_observed_failure(
                inputs, state, "adapter-process-input-incomplete", None, start_observation, input_observation
            )
    return _finish_started_process(
        adapter_id=adapter_id,
        attempt_id=attempt_id,
        cancel_event=cancel_event,
        capture=capture,
        cleanup_grace_seconds=cleanup_grace_seconds,
        command_hash=command_hash,
        deadline=deadline,
        deadline_ns=deadline_ns,
        group_hash=group_hash,
        input_bytes=input_bytes,
        input_observation=input_observation,
        max_input_bytes=max_input_bytes,
        on_started=on_started,
        operation_id=operation_id,
        output_limit=output_limit,
        owner=owner,
        process=process,
        process_hash=process_hash,
        reader_errors=reader_errors,
        readers=readers,
        retry=retry,
        start_observation=start_observation,
        telemetry=telemetry,
        timeout_seconds=timeout_seconds,
    )


def _write_ordinary_stdin(inputs: _OwnedProcessInputs, state: _OwnedProcessState) -> dict[str, Any] | None:
    """Keep the portable writer; its owner bounds waiting and reaps the thread."""
    process = _validated_cast(subprocess.Popen[Any], state.process)
    deadline = _validated_cast(float, state.deadline)
    failure = _CapturedFailure(BaseException)

    def write() -> None:
        with failure:
            _write_stdin(process, inputs.input_bytes)

    writer = threading.Thread(target=write, name="alk-process-stdin", daemon=True)
    state.readers.append(writer)
    writer.start()
    while writer.is_alive():
        cancelled = inputs.cancel_event is not None and inputs.cancel_event.is_set()
        remaining = deadline - time.monotonic()
        if cancelled or remaining <= 0:
            return {
                "status": "PARTIAL_OR_FAILED",
                "acceptedBytes": None,
                "acceptedSha256": None,
                "measurementStatus": "UNAVAILABLE",
                "expectedBytes": len(inputs.input_bytes),
                "closeSucceeded": False,
                "errorType": "cancelled" if cancelled else "timeout",
                "hostConsumptionProven": False,
            }
        writer.join(min(0.02, remaining))
    if failure.error is not None:
        raise failure.error
    # No callback requested OS-acceptance measurement on this ordinary route.
    return None


def _run_process_owned(
    *,
    absolute_deadline_monotonic_ns,
    adapter_id,
    argv,
    attempt_id,
    cancel_event,
    cleanup_grace_seconds,
    command_hash,
    cwd,
    deadline_ns,
    env,
    input_bytes,
    max_input_bytes,
    observer_lease,
    on_input,
    on_started,
    operation_id,
    output_limit,
    retry,
    started_ns,
    timeout_seconds,
):
    inputs = _OwnedProcessInputs(
        absolute_deadline_monotonic_ns=absolute_deadline_monotonic_ns,
        adapter_id=adapter_id,
        argv=argv,
        attempt_id=attempt_id,
        cancel_event=cancel_event,
        cleanup_grace_seconds=cleanup_grace_seconds,
        command_hash=command_hash,
        cwd=cwd,
        deadline_ns=deadline_ns,
        env=env,
        input_bytes=input_bytes,
        max_input_bytes=max_input_bytes,
        observer_lease=observer_lease,
        on_input=on_input,
        on_started=on_started,
        operation_id=operation_id,
        output_limit=output_limit,
        retry=retry,
        started_ns=started_ns,
        timeout_seconds=timeout_seconds,
    )
    state = _OwnedProcessState()
    try:
        result = _execute_started_owned_process(inputs, state)
        if observer_lease is not None and any(t.is_alive() for t in observer_lease.threads):
            result["observerDisposition"] = "MAY_STILL_RUN"
        if state.owner is not None:
            state.owner.close()
        return _record_process_clock(result, absolute_deadline_monotonic_ns, deadline_ns, started_ns)
    except BaseException as exc:
        if state.process is None:
            raise
        result = _exceptional_started_failure(
            state.process,
            state.owner,
            state.capture,
            state.readers,
            exc,
            cleanup_grace_seconds,
            deadline_ns,
            input_bytes,
            state.start_observation,
            state.input_observation,
            observer_lease,
            cancel_event,
        )
        if not isinstance(exc, Exception):
            raise
        return _record_process_clock(result, absolute_deadline_monotonic_ns, deadline_ns, started_ns)
    finally:
        if observer_lease is not None:
            observer_lease.process_finished()


_DEFAULT_OBSERVER_SLOTS = _ObserverSlots(8)


def run_process(
    argv: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: float,
    absolute_deadline_monotonic_ns: int | None = None,
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
    on_started: Callable[[dict[str, Any]], None] | None = None,
    on_input: Callable[[dict[str, Any]], None] | None = None,
    _observer_slots: _ObserverSlots = _DEFAULT_OBSERVER_SLOTS,
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
        timeout_seconds=timeout_seconds,
        cleanup_grace_seconds=cleanup_grace_seconds,
    )
    if invalid is not None:
        return invalid
    if (on_started is None) != (on_input is None):
        return _bounded_failure(
            "adapter-process-observation-incomplete",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={},
            command_hash=command_hash,
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            retry=retry,
        )
    if absolute_deadline_monotonic_ns is not None and (
        type(absolute_deadline_monotonic_ns) is not int or absolute_deadline_monotonic_ns <= 0
    ):
        return _bounded_failure(
            "adapter-process-absolute-deadline-invalid",
            input_bytes=len(input_bytes),
            output_bytes=0,
            process_started=False,
            details={},
            command_hash=command_hash,
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_id=adapter_id,
            retry=retry,
        )
    started_ns = time.monotonic_ns()
    deadline_ns = started_ns + int(max(0.01, timeout_seconds) * 1000000000)
    if absolute_deadline_monotonic_ns is not None:
        deadline_ns = min(deadline_ns, absolute_deadline_monotonic_ns)
    if absolute_deadline_monotonic_ns is not None and deadline_ns <= started_ns:
        return _record_process_clock(
            _process_deadline_failure(
                absolute_deadline_monotonic_ns,
                adapter_id,
                attempt_id,
                command_hash,
                input_bytes,
                operation_id,
                retry,
            ),
            absolute_deadline_monotonic_ns,
            deadline_ns,
            started_ns,
        )
    observer_lease: _ObserverLease | None = None
    if on_started is not None:
        observer_lease = _observer_slots.acquire(blocking=False)
        if observer_lease is None:
            return _bounded_failure(
                "adapter-process-observer-slots-exhausted",
                input_bytes=len(input_bytes),
                output_bytes=0,
                process_started=False,
                details={"observerSlotLimit": _observer_slots.limit},
                command_hash=command_hash,
                operation_id=operation_id,
                attempt_id=attempt_id,
                adapter_id=adapter_id,
                retry=retry,
            )
    return _run_process_owned(
        absolute_deadline_monotonic_ns=absolute_deadline_monotonic_ns,
        adapter_id=adapter_id,
        argv=argv,
        attempt_id=attempt_id,
        cancel_event=cancel_event,
        cleanup_grace_seconds=cleanup_grace_seconds,
        command_hash=command_hash,
        cwd=cwd,
        deadline_ns=deadline_ns,
        env=env,
        input_bytes=input_bytes,
        max_input_bytes=max_input_bytes,
        observer_lease=observer_lease,
        on_input=on_input,
        on_started=on_started,
        operation_id=operation_id,
        output_limit=output_limit,
        retry=retry,
        started_ns=started_ns,
        timeout_seconds=timeout_seconds,
    )


def _start_capture(
    process: subprocess.Popen[Any], capture: _CaptureState, readers: list[threading.Thread]
) -> list[BaseException]:
    """Retain each thread before start, including a partially failed two-reader start."""
    errors: list[BaseException] = []

    def read(name: str, stream: Any) -> None:
        _captured_failure_7 = _CapturedFailure(BaseException)
        with _captured_failure_7:
            capture._read_stream(name, stream)
        if _captured_failure_7.error is not None:
            exc = _captured_failure_7.error
            errors.append(exc)

    for name in ("stdout", "stderr"):
        reader = threading.Thread(
            target=read, args=(name, getattr(process, name)), name="alk-process-capture-" + name, daemon=True
        )
        readers.append(reader)
        reader.start()
    return errors


def _finish_capture(
    process: subprocess.Popen[Any], capture: _CaptureState, readers: list[threading.Thread], grace_seconds: float
) -> None:
    deadline = time.monotonic() + max(0.05, grace_seconds)
    for reader in readers:
        if reader.ident is not None:
            reader.join(max(0.0, deadline - time.monotonic()))
    if any(reader.is_alive() for reader in readers):
        raise RuntimeError("process capture threads did not terminate")
    capture.finish(process, readers, grace_seconds)


def _close_exceptional_process_streams(
    process: subprocess.Popen[Any], failures: list[dict[str, str]], cleanup: dict[str, Any], readers_done: bool
) -> bool:
    streams_closed = True
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(process, name, None)
        # Buffered close may wait for a live reader's I/O lock indefinitely.
        if (
            cleanup.get("directChildExited") is not True
            or cleanup.get("knownDescendantsGone") is not True
            or not readers_done
        ):
            streams_closed = False
            continue
        _captured_failure_3 = _CapturedFailure(BaseException)
        with _captured_failure_3:
            if stream is not None:
                stream.close()
        if _captured_failure_3.error is not None:
            exc = _captured_failure_3.error
            streams_closed = False
            failures.append({"stage": name + "-close", "errorType": type(exc).__name__})
    return streams_closed


def _exceptional_started_failure(
    process: subprocess.Popen[Any],
    owner: ProcessGroupOwner | None,
    capture: _CaptureState | None,
    readers: list[threading.Thread],
    error: BaseException,
    grace_seconds: float,
    deadline_ns: int,
    input_bytes: bytes,
    start_observation: dict[str, Any] | None,
    input_observation: dict[str, Any] | None,
    observer_lease: _ObserverLease | None,
    cancel_event: threading.Event | None,
) -> dict[str, Any]:
    """Independent error path: no retry of broken telemetry/capture/receipt builders."""
    _ = (capture,)
    grace = max(0.05, grace_seconds)
    failures: list[dict[str, str]] = []
    cleanup: dict[str, Any] = {
        "status": "BLOCKED",
        "attestation": "UNAVAILABLE",
        "knownDescendantsGone": False,
        "directChildExited": False,
    }
    if owner is not None:
        _captured_failure_6 = _CapturedFailure(BaseException)
        with _captured_failure_6:
            cleanup = owner.terminate(grace_seconds=grace)
        if _captured_failure_6.error is not None:
            exc = _captured_failure_6.error
            failures.append({"stage": "owner-terminate", "errorType": type(exc).__name__})
    if cleanup.get("status") != "PASS":
        _captured_failure_5 = _CapturedFailure(BaseException)
        with _captured_failure_5:
            if os.name == "posix":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=grace)
            gone = _wait_process_group_exit(process.pid, grace) if os.name == "posix" else False
            if os.name == "posix" and not gone:
                # The /proc helper is deliberately unavailable on macOS.
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    gone = True
            cleanup = {
                "status": "PASS" if gone else "BLOCKED",
                "attestation": "ATTESTED" if os.name == "posix" else "UNAVAILABLE",
                "knownDescendantsGone": gone,
                "directChildExited": process.poll() is not None,
                "mode": "posix-session" if os.name == "posix" else "windows-job-unavailable",
                "escalation": "exception-SIGKILL" if os.name == "posix" else "exception-kill",
            }
        if _captured_failure_5.error is not None:
            exc = _captured_failure_5.error
            failures.append({"stage": "emergency-terminate", "errorType": type(exc).__name__})
            cleanup["status"] = "BLOCKED"
    join_deadline = time.monotonic() + grace
    for reader in readers:
        _captured_failure_4 = _CapturedFailure(BaseException)
        with _captured_failure_4:
            if reader.ident is not None:
                reader.join(max(0.0, join_deadline - time.monotonic()))
        if _captured_failure_4.error is not None:
            exc = _captured_failure_4.error
            failures.append({"stage": "capture-join", "errorType": type(exc).__name__})
    readers_done = all(not reader.is_alive() for reader in readers)
    streams_closed = _close_exceptional_process_streams(process, failures, cleanup, readers_done)
    owner_closed = True
    if owner is not None:
        _captured_failure_2 = _CapturedFailure(BaseException)
        with _captured_failure_2:
            owner.close()
        if _captured_failure_2.error is not None:
            exc = _captured_failure_2.error
            owner_closed = False
            failures.append({"stage": "owner-close", "errorType": type(exc).__name__})
    cleanup = {
        **cleanup,
        "readersTerminated": readers_done,
        "streamsClosed": streams_closed,
        "ownerClosed": owner_closed,
    }
    if not (readers_done and streams_closed and owner_closed):
        cleanup["status"] = "BLOCKED"
    public_start = None
    _captured_failure_1 = _CapturedFailure(BaseException)
    with _captured_failure_1:
        if start_observation is not None:
            public_start = _public_start_observation(start_observation)
    if _captured_failure_1.error is not None:
        exc = _captured_failure_1.error
        failures.append({"stage": "start-observation-projection", "errorType": type(exc).__name__})
    cancelled = False
    _captured_failure_0 = _CapturedFailure(BaseException)
    with _captured_failure_0:
        cancelled = cancel_event.is_set() if cancel_event is not None else False
    if _captured_failure_0.error is not None:
        exc = _captured_failure_0.error
        failures.append({"stage": "cancellation-observation", "errorType": type(exc).__name__})
    return {
        "status": "FAIL" if cleanup.get("status") == "PASS" else "BLOCKED",
        "processStarted": True,
        "startedFailure": True,
        "processReceipt": None,
        "exitCode": process.returncode,
        "timedOut": time.monotonic_ns() >= deadline_ns,
        "cancelled": cancelled,
        "inputBytes": len(input_bytes),
        "outputBytes": None,
        "outputLimitExceeded": False,
        "stdout": "",
        "stderr": "",
        "stdoutTail": "",
        "stderrTail": "",
        "stdoutRedacted": False,
        "stderrRedacted": False,
        "cleanup": cleanup,
        "deadlineMonotonicNs": deadline_ns,
        "startObservation": public_start,
        "inputObservation": input_observation,
        "observerDisposition": (
            "MAY_STILL_RUN"
            if observer_lease is not None and any(t.is_alive() for t in observer_lease.threads)
            else "COMPLETED_OR_NOT_STARTED"
        ),
        "costStatus": "UNAVAILABLE",
        "retryAuthorized": False,
        "blockers": [
            {
                "code": "adapter-process-after-start-exception",
                "errorType": type(error).__name__,
                "costStatus": "UNAVAILABLE",
                "cleanupFailures": failures,
            }
        ],
    }


def _write_observed_stdin(
    process: subprocess.Popen[Any],
    data: bytes,
    timeout_seconds: float,
    started_at_monotonic: float,
    cancel_event: threading.Event | None,
    operation_id: str | None,
    attempt_id: str | None,
    adapter_id: str | None,
    process_hash: str,
    *,
    deadline_monotonic_ns: int | None = None,
) -> dict[str, Any]:
    """Measure bytes accepted by the OS pipe; this is not host consumption."""
    accepted = hashlib.sha256()
    count = 0
    error: str | None = None
    close_ok = False
    deadline = started_at_monotonic + max(0.01, timeout_seconds)
    if deadline_monotonic_ns is not None:
        deadline = min(deadline, deadline_monotonic_ns / 1_000_000_000)
    stream = process.stdin
    if stream is None:
        error = "stdin-unavailable"
    else:
        try:
            fd = stream.fileno()
            if os.name == "nt":
                from .windows_pipe import configure_pipe

                configure_pipe(fd)
            else:
                os.set_blocking(fd, False)
            while count < len(data):
                if cancel_event is not None and cancel_event.is_set():
                    error = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    error = "timeout"
                    break
                if (
                    os.name != "nt"
                    and not select.select([], [fd], [], min(0.02, max(0.0, deadline - time.monotonic())))[1]
                ):
                    continue
                try:
                    if os.name == "nt":
                        from .windows_pipe import write_pipe

                        written = write_pipe(fd, data[count : count + 8192])
                    else:
                        written = os.write(fd, data[count : count + 8192])
                except BlockingIOError:
                    if os.name == "nt":
                        time.sleep(min(0.002, max(0.0, deadline - time.monotonic())))
                    continue
                if written <= 0:
                    error = "short-write"
                    break
                accepted.update(data[count : count + written])
                count += written
        except (BrokenPipeError, OSError, ValueError) as exc:
            error = type(exc).__name__
        try:
            stream.close()
            close_ok = True
        except OSError as exc:
            error = error or type(exc).__name__
    return {
        "status": "COMPLETE" if count == len(data) and close_ok and error is None else "PARTIAL_OR_FAILED",
        "acceptedBytes": count,
        "acceptedSha256": accepted.hexdigest(),
        "expectedBytes": len(data),
        "closeSucceeded": close_ok,
        "errorType": error,
        "processIdentityHash": process_hash,
        "operationId": operation_id,
        "attemptId": attempt_id,
        "adapterId": adapter_id,
        "hostConsumptionProven": False,
    }


def _observed_failure(
    process: subprocess.Popen[Any],
    owner: ProcessGroupOwner,
    capture: _CaptureState,
    telemetry: ProcessTelemetry,
    command_hash: str,
    process_hash: str,
    group_hash: str,
    input_bytes: bytes,
    output_limit: int,
    timeout_seconds: float,
    cleanup_grace_seconds: float,
    operation_id: str | None,
    attempt_id: str | None,
    adapter_id: str | None,
    retry: dict[str, Any] | None,
    code: str,
    error: BaseException | None,
    start_observation: dict[str, Any] | None,
    input_observation: dict[str, Any] | None,
    readers: list[threading.Thread] | None = None,
    *,
    timed_out: bool = False,
) -> dict[str, Any]:
    if readers is None:
        readers = []
    if not readers:
        _start_capture(process, capture, readers)
    # A portable writer may hold buffered stdin's I/O lock. Terminate first,
    # then join all owned I/O threads before closing any remaining stream.
    cleanup = owner.terminate(grace_seconds=max(0.05, cleanup_grace_seconds))
    _finish_capture(process, capture, readers, cleanup_grace_seconds)
    if process.stdin is not None and not process.stdin.closed:
        with contextlib.suppress(OSError):
            process.stdin.close()
    result = _build_process_result(
        process,
        capture=capture,
        telemetry_values=telemetry.finish(),
        cleanup=cleanup,
        timed_out=timed_out or (input_observation or {}).get("errorType") == "timeout",
        cancelled=(input_observation or {}).get("errorType") == "cancelled",
        timeout_seconds=timeout_seconds,
        output_limit=output_limit,
        max_input_bytes=None,
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
    result["status"] = "FAIL" if cleanup.get("status") == "PASS" else "BLOCKED"
    result["processReceipt"] = None
    result["blockers"].append(
        {"code": code, "errorType": type(error).__name__ if error else None, "costStatus": "UNAVAILABLE"}
    )
    result["startObservation"] = _public_start_observation(start_observation) if start_observation else None
    result["inputObservation"] = input_observation
    result["startedFailure"] = True
    result["deadlineMonotonicNs"] = telemetry.started_ns + int(max(0.01, timeout_seconds) * 1_000_000_000)
    result["observerDisposition"] = "MAY_STILL_RUN" if timed_out else "COMPLETED_OR_NOT_STARTED"
    return result


def _public_start_observation(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "processIdentityHash",
            "groupIdentityHash",
            "commandIdentityHash",
            "plannedStdinBytes",
            "plannedStdinSha256",
            "stdinStatus",
            "operationId",
            "attemptId",
            "adapterId",
        )
    }


def _process_identity_hash(pid: int, started_ns: int) -> str:
    from agent_lifecycle.contracts.process_execution_schemas import process_identity_hash

    return process_identity_hash(pid=pid, started_ns=started_ns)
