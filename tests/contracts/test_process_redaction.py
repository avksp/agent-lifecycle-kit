from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.redaction import redact_process_text as facade_redact
from agent_lifecycle.contracts.process_redaction import redact_process_text


class ProcessRedactionContractTests(unittest.TestCase):
    def test_shared_process_contract_and_adapter_facade_remove_new_credential_families(self) -> None:
        tokens = ["glpat-" + "A" * 24, "npm_" + "B" * 36,
                  "sk_live_" + "C" * 24, "hf_" + "D" * 34, "AIza" + "E" * 35]
        value = " ".join(tokens) + " https://example.invalid/?sig=opaque-value&keep=home"
        redacted, changed = redact_process_text(value)
        self.assertTrue(changed)
        self.assertEqual(facade_redact(value), (redacted, changed))
        for token in tokens:
            self.assertNotIn(token, redacted)
        self.assertNotIn("opaque-value", redacted)
        self.assertIn("https://example.invalid/?sig=<redacted>&keep=home", redacted)

    def test_adapter_facade_matches_shared_contract(self) -> None:
        posix_path = "/" + "Users/example/project"
        value = f"token=sk-test-secret {posix_path} C:\\Users\\example\\project"
        self.assertEqual(facade_redact(value), redact_process_text(value))
        redacted, changed = redact_process_text(value)
        self.assertTrue(changed)
        self.assertNotIn("sk-test-secret", redacted)
        self.assertNotIn(posix_path, redacted)
        self.assertNotIn("C:\\Users\\example", redacted)

    def test_process_output_preserves_public_urls(self) -> None:
        value = "See https://github.com/avksp/agent-lifecycle-kit/docs and http://example.com/public"

        redacted, changed = redact_process_text(value)

        self.assertFalse(changed)
        self.assertEqual(redacted, value)

    def test_process_output_normalizes_public_url_without_redacting_it(self) -> None:
        value = "See HTTPS://EXAMPLE.COM:443/docs#Public"

        redacted, changed = redact_process_text(value)

        self.assertTrue(changed)
        self.assertEqual(redacted, "See https://example.com/docs#Public")

    def test_process_output_redacts_url_secrets(self) -> None:
        value = "https://user:password@example.com/path?api_key=topsecret"

        redacted, changed = redact_process_text(value)

        self.assertTrue(changed)
        self.assertNotIn("password", redacted)
        self.assertNotIn("topsecret", redacted)


if __name__ == "__main__":
    unittest.main()
