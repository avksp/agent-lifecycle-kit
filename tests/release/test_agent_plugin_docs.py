from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginDocumentationTests(unittest.TestCase):
    PIN_SURFACES = (
        "README.md",
        "docs/README.md",
        "docs/ru/README.md",
        "docs/guides/install-and-first-run.md",
        "docs/ru/guides/install-and-first-run.md",
        "docs/reference/cli.md",
        "docs/ru/reference/cli.md",
    )

    def test_user_visible_package_pins_use_target_release(self) -> None:
        for relative_path in self.PIN_SURFACES:
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("agent-lifecycle-kit==1.73.0", content, relative_path)
            self.assertNotIn("agent-lifecycle-kit==1.66.0", content, relative_path)
            self.assertNotIn("agent-lifecycle-kit==1.67.0", content, relative_path)

    def test_english_and_russian_package_pages_describe_same_contract(self) -> None:
        required = (
            "agent-plugins.org/specification",
            "plugin.json",
            "skills/",
            "agent-lifecycle-kit-agent-plugin-v1.70.0.zip",
            "1.70.0",
        )
        for relative_path in (
            "docs/reference/agent-plugins.md",
            "docs/ru/reference/agent-plugins.md",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            for marker in required:
                self.assertIn(marker, content, f"{marker}: {relative_path}")

    def test_publication_pages_explain_portable_projection(self) -> None:
        for relative_path in (
            "docs/reference/plugin-publication.md",
            "docs/ru/reference/plugin-publication.md",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("agent-plugins.md", content, relative_path)
            self.assertIn("plugin.json", content, relative_path)
            self.assertIn("skills/", content, relative_path)

    def test_indexes_and_support_matrices_link_package_pages(self) -> None:
        for relative_path in (
            "README.md",
            "docs/README.md",
            "docs/ru/README.md",
            "docs/adapters/support-matrix.md",
            "docs/ru/adapters/support-matrix.md",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("agent-plugins", content, relative_path)

    def test_bilingual_package_pages_link_to_each_other(self) -> None:
        english = (ROOT / "docs/reference/agent-plugins.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/agent-plugins.md").read_text(encoding="utf-8")
        self.assertIn("../ru/reference/agent-plugins.md", english)
        self.assertIn(
            "https://github.com/avksp/agent-lifecycle-kit/blob/main/docs/reference/agent-plugins.md",
            russian,
        )
        self.assertNotIn("English version: [Portable Agent Plugins package](agent-plugins.md)", russian)


if __name__ == "__main__":
    unittest.main()
