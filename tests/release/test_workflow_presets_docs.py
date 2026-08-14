from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class WorkflowPresetDocumentationTests(unittest.TestCase):
    def test_bilingual_preset_pages_cover_same_commands_and_contracts(self) -> None:
        english = (ROOT / "docs/reference/workflow-presets.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/workflow-presets.md").read_text(encoding="utf-8")
        for marker in (
            "quick-change",
            "research-review",
            "feature-implementation",
            "project preset list",
            "project preset inspect",
            "project preset validate",
            "project preset render",
            "start",
            "agent-project-workflow-preset.v1",
            "agent-project-workflow-preset-render-receipt.v1",
        ):
            self.assertIn(marker, english, marker)
            self.assertIn(marker, russian, marker)

    def test_entry_points_link_to_beginner_and_advanced_workflows(self) -> None:
        english = (ROOT / "docs/guides/beginner-and-advanced-workflows.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/guides/beginner-and-advanced-workflows.md").read_text(encoding="utf-8")
        for content in (english, russian):
            self.assertIn("project preset list", content)
            self.assertIn("project preset render", content)
            self.assertIn("--preset", content)
            self.assertIn("project-workflow-profile", content)
            self.assertIn("workflow-customization", content)

    def test_root_indexes_link_to_preset_reference(self) -> None:
        for relative_path in ("README.md", "docs/README.md", "docs/ru/README.md"):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("workflow-presets.md", content, relative_path)


if __name__ == "__main__":
    unittest.main()
