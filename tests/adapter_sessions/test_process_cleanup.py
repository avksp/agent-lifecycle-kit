from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from agent_lifecycle.adapter_sessions import process as process_module
from agent_lifecycle.adapter_sessions.process import ProcessTelemetry, run_process
from agent_lifecycle.contracts import canonical_digest


class ProcessCleanupTests(unittest.TestCase):
    @staticmethod
    def _write_operation() -> str:
        if os.name == "nt":
            return "agent_lifecycle.adapter_sessions.windows_pipe.write_pipe"
        return "agent_lifecycle.adapter_sessions.process.os.write"

    def test_popen_failure_has_no_start_or_input_observation(self) -> None:
        events: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            result = run_process(
                [str(Path(temporary) / "missing-executable")],
                env=dict(os.environ), timeout_seconds=5, stdin_text="private",
                on_started=lambda _event: events.append("start"),
                on_input=lambda _event: events.append("input"),
            )
        self.assertFalse(result["processStarted"])
        self.assertEqual(events, [])
        self.assertEqual(result["blockers"][0]["code"], "adapter-process-start-failed")
        self.assertIsNone(result.get("startObservation"))
        self.assertIsNone(result.get("inputObservation"))

    def test_observed_start_precedes_complete_stdin_receipt(self) -> None:
        events: list[tuple[str, dict]] = []
        child_env = dict(os.environ)
        argv = [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"]
        result = run_process(
            argv, env=child_env, timeout_seconds=5, stdin_text="exact prompt",
            on_started=lambda event: events.append(("start", event)),
            on_input=lambda event: events.append(("input", event)),
        )
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual([name for name, _ in events], ["start", "input"])
        self.assertEqual(events[0][1]["stdinStatus"], "PENDING")
        self.assertEqual(events[0][1]["argv"], argv)
        self.assertEqual(events[0][1]["environmentSha256"], canonical_digest(child_env))
        self.assertEqual(events[1][1]["status"], "COMPLETE")
        self.assertEqual(events[1][1]["acceptedBytes"], len(b"exact prompt"))
        self.assertFalse(events[1][1]["hostConsumptionProven"])

    def test_start_observer_time_consumes_stdin_deadline(self) -> None:
        inputs: list[dict] = []

        def slow_start(_event: dict) -> None:
            time.sleep(0.12)

        result = run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=dict(os.environ), timeout_seconds=0.05, stdin_text="private",
            on_started=slow_start, on_input=inputs.append,
        )
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertEqual(inputs, [])
        self.assertTrue(result["timedOut"])
        self.assertFalse(result["cancelled"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["blockers"][-1]["code"], "adapter-process-start-observation-timeout")

    @unittest.skipUnless(os.name == "posix", "process-group fixture uses POSIX sessions")
    def test_r69h_blocked_start_observer_cannot_hold_child_past_deadline(self) -> None:
        release = threading.Event()
        entered = threading.Event()

        def block_start(_event: dict) -> None:
            entered.set()
            release.wait(5)

        try:
            began = time.monotonic()
            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=0.1, cleanup_grace_seconds=0.2,
                stdin_text="private",
                on_started=block_start, on_input=lambda _event: None,
            )
            self.assertTrue(entered.is_set())
            self.assertLess(time.monotonic() - began, 1.5)
            self.assertTrue(result["timedOut"])
            self.assertTrue(result["startedFailure"])
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["cleanup"]["status"], "PASS")
            self.assertEqual(result["blockers"][-1]["code"], "adapter-process-start-observation-timeout")
            self.assertIsNone(result["inputObservation"])
        finally:
            release.set()

    @unittest.skipUnless(os.name == "posix", "process-group fixture uses POSIX sessions")
    def test_r11_observer_slot_exhaustion_refuses_before_popen(self) -> None:
        slots = process_module._ObserverSlots(8)
        release = threading.Event()
        entered = threading.Event()

        def block_start(_event: dict) -> None:
            entered.set()
            release.wait()

        try:
            for _ in range(8):
                first = run_process(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    env=dict(os.environ), timeout_seconds=0.1,
                    cleanup_grace_seconds=0.2, stdin_text="private",
                    on_started=block_start, on_input=lambda _event: None,
                    _observer_slots=slots,
                )
                self.assertTrue(first["startedFailure"])
                self.assertTrue(first["timedOut"])
            self.assertTrue(entered.is_set())
            self.assertTrue(first["startedFailure"])
            self.assertTrue(first["timedOut"])
            with patch.object(process_module.subprocess, "Popen",
                              side_effect=AssertionError("must refuse before Popen")):
                second = run_process(
                        [sys.executable, "-c", "pass"],
                        env=dict(os.environ), timeout_seconds=5,
                        stdin_text="private", on_started=lambda _event: None,
                        on_input=lambda _event: None,
                        _observer_slots=slots,
                    )
            self.assertFalse(second["processStarted"])
            self.assertEqual(second["blockers"][0]["code"],
                             "adapter-process-observer-slots-exhausted")
        finally:
            release.set()
            for lease in list(slots._leases):
                for thread in lease.threads:
                    thread.join(1)
        deadline = time.monotonic() + 1
        lease = slots.acquire(blocking=False)
        while lease is None and time.monotonic() < deadline:
            time.sleep(0.01)
            lease = slots.acquire(blocking=False)
        self.assertIsNotNone(lease, "observer slot was not released")
        lease.process_finished()

    @unittest.skipUnless(os.name == "posix", "process-group fixture uses POSIX sessions")
    def test_r11_thread_start_failure_after_popen_keeps_started_cost(self) -> None:
        slots = process_module._ObserverSlots(1)
        real_start = Thread.start

        def fail_observer_start(thread: threading.Thread) -> None:
            if thread.name == "alk-process-observer":
                raise RuntimeError("observer thread unavailable")
            real_start(thread)

        with patch.object(threading.Thread, "start", fail_observer_start):
            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=5,
                cleanup_grace_seconds=0.2, stdin_text="private",
                on_started=lambda _event: None, on_input=lambda _event: None,
                _observer_slots=slots,
            )
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["blockers"][-1]["code"],
                         "adapter-process-start-observation-failed")
        self.assertEqual(result["blockers"][-1]["costStatus"], "UNAVAILABLE")
        lease = slots.acquire(blocking=False)
        self.assertIsNotNone(lease, "observer slot was not released")
        lease.process_finished()
        self._check_after_popen_exceptions()
        self._check_ambiguous_observer_thread_start()
        self._check_exception_group_fallback_and_interrupt()

    def _check_ambiguous_observer_thread_start(self) -> None:
        slots = process_module._ObserverSlots(1)
        release = threading.Event()
        entered = threading.Event()
        real_start = Thread.start
        threads = []
        def start_then_raise(thread):
            real_start(thread)
            if thread.name == 'alk-process-observer':
                threads.append(thread)
                self.assertTrue(entered.wait(1))
                raise RuntimeError('start raised after actually starting')
        def observe(_event):
            entered.set()
            release.wait()
        try:
            with patch.object(Thread, 'start', start_then_raise):
                result = run_process([sys.executable, '-c', 'import time;time.sleep(30)'],
                    env=dict(os.environ), timeout_seconds=1, cleanup_grace_seconds=0.15,
                    on_started=observe, on_input=lambda _event: None, _observer_slots=slots)
            self.assertTrue(result['processStarted'])
            self.assertEqual(result['observerDisposition'], 'MAY_STILL_RUN')
            self.assertEqual(result['cleanup']['status'], 'PASS')
            self.assertIsNone(slots.acquire())
        finally:
            release.set()
            for thread in threads:
                thread.join(1)
        lease = slots.acquire()
        self.assertIsNotNone(lease)
        lease.process_finished()

    def _check_exception_group_fallback_and_interrupt(self) -> None:
        real_popen = subprocess.Popen
        for stage in ('owner-init-descendant', 'interrupt', 'cleanup-refused'):
            with self.subTest(exceptionBoundary=stage), tempfile.TemporaryDirectory() as temporary:
                marker = Path(temporary) / 'descendant'
                command = 'import time;time.sleep(30)'
                if stage == 'owner-init-descendant':
                    command = ('import subprocess,sys,time,pathlib;'
                               'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);'
                               f'pathlib.Path({str(marker)!r}).write_text(str(child.pid));time.sleep(30)')
                children = []
                def popen(argv, **kwargs):
                    child = real_popen(argv, **kwargs)
                    if argv[:2] == [sys.executable, '-c']:
                        children.append(child)
                        if stage == 'owner-init-descendant':
                            deadline = time.monotonic() + 2
                            while (not marker.exists() or marker.stat().st_size == 0) and time.monotonic() < deadline:
                                time.sleep(0.01)
                    return child
                try:
                    from contextlib import ExitStack
                    with ExitStack() as stack:
                        stack.enter_context(patch.object(process_module.subprocess, 'Popen', side_effect=popen))
                        if stage == 'interrupt':
                            stack.enter_context(patch.object(process_module, '_write_observed_stdin', side_effect=KeyboardInterrupt))
                        else:
                            stack.enter_context(patch.object(process_module, 'ProcessGroupOwner', side_effect=RuntimeError('owner')))
                        if stage == 'cleanup-refused':
                            stack.enter_context(patch.object(process_module.os, 'killpg', side_effect=PermissionError))
                        if stage == 'interrupt':
                            with self.assertRaises(KeyboardInterrupt):
                                run_process([sys.executable, '-c', command], env=dict(os.environ),
                                    timeout_seconds=1, cleanup_grace_seconds=0.15,
                                    on_started=lambda _event: None, on_input=lambda _event: None)
                        else:
                            result = run_process([sys.executable, '-c', command], env=dict(os.environ),
                                timeout_seconds=1, cleanup_grace_seconds=0.15)
                            self.assertTrue(result['processStarted'])
                            self.assertEqual(result['costStatus'], 'UNAVAILABLE')
                            self.assertFalse(result['retryAuthorized'])
                            self.assertEqual(result['cleanup']['status'], 'BLOCKED' if stage == 'cleanup-refused' else 'PASS')
                            if stage == 'cleanup-refused':
                                self.assertFalse(result['cleanup']['streamsClosed'])
                    self.assertEqual(len(children), 1)
                    if stage != 'cleanup-refused':
                        self.assertIsNotNone(children[0].poll())
                        self.assertTrue(all(s.closed for s in (children[0].stdin, children[0].stdout, children[0].stderr)))
                    if stage == 'owner-init-descendant':
                        self.assertTrue(marker.exists())
                        pid = int(marker.read_text())
                        probe = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
                        self.assertTrue(not probe.stdout.strip() or probe.stdout.strip().startswith('Z'))
                finally:
                    for child in children:
                        if child.poll() is None:
                            os.killpg(child.pid, 9)
                        child.wait(timeout=2)
                        for stream in (child.stdin, child.stdout, child.stderr):
                            stream.close()

    def _check_after_popen_exceptions(self) -> None:
        real_popen = subprocess.Popen
        real_sample = ProcessTelemetry.sample
        real_thread_start = Thread.start

        def sample_after_init(telemetry, **kwargs):
            if kwargs.get('force_group'):
                return real_sample(telemetry, **kwargs)
            raise RuntimeError('sample fault')

        def fail_second_reader(thread):
            if thread.name == 'alk-process-capture-stderr':
                raise RuntimeError('second capture start fault')
            return real_thread_start(thread)

        faults = {
            'owner-init': lambda: patch.object(process_module, 'ProcessGroupOwner', side_effect=RuntimeError('owner')),
            'telemetry-init': lambda: patch.object(process_module, 'ProcessTelemetry', side_effect=RuntimeError('telemetry')),
            'capture-init': lambda: patch.object(process_module, '_CaptureState', side_effect=RuntimeError('capture')),
            'second-reader-start': lambda: patch.object(Thread, 'start', fail_second_reader),
            'reader-body': lambda: patch.object(process_module._CaptureState, '_read_stream', side_effect=RuntimeError('reader')),
            'stdin': lambda: patch.object(process_module, '_write_observed_stdin', side_effect=RuntimeError('stdin')),
            'telemetry-sample': lambda: patch.object(ProcessTelemetry, 'sample', sample_after_init),
            'telemetry-finish': lambda: patch.object(ProcessTelemetry, 'finish', side_effect=RuntimeError('finish')),
            'capture-finish': lambda: patch.object(process_module._CaptureState, 'finish', side_effect=RuntimeError('finish')),
            'receipt-build': lambda: patch.object(process_module, '_build_process_result', side_effect=RuntimeError('receipt')),
            'owner-terminate': lambda: patch.object(process_module.ProcessGroupOwner, 'terminate', side_effect=RuntimeError('terminate')),
            'owner-close': lambda: patch.object(process_module.ProcessGroupOwner, 'close', side_effect=RuntimeError('close')),
            'projection': lambda: patch.object(process_module, '_public_start_observation', side_effect=RuntimeError('projection')),
        }
        for stage, fault in faults.items():
            with self.subTest(afterPopenStage=stage):
                children = []
                def popen(argv, **kwargs):
                    child = real_popen(argv, **kwargs)
                    if argv[:2] == [sys.executable, '-c']:
                        children.append(child)
                    return child
                began = time.monotonic()
                with patch.object(process_module.subprocess, 'Popen', side_effect=popen), fault():
                    result = run_process([sys.executable, '-c', 'import time; time.sleep(30)'],
                        env=dict(os.environ), timeout_seconds=0.12, cleanup_grace_seconds=0.15,
                        stdin_text='private', on_started=lambda _event: None, on_input=lambda _event: None)
                self.assertLess(time.monotonic() - began, 3)
                self.assertEqual(len(children), 1)
                child = children[0]
                self.assertIsNotNone(child.poll())
                self.assertTrue(all(stream.closed for stream in (child.stdin, child.stdout, child.stderr)))
                with self.assertRaises(ProcessLookupError):
                    os.killpg(child.pid, 0)
                self.assertTrue(result['processStarted'])
                self.assertTrue(result['startedFailure'])
                self.assertIsNone(result['processReceipt'])
                self.assertEqual(result['costStatus'], 'UNAVAILABLE')
                self.assertFalse(result['retryAuthorized'])
                self.assertEqual(result['blockers'][0]['code'], 'adapter-process-after-start-exception')
                self.assertEqual(result['cleanup']['status'], 'BLOCKED' if stage == 'owner-close' else 'PASS')

    @unittest.skipUnless(os.name == "posix", "process-group fixture uses POSIX sessions")
    def test_r11_late_input_observer_after_absolute_deadline_denied_on_zero_child(self) -> None:
        self._check_original_absolute_process_deadline()
        slots = process_module._ObserverSlots(1)
        returned = threading.Event()
        tail_entered = threading.Event()
        release = threading.Event()
        threads = []
        real_run = Thread.run

        def tail_after_callback(thread):
            real_run(thread)
            if thread.name == 'alk-process-observer' and returned.is_set():
                threads.append(thread)
                tail_entered.set()
                release.wait()

        try:
            with patch.object(Thread, 'run', tail_after_callback):
                result = run_process([sys.executable, '-c', 'import sys; sys.stdin.buffer.read()'],
                    env=dict(os.environ), timeout_seconds=0.2, cleanup_grace_seconds=0.15,
                    stdin_text='private', on_started=lambda _event: None,
                    on_input=lambda _event: returned.set(), _observer_slots=slots)
                self.assertTrue(tail_entered.is_set())
                self.assertTrue(returned.is_set())
                self.assertTrue(threads[0].is_alive())
                self.assertEqual(result['exitCode'], 0)
                self.assertTrue(result['timedOut'])
                self.assertTrue(result['startedFailure'])
                self.assertEqual(result['cleanup']['status'], 'PASS')
                self.assertEqual(result['observerDisposition'], 'MAY_STILL_RUN')
                self.assertEqual(result['blockers'][-1]['costStatus'], 'UNAVAILABLE')
                with patch.object(process_module.subprocess, 'Popen', side_effect=AssertionError('no slot')):
                    refused = run_process([sys.executable, '-c', 'pass'], env=dict(os.environ),
                        timeout_seconds=1, on_started=lambda _event: None,
                        on_input=lambda _event: None, _observer_slots=slots)
                self.assertFalse(refused['processStarted'])
        finally:
            release.set()
            for thread in threads:
                thread.join(1)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        lease = slots.acquire()
        self.assertIsNotNone(lease)
        lease.process_finished()
        self._check_delayed_observer_thread_start_keeps_original_deadline()

    @unittest.skipUnless(os.name == "posix", "process-group fixture uses POSIX sessions")
    def _check_delayed_observer_thread_start_keeps_original_deadline(self) -> None:
        slots = process_module._ObserverSlots(1)
        entered = threading.Event()
        release = threading.Event()
        callback_ran = threading.Event()
        entered_at: list[float] = []
        real_start = Thread.start

        def delayed_start(thread: threading.Thread) -> None:
            if thread.name == "alk-process-observer":
                entered_at.append(time.monotonic())
                entered.set()
                release.wait(2)
            real_start(thread)

        def release_after_deadline() -> None:
            if entered.wait(2):
                while time.monotonic() < entered_at[0] + 0.1:
                    time.sleep(0.001)
            release.set()

        driver = Thread(target=release_after_deadline)
        driver.start()
        try:
            with patch.object(Thread, "start", delayed_start):
                result = run_process(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    env=dict(os.environ), timeout_seconds=0.05,
                    cleanup_grace_seconds=0.2, stdin_text="private",
                    on_started=lambda _event: callback_ran.set(),
                    on_input=lambda _event: None, _observer_slots=slots,
                )
        finally:
            release.set()
            driver.join(2)
        self.assertTrue(entered.is_set())
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertTrue(result["timedOut"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["blockers"][-1]["code"],
                         "adapter-process-start-observation-timeout")
        self.assertEqual(result["blockers"][-1]["costStatus"], "UNAVAILABLE")
        self.assertTrue(callback_ran.wait(1))
        lease = slots.acquire(blocking=False)
        self.assertIsNotNone(lease)
        lease.process_finished()

    def test_r69h_blocked_input_observer_preserves_timeout_after_child_exit(self) -> None:
        release = threading.Event()
        entered = threading.Event()

        def block_input(_event: dict) -> None:
            entered.set()
            release.wait(5)

        try:
            began = time.monotonic()
            result = run_process(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                env=dict(os.environ), timeout_seconds=0.2, cleanup_grace_seconds=0.2,
                stdin_text="private",
                on_started=lambda _event: None, on_input=block_input,
            )
            self.assertTrue(entered.is_set())
            self.assertLess(time.monotonic() - began, 1.5)
            self.assertTrue(result["timedOut"])
            self.assertTrue(result["startedFailure"])
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["cleanup"]["status"], "PASS")
            self.assertEqual(result["blockers"][-1]["code"], "adapter-process-input-observation-timeout")
            self.assertEqual(result["inputObservation"]["status"], "COMPLETE")
            self.assertEqual(result["exitCode"], 0)
        finally:
            release.set()

    def test_r69h_input_cancellation_keeps_failure_cause(self) -> None:
        cancelled = threading.Event()
        inputs: list[dict] = []

        def cancel_at_start(_event: dict) -> None:
            cancelled.set()

        result = run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=dict(os.environ), timeout_seconds=5, stdin_text="private",
            cancel_event=cancelled, on_started=cancel_at_start, on_input=inputs.append,
        )
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertTrue(result["cancelled"])
        self.assertFalse(result["timedOut"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(inputs[0]["errorType"], "cancelled")

    @unittest.skipUnless(os.name == "posix", "Injects the POSIX select syscall failure")
    def test_r69h_select_value_error_cleans_started_child(self) -> None:
        inputs: list[dict] = []
        with patch("agent_lifecycle.adapter_sessions.process.select.select",
                   side_effect=ValueError("descriptor out of range")):
            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=5, stdin_text="private",
                on_started=lambda _event: None, on_input=inputs.append,
            )
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(inputs[0]["status"], "PARTIAL_OR_FAILED")
        self.assertEqual(inputs[0]["errorType"], "ValueError")

    def test_start_observation_failure_is_started_failure(self) -> None:
        collectors: list[ProcessTelemetry] = []

        def track_telemetry(*, pid: int, group_id: int | None) -> ProcessTelemetry:
            collector = ProcessTelemetry(pid=pid, group_id=group_id)
            collectors.append(collector)
            return collector

        def fail(_event: dict) -> None:
            raise OSError("receipt unavailable")

        with patch("agent_lifecycle.adapter_sessions.process.ProcessTelemetry",
                   side_effect=track_telemetry):
            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=5, stdin_text="private",
                on_started=fail, on_input=lambda _event: None,
            )
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["processReceipt"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(len(collectors), 1)
        self.assertGreaterEqual(collectors[0]._sample_count, 2)

    def test_broken_pipe_retains_partial_input_and_started_cost(self) -> None:
        events: list[dict] = []
        with patch(self._write_operation(), side_effect=BrokenPipeError):
            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=5, stdin_text="private",
                on_started=lambda _event: None, on_input=events.append,
            )
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertEqual(events[0]["status"], "PARTIAL_OR_FAILED")
        self.assertEqual(events[0]["acceptedBytes"], 0)
        self.assertEqual(result["blockers"][-1]["costStatus"], "UNAVAILABLE")

    def test_stdin_close_error_after_full_write_is_started_failure(self) -> None:
        real_popen = subprocess.Popen

        class CloseErrorStream:
            def __init__(self, stream: object) -> None:
                self.stream = stream

            def fileno(self) -> int:
                return self.stream.fileno()

            @property
            def closed(self) -> bool:
                return self.stream.closed

            def close(self) -> None:
                self.stream.close()
                raise OSError("simulated close failure after OS close")

        def popen_with_close_error(*args: object, **kwargs: object) -> subprocess.Popen:
            process = real_popen(*args, **kwargs)
            process.stdin = CloseErrorStream(process.stdin)
            return process

        events: list[dict] = []
        with patch("agent_lifecycle.adapter_sessions.process.subprocess.Popen",
                   side_effect=popen_with_close_error):
            result = run_process(
                [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                env=dict(os.environ), timeout_seconds=5, stdin_text="private",
                on_started=lambda _event: None, on_input=events.append,
            )
        self.assertTrue(result["processStarted"])
        self.assertTrue(result["startedFailure"])
        self.assertEqual(events[0]["acceptedBytes"], len(b"private"))
        self.assertFalse(events[0]["closeSucceeded"])
        self.assertEqual(events[0]["status"], "PARTIAL_OR_FAILED")
        self.assertEqual(result["blockers"][-1]["costStatus"], "UNAVAILABLE")

    def test_short_write_and_input_receipt_failure_remain_started(self) -> None:
        with patch(self._write_operation(), return_value=0):
            short = run_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                env=dict(os.environ), timeout_seconds=5, stdin_text="private",
                on_started=lambda _event: None, on_input=lambda _event: None,
            )
        self.assertTrue(short["processStarted"])
        self.assertTrue(short["startedFailure"])
        self.assertEqual(short["inputObservation"]["status"], "PARTIAL_OR_FAILED")
        self.assertEqual(short["inputObservation"]["errorType"], "short-write")
        self.assertEqual(short["blockers"][-1]["costStatus"], "UNAVAILABLE")

        def fail_receipt(_event: dict) -> None:
            raise OSError("input receipt unavailable")

        lost = run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env=dict(os.environ), timeout_seconds=5, stdin_text="private",
            on_started=lambda _event: None, on_input=fail_receipt,
        )
        self.assertTrue(lost["processStarted"])
        self.assertTrue(lost["startedFailure"])
        self.assertEqual(lost["inputObservation"]["status"], "COMPLETE")
        self.assertEqual(lost["blockers"][-1]["code"], "adapter-process-input-observation-failed")
        self.assertEqual(lost["blockers"][-1]["costStatus"], "UNAVAILABLE")

    @unittest.skipUnless(os.name == "posix", "process-group fixture uses POSIX sessions")
    def test_timeout_terminates_descendant_group(self) -> None:
        script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(30)"

        result = run_process(
            [sys.executable, "-c", script],
            env=dict(os.environ),
            timeout_seconds=0.1,
            cleanup_grace_seconds=0.5,
            operation_id="cleanup-op",
            attempt_id="cleanup-attempt",
            adapter_id="fixture",
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["timedOut"])
        self.assertEqual(result["cleanup"]["status"], "PASS")
        self.assertEqual(result["blockers"][0]["code"], "adapter-process-timeout")

    def test_normal_exit_has_cleanup_receipt(self) -> None:
        result = run_process(
            [sys.executable, "-c", "pass"],
            env=dict(os.environ),
            timeout_seconds=5,
            operation_id="normal-op",
            attempt_id="normal-attempt",
            adapter_id="fixture",
        )

        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["processReceipt"]["cleanup"]["status"], "PASS")

    def _check_original_absolute_process_deadline(self):
        from agent_lifecycle.contracts.process_execution_schemas import process_identity_hash
        options={'env':dict(os.environ),'timeout_seconds':10,'cleanup_grace_seconds':0.1,
                 'operation_id':'absolute-fixture','attempt_id':'attempt','adapter_id':'fixture'}
        sleeping=[sys.executable,'-c','import time; time.sleep(5)']
        for deadline in (True,0,-1,1.5,'invalid'):
            with self.subTest(absoluteProcess='invalid-deadline',value=deadline),patch.object(process_module.subprocess,'Popen') as popen:
                result=run_process(sleeping,**options,absolute_deadline_monotonic_ns=deadline)
                self.assertFalse(result['processStarted']);popen.assert_not_called()
        with self.subTest(absoluteProcess='expired-before-spawn'),patch.object(process_module.subprocess,'Popen') as popen:
            result=run_process(sleeping,**options,absolute_deadline_monotonic_ns=time.monotonic_ns()-1)
            self.assertFalse(result['processStarted']);popen.assert_not_called()
        with self.subTest(absoluteProcess='expires-during-admission-no-spawn'), \
             patch.object(process_module.time,'monotonic_ns',side_effect=[100,201]),patch.object(process_module.subprocess,'Popen') as popen:
            result=run_process(sleeping,**options,absolute_deadline_monotonic_ns=200)
            self.assertFalse(result['processStarted']);popen.assert_not_called()
        with self.subTest(absoluteProcess='success-start-identity-is-independent-of-shortened-deadline'):
            observations=[];deadline=time.monotonic_ns()+3_000_000_000
            result=run_process([sys.executable,'-c','print("done")'],**options,absolute_deadline_monotonic_ns=deadline,
                on_started=observations.append,on_input=lambda _:None)
            self.assertEqual(result['status'],'PASS');self.assertEqual(result['absoluteDeadlineMonotonicNs'],deadline)
            self.assertEqual(result['deadlineMonotonicNs'],deadline);self.assertLess(result['startedMonotonicNs'],deadline)
            self.assertEqual(result['processReceipt']['processIdentityHash'],process_identity_hash(pid=observations[0]['pid'],started_ns=result['startedMonotonicNs']))
            self.assertNotEqual(result['startedMonotonicNs'],result['deadlineMonotonicNs']-10_000_000_000)
        for mode in ('absolute-shorter','relative-shorter'):
            with self.subTest(absoluteProcess=mode):
                deadline=time.monotonic_ns()+(200_000_000 if mode=='absolute-shorter' else 30_000_000_000)
                timeout=10 if mode=='absolute-shorter' else 0.2;started=time.monotonic()
                result=run_process(sleeping,**{**options,'timeout_seconds':timeout},absolute_deadline_monotonic_ns=deadline)
                self.assertTrue(result['timedOut']);self.assertNotEqual(result['status'],'PASS')
                self.assertEqual(result['deadlineMonotonicNs'],min(deadline,result['startedMonotonicNs']+int(timeout*1_000_000_000)))
                self.assertEqual(result['cleanup']['status'],'PASS');self.assertLess(time.monotonic()-started,3)
        with self.subTest(absoluteProcess='blocked-start-callback-cannot-reset-original-deadline'):
            release=threading.Event();entered=threading.Event();done=threading.Event()
            def observer(_):
                entered.set()
                try:release.wait(3)
                finally:done.set()
            deadline=time.monotonic_ns()+200_000_000;started=time.monotonic()
            try:
                result=run_process(sleeping,**options,absolute_deadline_monotonic_ns=deadline,on_started=observer,on_input=lambda _:None)
                self.assertTrue(entered.is_set());self.assertTrue(result['timedOut']);self.assertEqual(result['deadlineMonotonicNs'],deadline)
                self.assertEqual(result['observerDisposition'],'MAY_STILL_RUN');self.assertLess(time.monotonic()-started,3)
                self.assertEqual(result['cleanup']['status'],'PASS')
            finally:release.set();self.assertTrue(done.wait(2))
        with self.subTest(absoluteProcess='unobserved-stdin-write-is-bounded'):
            deadline=time.monotonic_ns()+200_000_000;started=time.monotonic()
            result=run_process(sleeping,**options,absolute_deadline_monotonic_ns=deadline,stdin_text='x'*2_000_000,max_input_bytes=3_000_000)
            self.assertNotEqual(result['status'],'PASS');self.assertTrue(result['timedOut']);self.assertLess(time.monotonic()-started,3)
            self.assertLess(result['inputObservation']['acceptedBytes'],2_000_000);self.assertEqual(result['observerDisposition'],'NOT_REQUESTED')
            self.assertEqual(result['cleanup']['status'],'PASS');self.assertEqual(result['deadlineMonotonicNs'],deadline)
        with self.subTest(absoluteProcess='after-start-exception-retains-start-and-original-limit'), \
             patch.object(process_module,'_start_capture',side_effect=RuntimeError('fixture capture failure')):
            deadline=time.monotonic_ns()+3_000_000_000
            result=run_process(sleeping,**options,absolute_deadline_monotonic_ns=deadline)
            self.assertTrue(result['processStarted']);self.assertNotEqual(result['status'],'PASS');self.assertIsNone(result['processReceipt'])
            self.assertEqual(result['deadlineMonotonicNs'],deadline);self.assertLess(result['startedMonotonicNs'],deadline)
            self.assertEqual(result['cleanup']['status'],'PASS')


if __name__ == "__main__":
    unittest.main()
