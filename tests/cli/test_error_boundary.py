from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.cli.main import main


class CliErrorBoundaryTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_expected_io_error_is_structured_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with contextlib.chdir(root):
                code, stdout, stderr = self._run(
                    ["model", "route", "--profile", "missing-profile.json", "--request", "missing-request.json"]
                )
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "")
        self.assertNotIn(str(root), stdout)
        self.assertNotIn("No such file", stdout)
        self.assertIn('"code":"json-input-unavailable"', stdout)
        self.assertIn('"schemaVersion":"agent-lifecycle-error.v1"', stdout)

    def test_unmapped_io_error_uses_safe_root_code(self) -> None:
        with patch("agent_lifecycle.cli.main.dispatch", side_effect=OSError("/private/absolute/path")):
            code, stdout, stderr = self._run(["version"])
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "")
        self.assertNotIn("/private/absolute/path", stdout)
        self.assertIn('"code":"cli-io-error"', stdout)

    def test_unexpected_exception_is_structured_without_traceback(self) -> None:
        with patch("agent_lifecycle.cli.main.dispatch", side_effect=RuntimeError("/private/absolute/path")):
            code, stdout, stderr = self._run(["version"])
        self.assertEqual(code, 2)
        self.assertEqual(stderr, "")
        self.assertNotIn("Traceback", stdout)
        self.assertNotIn("/private/absolute/path", stdout)
        self.assertIn('"code":"cli-unexpected-error"', stdout)

    def test_lifecycle_error_payload_remains_unchanged(self) -> None:
        with patch(
            "agent_lifecycle.cli.main.dispatch",
            side_effect=ValueError("internal detail must not replace the contract"),
        ):
            code, stdout, _stderr = self._run(["version"])
        self.assertEqual(code, 2)
        self.assertIn('"message":"CLI operation failed"', stdout)

    def test_keyboard_interrupt_and_system_exit_are_not_swallowed(self) -> None:
        with (
            patch("agent_lifecycle.cli.main.dispatch", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            main(["version"])
        with (
            patch("agent_lifecycle.cli.main.dispatch", side_effect=SystemExit(7)),
            self.assertRaises(SystemExit) as raised,
        ):
            main(["version"])
        self.assertEqual(raised.exception.code, 7)


if __name__ == "__main__":
    unittest.main()
