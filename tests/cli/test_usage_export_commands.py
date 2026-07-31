from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class UsageExportCliTests(unittest.TestCase):
    def test_usage_export_cli_writes_json_and_table_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "usage.json"
            json_out = root / "usage-export.json"
            table_out = root / "usage-export.txt"
            artifact.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-host-operation-receipt.v1",
                        "host": "codex",
                        "runId": "run-1",
                        "taskId": "WS-01",
                        "operationId": "op",
                        "usage": {"inputTokens": 4, "outputTokens": 6, "toolCalls": 2},
                    }
                ),
                encoding="utf-8",
            )

            code, receipt = _run_cli(
                [
                    "metrics",
                    "usage-export",
                    "--artifact",
                    str(artifact),
                    "--project-root",
                    str(root),
                    "--out",
                    str(json_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(receipt["schemaVersion"], "agent-usage-export-generation.v1")
            self.assertEqual(receipt["status"], "PASS")
            payload = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(payload["entries"][0]["tokens"]["total"], 10)

            code, table_receipt = _run_cli(
                [
                    "metrics",
                    "usage-export",
                    "--artifact",
                    str(artifact),
                    "--project-root",
                    str(root),
                    "--format",
                    "table",
                    "--out",
                    str(table_out),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(table_receipt["format"], "table")
            self.assertIn("usage-1", table_out.read_text(encoding="utf-8"))

    def test_usage_export_cli_does_not_overwrite_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "usage.json"
            out = root / "usage-export.json"
            artifact.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-host-operation-receipt.v1",
                        "host": "codex",
                        "operationId": "op",
                        "usage": {"billableTokens": 1},
                    }
                ),
                encoding="utf-8",
            )
            out.write_text("occupied", encoding="utf-8")

            code, payload = _run_cli(
                [
                    "metrics",
                    "usage-export",
                    "--artifact",
                    str(artifact),
                    "--project-root",
                    str(root),
                    "--out",
                    str(out),
                ]
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "output-already-exists")


if __name__ == "__main__":
    unittest.main()
