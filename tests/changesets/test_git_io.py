from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
