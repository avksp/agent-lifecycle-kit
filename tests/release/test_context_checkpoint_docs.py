from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ContextCheckpointDocumentationTests(unittest.TestCase):
    def test_bilingual_guides_cover_same_operational_contract(self) -> None:
        english = (ROOT / "docs/reference/context-checkpoints.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/context-checkpoints.md").read_text(encoding="utf-8")
        for text in (english, russian):
            self.assertIn("MILESTONE", text)
            self.assertIn("AGENT_REQUESTED", text)
            self.assertIn("NATIVE_HOOK", text)
            self.assertIn("UNAVAILABLE", text)
            self.assertIn("agent-lifecycle context checkpoint", text)
            self.assertIn("agent-lifecycle context restore", text)
            self.assertIn("64", text)
            self.assertIn("implementationAuthorized", text)
        self.assertIn("Compaction", english.title())
        self.assertIn("сжатия", russian.lower())

    def test_architecture_and_existing_context_guides_link_the_page(self) -> None:
        for relative in (
            "docs/architecture/system-architecture.md",
            "docs/ru/architecture/system-architecture.md",
            "docs/reference/episode-retrieval.md",
            "docs/ru/reference/episode-retrieval.md",
            "docs/reference/managed-adapter-sessions.md",
            "docs/ru/reference/managed-adapter-sessions.md",
            "skills/agent-workflow-orchestrator/SKILL.md",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8").lower()
            self.assertTrue("context checkpoint" in content or "снимки контекста" in content)


if __name__ == "__main__":
    unittest.main()
