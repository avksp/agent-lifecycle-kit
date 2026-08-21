from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SecurityDocumentationTests(unittest.TestCase):
    def test_release_175_security_contract_is_present_in_both_languages(self) -> None:
        english = (ROOT / "docs/security/release-security.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/security/release-security.md").read_text(encoding="utf-8")

        for content in (english, russian):
            self.assertIn("1.75", content)
            self.assertIn("PyPI Trusted Publisher", content)
            self.assertIn("Ed25519", content)
            self.assertIn("lock", content.lower())

        self.assertIn("claims, operation and primary artifact", english)
        self.assertIn("утверждения с операцией и", russian)

    def test_security_contract_pages_cover_receipt_binding(self) -> None:
        english = (ROOT / "docs/security/neutrality-contract.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/security/neutrality-contract.md").read_text(encoding="utf-8")

        self.assertIn("claims, operation and the", english)
        self.assertIn("primary artifact identity", english)
        self.assertIn("утверждения, операция и\nидентичность основного артефакта", russian)


if __name__ == "__main__":
    unittest.main()
