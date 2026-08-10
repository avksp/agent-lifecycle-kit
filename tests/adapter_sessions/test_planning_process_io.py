from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.adapter_sessions.process import run_process  # noqa: E402


class PlanningProcessIoTests(unittest.TestCase):
    def test_bounded_stdin_is_delivered_without_argv_interpolation(self) -> None:
        task = "private planning input"
        result = run_process(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            env=dict(os.environ),
            timeout_seconds=5,
            stdin_text=task,
            max_input_bytes=100,
            max_output_bytes=100,
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["stdout"], task)
        self.assertEqual(result["inputBytes"], len(task.encode("utf-8")))
        self.assertNotIn(task, result.get("blockers", []))

    def test_input_limit_fails_before_process_start(self) -> None:
        result = run_process(
            [sys.executable, "-c", "raise SystemExit(99)"],
            env=dict(os.environ),
            timeout_seconds=5,
            stdin_text="12345",
            max_input_bytes=4,
            max_output_bytes=100,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["processStarted"])
        self.assertEqual(result["blockers"][0]["code"], "adapter-process-input-limit")

    def test_output_limit_kills_process_and_fails_closed(self) -> None:
        result = run_process(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 5000)"],
            env=dict(os.environ),
            timeout_seconds=5,
            stdin_text="{}",
            max_input_bytes=10,
            max_output_bytes=128,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["outputLimitExceeded"])
        self.assertLessEqual(result["outputBytes"], 128)
        self.assertEqual(result["blockers"][0]["code"], "adapter-process-output-limit")

    def test_timeout_kills_process(self) -> None:
        result = run_process(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            env=dict(os.environ),
            timeout_seconds=0.05,
            stdin_text="{}",
            max_input_bytes=10,
            max_output_bytes=128,
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["timedOut"])
        self.assertEqual(result["blockers"][0]["code"], "adapter-process-timeout")


if __name__ == "__main__":
    unittest.main()
