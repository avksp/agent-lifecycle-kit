from __future__ import annotations

import ctypes
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from agent_lifecycle.changesets import git_io
from agent_lifecycle.changesets.git_io import BoundedProcess, run_bounded_command
from agent_lifecycle.contracts import LifecycleError


class BoundedGitIOTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    @staticmethod
    def command(source: str) -> list[str]:
        return [sys.executable, "-c", source]

    def test_both_pipes_are_drained_and_nonzero_exit_is_preserved(self) -> None:
        result = run_bounded_command(
            self.command("import os; os.write(2,b'e'*50000); os.write(1,b'o'*100000); raise SystemExit(7)"),
            cwd=self.root, timeout_seconds=3, max_stdout_bytes=100000,
        )
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, b"o" * 100000)
        self.assertEqual(result.stderr, b"e" * 50000)

    def test_output_limits_interrupt_a_child_that_keeps_running(self) -> None:
        for stream, code in [(1, "bounded-process-output-limit"), (2, "bounded-process-stderr-limit")]:
            with self.subTest(stream=stream):
                started = time.monotonic()
                with self.assertRaises(LifecycleError) as raised:
                    run_bounded_command(
                        self.command(f"import os,time; os.write({stream},b'x'*200000); time.sleep(20)"),
                        cwd=self.root, timeout_seconds=4, max_stdout_bytes=128, max_stderr_bytes=128,
                    )
                self.assertEqual(raised.exception.code, code)
                self.assertLess(time.monotonic() - started, 2)

    def test_stalled_read_has_one_absolute_deadline_and_reaps_the_child(self) -> None:
        children: list[subprocess.Popen] = []
        real_popen = subprocess.Popen

        def capture(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        started = time.monotonic()
        with (
            patch("agent_lifecycle.changesets.git_io.subprocess.Popen", side_effect=capture),
            self.assertRaises(LifecycleError) as raised,
        ):
            run_bounded_command(
                self.command("import time; time.sleep(20)"), cwd=self.root,
                timeout_seconds=0.15, max_stdout_bytes=128,
            )
        self.assertEqual(raised.exception.code, "bounded-process-timeout")
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_unterminated_oversized_header_is_rejected_before_eof(self) -> None:
        started = time.monotonic()
        with BoundedProcess(
            self.command("import os,time; os.write(1,b'x'*1000); time.sleep(20)"),
            cwd=self.root, deadline=started + 3, max_stdout_bytes=2000,
        ) as child:
            with self.assertRaises(LifecycleError) as raised:
                child.stdout.readline(64)
            self.assertEqual(raised.exception.code, "bounded-process-line-limit")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_short_body_is_returned_without_hanging(self) -> None:
        with BoundedProcess(
            self.command("import os; os.write(1,b'ab')"), cwd=self.root,
            deadline=time.monotonic() + 3, max_stdout_bytes=100,
        ) as child:
            self.assertEqual(child.stdout.read(3), b"ab")
            self.assertEqual(child.wait(), 0)

    def test_descendant_holding_pipes_is_reaped_even_after_the_direct_child_exits(self) -> None:
        source = (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
            "print('parent finished',flush=True)"
        )
        started = time.monotonic()
        with self.assertRaises(LifecycleError) as raised:
            run_bounded_command(
                self.command(source), cwd=self.root, timeout_seconds=0.2, max_stdout_bytes=100,
            )
        self.assertEqual(raised.exception.code, "bounded-process-timeout")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_batch_requests_and_eof_share_the_deadline(self) -> None:
        source = "import sys\nfor line in sys.stdin.buffer:\n sys.stdout.buffer.write(line); sys.stdout.buffer.flush()"
        with BoundedProcess(
            self.command(source), cwd=self.root, deadline=time.monotonic() + 3,
            max_stdout_bytes=100, writable=True,
        ) as child:
            child.write_request(b"request\n")
            self.assertEqual(child.stdout.readline(20), b"request\n")
            child.write_request(None)
            self.assertEqual(child.stdout.read_all(), b"")
            self.assertEqual(child.wait(), 0)

    def test_blocked_request_writer_cannot_escape_the_deadline(self) -> None:
        started = time.monotonic()
        with self.assertRaises(LifecycleError) as raised, BoundedProcess(
            self.command("import time; time.sleep(20)"), cwd=self.root,
            deadline=started + 0.15, max_stdout_bytes=100, writable=True,
        ) as child:
            for _ in range(10000):
                child.write_request(b"x" * 1024)
        self.assertEqual(raised.exception.code, "bounded-process-timeout")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_nonfinite_timing_and_invalid_limits_refuse_before_spawn(self) -> None:
        with patch("agent_lifecycle.changesets.git_io.subprocess.Popen") as spawn:
            for value in [float("nan"), float("inf"), float("-inf"), 0, -1, True]:
                with self.subTest(value=str(value)), self.assertRaises(LifecycleError):
                    run_bounded_command(self.command("pass"), cwd=self.root, timeout_seconds=value, max_stdout_bytes=100)
            with self.assertRaises(LifecycleError):
                run_bounded_command(self.command("pass"), cwd=self.root, timeout_seconds=1, max_stdout_bytes=0)
            spawn.assert_not_called()


class WindowsGroupDiagnosticTests(unittest.TestCase):
    def test_create_failure_captures_numeric_error_before_any_other_native_call(self) -> None:
        events = []
        kernel = Mock()
        kernel.CreateJobObjectW.side_effect = lambda *_args: events.append("CreateJobObjectW") or 0
        process = Mock(_handle=123)

        def last_error():
            events.append("get_last_error")
            return 8

        with (
            patch.object(git_io.os, "name", "nt"),
            patch.object(ctypes, "WinDLL", return_value=kernel, create=True),
            patch.object(ctypes, "get_last_error", side_effect=last_error, create=True),
            self.assertRaises(LifecycleError) as raised,
        ):
            git_io._windows_cleanup(process)
        self.assertEqual(events, ["CreateJobObjectW", "get_last_error"])
        self.assertEqual(raised.exception.code, "bounded-process-group-unavailable")
        self.assertEqual(raised.exception.message, "Cannot own the Windows child group")
        self.assertEqual(raised.exception.details, {"nativeStage": "CreateJobObjectW", "winError": 8})
        kernel.AssignProcessToJobObject.assert_not_called()
        kernel.CloseHandle.assert_not_called()

    def test_assign_failure_keeps_original_error_when_close_handle_clobbers_it(self) -> None:
        events = []
        state = {"last_error": 87}
        kernel = Mock()
        kernel.CreateJobObjectW.side_effect = lambda *_args: events.append("CreateJobObjectW") or 456
        kernel.AssignProcessToJobObject.side_effect = lambda *_args: events.append("AssignProcessToJobObject") or 0

        def last_error():
            events.append("get_last_error")
            return state["last_error"]

        def close(_handle):
            events.append("CloseHandle")
            state["last_error"] = 9999
            return 1

        kernel.CloseHandle.side_effect = close
        with (
            patch.object(git_io.os, "name", "nt"),
            patch.object(ctypes, "WinDLL", return_value=kernel, create=True),
            patch.object(ctypes, "get_last_error", side_effect=last_error, create=True),
            self.assertRaises(LifecycleError) as raised,
        ):
            git_io._windows_cleanup(Mock(_handle=123))
        self.assertEqual(events, ["CreateJobObjectW", "AssignProcessToJobObject", "get_last_error", "CloseHandle"])
        self.assertEqual(state["last_error"], 9999)
        self.assertEqual(raised.exception.code, "bounded-process-group-unavailable")
        self.assertEqual(raised.exception.message, "Cannot own the Windows child group")
        self.assertEqual(raised.exception.details, {"nativeStage": "AssignProcessToJobObject", "winError": 87})
        kernel.CloseHandle.assert_called_once_with(456)

    def test_successful_ownership_and_cleanup_do_not_read_last_error(self) -> None:
        kernel = Mock()
        kernel.CreateJobObjectW.return_value = 456
        kernel.AssignProcessToJobObject.return_value = 1
        kernel.TerminateJobObject.return_value = 1
        kernel.CloseHandle.return_value = 1
        with (
            patch.object(git_io.os, "name", "nt"),
            patch.object(ctypes, "WinDLL", return_value=kernel, create=True),
            patch.object(ctypes, "get_last_error", create=True) as last_error,
        ):
            cleanup = git_io._windows_cleanup(Mock(_handle=123))
            self.assertIsNotNone(cleanup)
            cleanup()
        last_error.assert_not_called()
        kernel.AssignProcessToJobObject.assert_called_once_with(456, 123)
        kernel.TerminateJobObject.assert_called_once_with(456, 1)
        kernel.CloseHandle.assert_called_once_with(456)

    def test_existing_cli_envelope_and_continuation_blocker_keep_bounded_details(self) -> None:
        from agent_lifecycle.cli.main import main
        from agent_lifecycle.workflow.continuation import continue_workflow

        details = {"nativeStage": "AssignProcessToJobObject", "winError": 5}
        error = LifecycleError("bounded-process-group-unavailable", "Cannot own the Windows child group", details)
        stdout = io.StringIO()
        with redirect_stdout(stdout), patch("agent_lifecycle.cli.main.dispatch", side_effect=error):
            self.assertEqual(main(["version"]), 2)
        envelope = json.loads(stdout.getvalue())
        self.assertEqual(envelope["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(envelope["code"], error.code)
        self.assertEqual(envelope["details"], details)
        with patch("agent_lifecycle.workflow.continuation.normalize_continuation_inputs", side_effect=error):
            receipt = continue_workflow(
                state_path=Path("missing-state.json"), manifest_path=Path("missing-manifest.json"),
                operation_id="unit-only-diagnostic", expected_revision=0, source_revision="unit-only", reason="unit-only",
            )
        self.assertEqual(receipt["schemaVersion"], "agent-workflow-continuation-receipt.v1")
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["blockers"][0]["context"], details)
        self.assertEqual(set(envelope["details"]), {"nativeStage", "winError"})

    def test_diagnostic_workflow_has_one_bounded_source_bound_job_and_fixed_modules(self) -> None:
        import textwrap

        workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci-timing-control.yml").read_text()
        job = workflow.split("  release235-diagnostic-windows:", 1)[1].split("  release234-windows:", 1)[0]
        self.assertIn("if: inputs.mode == 'release-2-35-diagnostic'", job)
        self.assertIn("timeout-minutes: 20", job)
        self.assertIn("python-version: \"3.15\"", job)
        self.assertIn("inputs.mode != 'release-2-34' && inputs.mode != 'release-2-35-diagnostic'", workflow)
        self.assertEqual(workflow.count("$code = @'"), 2)
        self.assertIn("re.fullmatch(r\"[0-9a-f]{40}\", candidate)", job)
        self.assertIn("head == candidate == value[\"githubSha\"]", job)
        self.assertIn("2026-10-31T23:36:59Z", job)
        self.assertIn("ALK_EXTERNAL_CONSUMER_RECEIPTS", job)
        self.assertIn("\"PYTHONPATH\" not in receipt[\"env\"]", job)
        self.assertIn("\"PYTHONHOME\" not in receipt[\"env\"]", job)
        self.assertIn("if: always()", job)
        expected = ["tests.cli.test_external_consumer_contract", "tests.cli.test_plan_delta_commands", "tests.changesets.test_git_io"]
        self.assertIn("modules = " + json.dumps(expected), job)
        for variable in ("diagnosticBinding", "diagnosticRun"):
            source = textwrap.dedent(job.split("$" + variable + " = @'", 1)[1].split("'@", 1)[0])
            compile(source, variable, "exec")
        self.assertGreater(source.rfind("remaining ="), source.index("json.loads(subprocess.check_output"))


if __name__ == "__main__":
    unittest.main()
