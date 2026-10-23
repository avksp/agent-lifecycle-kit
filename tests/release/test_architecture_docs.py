from __future__ import annotations

import json
import re
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

    def test_numeric_tables_match_policy_and_reject_conflicting_hard_limit(self) -> None:
        limits = json.loads((ROOT / "policy/architecture-limits.json").read_text(encoding="utf-8"))["limits"]
        documents = (
            "docs/architecture/modular-controller.md", "docs/architecture/system-architecture.md",
            "docs/ru/architecture/system-architecture.md", "docs/guides/contributing-and-quality.md",
            "docs/ru/guides/contributing-and-quality.md",
        )
        for path in documents:
            document = (ROOT / path).read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertIn("policy/architecture-limits.json", document)
                self._assert_limits(document, limits)
                with self.assertRaises(AssertionError):
                    self._assert_limits(document.replace("| `hardSymbols` | 80 |", "| `hardSymbols` | 120 |"), limits)

    def _assert_limits(self, document: str, limits: dict[str, int]) -> None:
        rows = re.findall(r"^\| `([A-Za-z]+)` \| ([0-9]+) \|$", document, re.M)
        self.assertEqual(limits, {key: int(value) for key, value in rows if key in limits})
        self.assertEqual(len(limits), len([key for key, _ in rows if key in limits]))

    def test_portable_usage_documentation_preserves_the_refusal_boundary(self) -> None:
        for path in ("docs/architecture/system-architecture.md", "docs/ru/architecture/system-architecture.md",
                     "docs/reference/python-api.md", "docs/ru/reference/python-api.md",
                     "docs/guides/lifecycle-cookbook.md", "docs/ru/guides/lifecycle-cookbook.md"):
            with self.subTest(path=path):
                document = (ROOT / path).read_text(encoding="utf-8")
                self.assertIn("UNIT_ONLY", document)
                self.assertIn("declared-ledger-route-unsupported", document)


if __name__ == "__main__":
    unittest.main()
