from __future__ import annotations

import sys
import time
import unittest

from agent_lifecycle.host_protocol.inspection_common import (
    CommandRun,
    _default_command_runner,
    _run_command_check_with_text,
)


class InspectionTransportTests(unittest.TestCase):
    def check_command(self, source: str, timeout: float = 3):
        return _run_command_check_with_text(
            "inert-fixture", [sys.executable, "-c", source],
            timeout_seconds=timeout, command_runner=_default_command_runner,
        )

    def test_actual_default_runner_redacts_the_complete_output_before_first_line(self) -> None:
        check, first_line, text = self.check_command("print('api_key='+'q'*5000)")
        self.assertEqual(check["status"], "PASS")
        self.assertEqual(first_line, "api_key=<redacted>")
        self.assertNotIn("q" * 30, text)
        self.assertTrue(check["details"]["stdoutRedacted"])
        self.assertFalse(check["details"]["stderrRedacted"])
        self.assertGreater(check["details"]["stdoutBytes"], 5000)

    def test_actual_default_runner_stops_oversized_output_before_child_exit(self) -> None:
        started = time.monotonic()
        check, first_line, text = self.check_command(
            "import os,time; os.write(1,b'x'*2000000); time.sleep(10)",
        )
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(check["details"]["reason"], "bounded-process-output-limit")
        self.assertIsNone(first_line)
        self.assertEqual(text, "")
        self.assertLess(time.monotonic() - started, 2)

    def test_actual_default_runner_enforces_the_original_deadline(self) -> None:
        started = time.monotonic()
        check, _first_line, text = self.check_command("import time; time.sleep(10)", timeout=0.15)
        self.assertEqual(check["status"], "FAIL")
        self.assertEqual(check["details"]["reason"], "bounded-process-timeout")
        self.assertEqual(text, "")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_injected_runner_cannot_publish_an_oversized_capture(self) -> None:
        for stdout, stderr in [("x" * 2000000, ""), ("", "x" * 100000)]:
            with self.subTest(stderr=bool(stderr)):
                check, first_line, text = _run_command_check_with_text(
                    "fixture", ["fixture", "--help"], timeout_seconds=1,
                    command_runner=lambda _argv, _timeout, out=stdout, err=stderr: CommandRun(0, out, err),
                )
                self.assertEqual(check["status"], "FAIL")
                self.assertEqual(check["details"]["reason"], "inspection-output-limit")
                self.assertIsNone(first_line)
                self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()
