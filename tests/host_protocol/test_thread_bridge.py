from __future__ import annotations

import unittest

from agent_lifecycle.host_protocol.thread_bridge import (
    prepare_thread_context_import,
    prepare_thread_request,
    validate_thread_exchange,
)


class ThreadBridgeHostProtocolTests(unittest.TestCase):
    def test_boundary_prepares_request_and_validates_exchange_without_host_call(self) -> None:
        request = prepare_thread_request(
            operation="list",
            operation_id="thread-list-1",
            target={"scope": "project", "projectHash": "p" * 64},
        )
        from agent_lifecycle.contracts.thread_bridge_schemas import build_thread_operation_receipt

        receipt = build_thread_operation_receipt(request=request, status="UNAVAILABLE", result={})
        validation = validate_thread_exchange(request, receipt)

        self.assertEqual(validation["status"], "PASS")
        self.assertFalse(request["hostExecutionAllowed"])

    def test_context_wrapper_preserves_non_authoritative_role(self) -> None:
        imported = prepare_thread_context_import(
            operation_id="thread-list-1",
            source_receipt_digest="e" * 64,
            content={"items": []},
        )

        self.assertFalse(imported["sourceOfTruth"])
        self.assertFalse(imported["proof"])


if __name__ == "__main__":
    unittest.main()
