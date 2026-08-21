from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ERROR_CODES = (
    "cli-io-error",
    "cli-invalid-encoding",
    "cli-invalid-json",
    "cli-json-depth-exceeded",
    "cli-unexpected-error",
)


class CliErrorDocumentationTests(unittest.TestCase):
    def test_english_and_russian_pages_cover_the_same_error_contract(self) -> None:
        english = (ROOT / "docs/reference/cli-errors.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/cli-errors.md").read_text(encoding="utf-8")
        for code in ERROR_CODES:
            with self.subTest(code=code):
                self.assertIn(code, english)
                self.assertIn(code, russian)
        self.assertIn("../ru/reference/cli-errors.md", english)
        self.assertIn("../../reference/cli-errors.md", russian)
        self.assertIn("KeyboardInterrupt", english)
        self.assertIn("KeyboardInterrupt", russian)
        self.assertIn("SystemExit", english)
        self.assertIn("SystemExit", russian)


if __name__ == "__main__":
    unittest.main()
