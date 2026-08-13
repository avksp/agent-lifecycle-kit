from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main


class ThreadBridgeCliTests(unittest.TestCase):
    def test_request_command_writes_bounded_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "request.json"
            code = main(
                [
                    "thread",
                    "request",
                    "--operation",
                    "read",
                    "--target-hash",
                    "a" * 64,
                    "--max-tokens",
                    "512",
                    "--out",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            self.assertEqual(payload["operation"], "read")
            self.assertFalse(payload["hostExecutionAllowed"])
            self.assertEqual(payload["limits"]["maxImportedTokens"], 512)

    def test_import_command_validates_receipt_and_writes_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            receipt_path = root / "receipt.json"
            output = root / "context.json"
            main(
                [
                    "thread",
                    "request",
                    "--operation",
                    "list",
                    "--out",
                    str(request_path),
                ]
            )
            from agent_lifecycle.contracts.thread_bridge_schemas import build_thread_operation_receipt

            request = json.loads(request_path.read_text(encoding="utf-8"))
            receipt = build_thread_operation_receipt(request=request, status="PASS", result={"items": ["one"]})
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            code = main(
                [
                    "thread",
                    "import",
                    "--request",
                    str(request_path),
                    "--receipt",
                    str(receipt_path),
                    "--out",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(code, 0)
            self.assertFalse(payload["sourceOfTruth"])
            self.assertFalse(payload["proof"])


if __name__ == "__main__":
    unittest.main()
