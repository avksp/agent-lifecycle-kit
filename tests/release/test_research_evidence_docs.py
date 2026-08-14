from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ResearchEvidenceDocumentationTests(unittest.TestCase):
    def test_bilingual_research_pages_exist_and_link(self) -> None:
        english = ROOT / "docs/reference/research-evidence.md"
        russian = ROOT / "docs/ru/reference/research-evidence.md"
        self.assertTrue(english.is_file())
        self.assertTrue(russian.is_file())
        self.assertIn("../ru/reference/research-evidence.md", english.read_text(encoding="utf-8"))
        self.assertIn(
            "https://github.com/avksp/agent-lifecycle-kit/blob/main/docs/reference/research-evidence.md",
            russian.read_text(encoding="utf-8"),
        )

    def test_bilingual_guides_describe_the_same_commands_and_boundaries(self) -> None:
        english = (ROOT / "docs/guides/research-workflow.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/guides/research-workflow.md").read_text(encoding="utf-8")
        for marker in (
            "research validate",
            "research summary",
            "agent-research-evidence-package.v1",
            "UNAVAILABLE",
            "Review Mesh",
        ):
            self.assertIn(marker, english)
            self.assertIn(marker, russian)
        self.assertIn("does not fetch", english)
        self.assertIn("не загружает", russian)

    def test_cli_and_contract_indexes_expose_research_surface(self) -> None:
        for relative_path in (
            "README.md",
            "docs/README.md",
            "docs/ru/README.md",
            "docs/reference/cli.md",
            "docs/ru/reference/cli.md",
            "docs/reference/public-contracts.md",
            "docs/ru/reference/public-contracts.md",
            "docs/architecture/system-architecture.md",
            "docs/ru/architecture/system-architecture.md",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("research", content.lower(), relative_path)
            if relative_path not in {"README.md", "docs/README.md", "docs/ru/README.md"}:
                self.assertIn("agent-research", content, relative_path)


if __name__ == "__main__":
    unittest.main()
