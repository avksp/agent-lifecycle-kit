from __future__ import annotations

import unittest

from agent_lifecycle.host_protocol.receipts import normalize_host_operation_receipt


class HostOperationReceiptRedactionTests(unittest.TestCase):
    def test_public_url_is_preserved_in_host_receipt(self) -> None:
        private_path = "/" + "Users/operator/private.log"
        payload = {
            "schemaVersion": "agent-host-operation-receipt.v1",
            "operationId": "op-1",
            "capability": "inspect",
            "status": "PASS",
            "outputs": [
                {"message": "see https://github.com/avksp/agent-lifecycle-kit/docs"},
                {"path": private_path},
            ],
            "usage": {},
        }

        receipt = normalize_host_operation_receipt(payload)

        self.assertEqual(receipt["outputs"][0]["message"], "see https://github.com/avksp/agent-lifecycle-kit/docs")
        self.assertNotIn(private_path, str(receipt))
        self.assertEqual(receipt["usage"]["receiptRedaction"]["secretValuesStored"], False)

    def test_url_credentials_and_sensitive_query_values_are_redacted(self) -> None:
        payload = {
            "schemaVersion": "agent-host-operation-receipt.v1",
            "operationId": "op-2",
            "capability": "inspect",
            "status": "PASS",
            "outputs": [{"message": "https://user:password@example.com/path?api_key=topsecret&ok=1"}],
            "usage": {},
        }

        receipt = normalize_host_operation_receipt(payload)
        message = receipt["outputs"][0]["message"]

        self.assertNotIn("password", message)
        self.assertNotIn("topsecret", message)
        self.assertIn("example.com/path?api_key=<redacted>&ok=1", message)

    def test_public_url_is_normalized_without_losing_its_path(self) -> None:
        payload = {
            "schemaVersion": "agent-host-operation-receipt.v1",
            "operationId": "op-3",
            "capability": "inspect",
            "status": "PASS",
            "outputs": [{"message": "HTTPS://EXAMPLE.COM:443/docs#Receipt"}],
            "usage": {},
        }

        receipt = normalize_host_operation_receipt(payload)

        self.assertEqual(receipt["outputs"][0]["message"], "https://example.com/docs#Receipt")


if __name__ == "__main__":
    unittest.main()
