from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ArchitectureDocumentationTests(unittest.TestCase):
    def test_bilingual_architecture_docs_describe_enforced_boundaries(self) -> None:
        english = (ROOT / "docs/architecture/system-architecture.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/architecture/system-architecture.md").read_text(encoding="utf-8")
        for document, acyclic_term in ((english, "acyclic"), (russian, "ациклич")):
            self.assertIn("architecture-dependencies", document)
            self.assertIn("inspection_profile.py", document)
            self.assertIn(acyclic_term, document.lower())


if __name__ == "__main__":
    unittest.main()
