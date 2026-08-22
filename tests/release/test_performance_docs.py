from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGLISH = ROOT / "docs/reference/performance-and-resource-budgets.md"
RUSSIAN = ROOT / "docs/ru/reference/performance-and-resource-budgets.md"


class PerformanceDocumentationTests(unittest.TestCase):
    def test_bilingual_pages_exist_and_cover_the_same_contract(self) -> None:
        english = ENGLISH.read_text(encoding="utf-8")
        russian = RUSSIAN.read_text(encoding="utf-8")
        for text in (english, russian):
            self.assertIn("1.78", text)
            self.assertIn("Ed25519", text)
            self.assertIn("tracked-release", text)
            self.assertIn("full-repository", text)
            self.assertIn("NO_RECOMMENDATION", text)
            self.assertIn("INCOMPLETE", text)
            self.assertIn("BLOCKED", text)
            self.assertIn("policy/performance-budgets.json", text)
            self.assertIn("performance_limits.py", text)
            self.assertIn("shell=True", text)
        for marker in ("20%", "128", "16", "256", "600", "96"):
            self.assertIn(marker, english)
            self.assertIn(marker, russian)

    def test_pages_explicitly_reject_constant_time_claims_and_caching(self) -> None:
        for path in (ENGLISH, RUSSIAN):
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("constant-time" if path == ENGLISH else "постоянном времени", text)
            self.assertIn("cach" if path == ENGLISH else "кэширован", text)


if __name__ == "__main__":
    unittest.main()
