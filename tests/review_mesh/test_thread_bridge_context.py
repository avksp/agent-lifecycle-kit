from __future__ import annotations

import unittest

from agent_lifecycle.contracts.thread_bridge_schemas import build_thread_operation_request, build_thread_operation_receipt
from agent_lifecycle.review_mesh import build_thread_context_review_input, source_from_thread_context
from agent_lifecycle.context.thread_bridge_context import import_thread_context


class ReviewMeshThreadContextTests(unittest.TestCase):
    def test_thread_context_has_explicit_optional_source_role(self) -> None:
        request = build_thread_operation_request(
            operation="read",
            operation_id="thread-review",
            target={"scope": "explicit-target", "targetHash": "c" * 64},
        )
        receipt = build_thread_operation_receipt(request=request, status="PASS", result={"text": "review context"})
        imported = import_thread_context(receipt, source_id="thread-1")

        source = source_from_thread_context(imported)
        review_input = build_thread_context_review_input(imported)

        self.assertEqual(source["kind"], "THREAD_CONTEXT_IMPORT")
        self.assertEqual(review_input["sourceRole"], "optional-thread-context")
        self.assertFalse(review_input["sourceOfTruth"])
        self.assertFalse(review_input["proof"])
        self.assertFalse(review_input["promptAuthorityGranted"])


if __name__ == "__main__":
    unittest.main()
