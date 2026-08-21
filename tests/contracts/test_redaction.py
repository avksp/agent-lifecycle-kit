from __future__ import annotations

import unittest

from agent_lifecycle.contracts.redaction import REDACTED_VALUE, redact_text, redact_value


class ReceiptRedactionTests(unittest.TestCase):
    def test_redact_text_covers_assignment_bearer_private_key_and_local_path(self) -> None:
        local_path = "/" + "Users/operator/private.log"
        value = (
            "API_KEY=top-secret Authorization: Bearer token-value "
            "{\"session-token\": \"session-secret\"} "
            "-----BEGIN " + "PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY----- "
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

    def test_redact_value_redacts_common_posix_roots(self) -> None:
        paths = [
            "/" + "Volumes/Work/repo/private.txt",
            "/root/.ssh/id_rsa",
            "/opt/data/private.txt",
            "/etc/passwd",
            "/var/log/private.log",
        ]

        redacted, applied = redact_value({"paths": paths})

        self.assertTrue(applied)
        self.assertEqual(redacted["paths"], [REDACTED_VALUE] * len(paths))

    def test_redact_value_redacts_windows_unc_paths(self) -> None:
        paths = [
            r"\\corp-filesvr\eng\secret\roadmap.md",
            r"\\filesvr/share/secret",
            r"\\?\C:\Users\operator\secret.txt",
            r"C:\Users/operator\secret.txt",
            r"C:\foo/bar\baz",
            r"\Windows\System32\drivers",
            r"file:///etc/passwd",
        ]

        redacted, applied = redact_value({"paths": paths})

        self.assertTrue(applied)
        self.assertEqual(redacted["paths"], [REDACTED_VALUE] * len(paths))

    def test_redact_text_covers_standalone_provider_token_formats(self) -> None:
        values = [
            "sk-" + "proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789",
            "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature-material",
            "gh" + "p_1234567890abcdefghijklmnopqrstuvwxyzAB",
            "xo" + "xb-123456789012-1234567890123-AbCdEfGhIjKlMnOp",
            "AKIA" + "IOSFODNN7EXAMPLE",
        ]
        redacted, applied = redact_text(" ".join(values))

        self.assertTrue(applied)
        for value in values:
            self.assertNotIn(value, redacted)
        self.assertGreaterEqual(redacted.count(REDACTED_VALUE), len(values))


if __name__ == "__main__":
    unittest.main()
