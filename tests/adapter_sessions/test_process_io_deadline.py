from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.adapter_sessions.process import run_process


class ProcessIODeadlineTests(unittest.TestCase):
    def test_nonfinite_timing_refuses_before_spawning_or_observing_a_child(self) -> None:
        for field in ("timeout_seconds", "cleanup_grace_seconds"):
            for value in (float("nan"), float("inf"), float("-inf"), -0.1):
                with self.subTest(field=field, value=str(value)), tempfile.TemporaryDirectory() as tmp:
                    with patch("agent_lifecycle.adapter_sessions.process.subprocess.Popen") as spawn:
                        result = run_process(
                            [sys.executable, "-c", "pass"],
                            cwd=Path(tmp),
                            env=dict(os.environ),
                            timeout_seconds=value if field == "timeout_seconds" else 1.0,
                            cleanup_grace_seconds=value if field == "cleanup_grace_seconds" else 0.1,
                        )
                    spawn.assert_not_called()
                    self.assertFalse(result["processStarted"])
                    self.assertNotEqual(result["status"], "PASS")

    def test_zero_cleanup_grace_preserves_success_and_zero_timeout_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_process(
                [sys.executable, "-c", "print('done')"],
                cwd=Path(tmp),
                env=dict(os.environ),
                timeout_seconds=3,
                cleanup_grace_seconds=0,
            )
            self.assertEqual(result["status"], "PASS", result)
            self.assertTrue(result["processStarted"])
            self.assertEqual(result["processReceipt"]["limits"]["cleanupGraceSeconds"], 0)
            with patch("agent_lifecycle.adapter_sessions.process.subprocess.Popen") as spawn:
                invalid = run_process(
                    [sys.executable, "-c", "pass"],
                    cwd=Path(tmp),
                    env=dict(os.environ),
                    timeout_seconds=0,
                    cleanup_grace_seconds=0,
                )
            spawn.assert_not_called()
            self.assertFalse(invalid["processStarted"])
            self.assertNotEqual(invalid["status"], "PASS")

    def test_stdout_and_stderr_are_redacted_before_the_display_tail_is_taken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = "import sys; value='api_key='+'q'*5000; print(value); print(value,file=sys.stderr)"
            result = run_process(
                [sys.executable, "-c", source],
                cwd=Path(tmp),
                env=dict(os.environ),
                timeout_seconds=3,
                max_output_bytes=20000,
                cleanup_grace_seconds=0.1,
            )
        self.assertEqual(result["status"], "PASS")
        for stream in ("stdout", "stderr"):
            self.assertTrue(result[stream + "Redacted"])
            self.assertNotIn("q" * 30, result[stream + "Tail"])
            self.assertIn("<redacted>", result[stream + "Tail"])

    def test_ordinary_stdin_that_is_never_read_remains_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            started = time.monotonic()
            result = run_process(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                cwd=Path(tmp),
                env=dict(os.environ),
                stdin_text="x" * (4 * 1024 * 1024),
                timeout_seconds=0.15,
                max_input_bytes=4 * 1024 * 1024,
                cleanup_grace_seconds=0.05,
            )
        self.assertNotEqual(result["status"], "PASS")
        self.assertTrue(result["timedOut"])
        self.assertTrue(result["cleanup"]["directChildExited"])
        self.assertTrue(result["cleanup"]["knownDescendantsGone"])
        self.assertLess(time.monotonic() - started, 2)


if __name__ == "__main__":
    unittest.main()
