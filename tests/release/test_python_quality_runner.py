from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tools.release.run_python_quality import _run_command


class PythonQualityRunnerTests(unittest.TestCase):
    def test_runner_uses_bounded_command_and_accepts_diagnostic_exit(self) -> None:
        result = _run_command(
            [sys.executable, "-c", "print('diagnostic')"],
            cwd=Path.cwd(),
            timeout_seconds=5,
            output_limit=1024,
            expected_exit_codes={0, 1},
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].strip(), "diagnostic")
        self.assertFalse(result["timedOut"])
        self.assertFalse(result["outputLimited"])

    def test_runner_rejects_output_over_limit(self) -> None:
        result = _run_command(
            [sys.executable, "-c", "print('x' * 4096)"],
            cwd=Path.cwd(),
            timeout_seconds=5,
            output_limit=128,
            expected_exit_codes={0},
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["outputLimited"])

    def test_runner_reports_invocation_failure_as_structured_result(self) -> None:
        result = _run_command(
            ["/path/that/does/not/exist"],
            cwd=Path.cwd(),
            timeout_seconds=5,
            output_limit=1024,
            expected_exit_codes={0},
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["returncode"])
        self.assertIn("No such file", result["stderr"])


if __name__ == "__main__":
    unittest.main()
