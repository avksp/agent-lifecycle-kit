from __future__ import annotations

import unittest

from agent_lifecycle.adapter_sessions.redaction import redact_process_text as facade_redact
from agent_lifecycle.contracts.process_redaction import redact_process_text


class ProcessRedactionContractTests(unittest.TestCase):
    def test_adapter_facade_matches_shared_contract(self) -> None:
        posix_path = "/" + "Users/example/project"
        value = f"token=sk-test-secret {posix_path} C:\\Users\\example\\project"
        self.assertEqual(facade_redact(value), redact_process_text(value))
        redacted, changed = redact_process_text(value)
        self.assertTrue(changed)
        self.assertNotIn("sk-test-secret", redacted)
        self.assertNotIn(posix_path, redacted)
        self.assertNotIn("C:\\Users\\example", redacted)


if __name__ == "__main__":
    unittest.main()
