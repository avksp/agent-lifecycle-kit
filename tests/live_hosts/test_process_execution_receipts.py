from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts.process_execution_schemas import validate_process_execution_receipt
from tools.live_hosts.json_cli_harness import run_command_capture, write_invocation_diagnostic


class ProcessExecutionReceiptTests(unittest.TestCase):
    def test_command_capture_returns_valid_receipt_and_safe_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run_command_capture(
                [sys.executable, "-c", "print('ok')"],
                cwd=root,
                timeout_seconds=5,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIsInstance(result.process_receipt, dict)
            assert result.process_receipt is not None
            self.assertEqual(validate_process_execution_receipt(result.process_receipt)["status"], "PASS")

            diagnostic_path = write_invocation_diagnostic(
                root,
                "probe",
                "probe-1",
                result,
                "test-live-diagnostic.v1",
            )
            diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
            self.assertEqual(diagnostic["processExecution"]["status"], "PASS")
            self.assertNotIn("stdout", diagnostic)
            self.assertNotIn("stderr", diagnostic)
            self.assertNotIn("environment", diagnostic)


if __name__ == "__main__":
    unittest.main()
