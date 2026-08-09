from __future__ import annotations

import unittest

from agent_lifecycle.contracts.redaction import REDACTED_VALUE, redact_text, redact_value


class ReceiptRedactionTests(unittest.TestCase):
    def test_redact_text_covers_assignment_bearer_private_key_and_local_path(self) -> None:
        local_path = "/" + "Users/operator/private.log"
        value = (
            "API_KEY=top-secret Authorization: Bearer token-value "
            "{\"session-token\": \"session-secret\"} "
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY----- "
            + local_path
        )

        redacted, applied = redact_text(value)

        self.assertTrue(applied)
        self.assertNotIn("top-secret", redacted)
        self.assertNotIn("token-value", redacted)
        self.assertNotIn("session-secret", redacted)
        self.assertNotIn("private-material", redacted)
        self.assertNotIn(local_path, redacted)
        self.assertIn(REDACTED_VALUE, redacted)

    def test_redact_value_preserves_safe_values_and_tracks_no_change(self) -> None:
        redacted, applied = redact_value({"inputTokens": 12, "message": "safe", "items": ["ok"]})

        self.assertFalse(applied)
        self.assertEqual(redacted, {"inputTokens": 12, "message": "safe", "items": ["ok"]})

    def test_redact_value_redacts_nested_sensitive_keys(self) -> None:
        redacted, applied = redact_value({"nested": {"refresh_token": "secret"}, "path": "C:\\Users\\operator\\secret.txt"})

        self.assertTrue(applied)
        self.assertEqual(redacted["nested"]["refresh_token"], REDACTED_VALUE)
        self.assertEqual(redacted["path"], REDACTED_VALUE)


if __name__ == "__main__":
    unittest.main()
