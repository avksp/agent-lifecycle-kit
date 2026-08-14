from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.process import run_process

try:
    from .helpers import _run_cli  # noqa: F401,E402
except ImportError:
    from helpers import _run_cli  # type: ignore[no-redef]


class ExecutionResourceCommandTests(unittest.TestCase):
    def test_execution_report_cli_is_local_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_process(
                [sys.executable, "-c", "print('not stored')"],
                env={},
                timeout_seconds=5,
                operation_id="cli-op",
                attempt_id="cli-attempt",
                adapter_id="fixture",
            )
            receipt = root / "receipt.json"
            output = root / "report.json"
            receipt.write_text(json.dumps(result["processReceipt"]), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "metrics",
                    "execution-report",
                    "--receipt",
                    str(receipt),
                    "--operation-id",
                    "cli-op",
                    "--out",
                    str(output),
                ]
            )
            self.assertTrue(output.is_file())
            self.assertNotIn("not stored", output.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-execution-resource-report-generation.v1")
        self.assertEqual(payload["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
