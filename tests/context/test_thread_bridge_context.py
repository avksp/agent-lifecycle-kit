from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.context.thread_bridge_context import build_thread_episode_context, import_thread_context
from agent_lifecycle.contracts.thread_bridge_schemas import build_thread_operation_receipt


class ThreadBridgeContextTests(unittest.TestCase):
    def test_receipt_becomes_untrusted_context(self) -> None:
        from agent_lifecycle.contracts.thread_bridge_schemas import build_thread_operation_request

        request = build_thread_operation_request(
            operation="read",
            operation_id="thread-read",
            target={"scope": "explicit-target", "targetHash": "a" * 64},
        )
        receipt = build_thread_operation_receipt(request=request, status="PASS", result={"text": "context"})
        imported = import_thread_context(receipt)

        self.assertFalse(imported["sourceOfTruth"])
        self.assertFalse(imported["proof"])

    def test_thread_context_is_added_as_a_retrieval_hint(self) -> None:
        from agent_lifecycle.contracts.thread_bridge_schemas import build_thread_operation_request

        request = build_thread_operation_request(
            operation="read",
            operation_id="thread-read",
            target={"scope": "explicit-target", "targetHash": "b" * 64},
        )
        receipt = build_thread_operation_receipt(request=request, status="PASS", result={"text": "context"})
        imported = import_thread_context(receipt)

        with tempfile.TemporaryDirectory() as directory:
            result = build_thread_episode_context(Path(directory), [], imported, query="context")

        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(result.get("externalContextHintCount", 0), 1)

    def test_unavailable_receipt_does_not_become_pass_context(self) -> None:
        receipt = {
            "status": "UNAVAILABLE",
            "operationId": "thread-read-unavailable",
            "receiptDigest": "c" * 64,
            "result": {},
        }

        imported = import_thread_context(receipt)

        self.assertEqual(imported["status"], "FAIL")
        self.assertEqual(imported["source"]["status"], "UNAVAILABLE")
        self.assertEqual(imported["blockers"][0]["code"], "thread-source-status")


if __name__ == "__main__":
    unittest.main()
