from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginQualificationDocumentationTests(unittest.TestCase):
    def test_bilingual_pages_describe_the_same_outcomes(self) -> None:
        english = (ROOT / "docs/reference/agent-plugin-qualification.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/agent-plugin-qualification.md").read_text(encoding="utf-8")
        for marker in ("OFFLINE_VALIDATED", "QUALIFIED", "BLOCKED", "UNAVAILABLE", "plugin-qualify", "1.68.0"):
            self.assertIn(marker, english)
            self.assertIn(marker, russian)
        self.assertIn("agent-plugin-qualification.md", english)
        self.assertIn("docs/reference/agent-plugin-qualification.md", russian)

    def test_pages_keep_installation_client_owned_and_lifecycle_boundary(self) -> None:
        for relative in ("docs/reference/agent-plugin-qualification.md", "docs/ru/reference/agent-plugin-qualification.md"):
            content = (ROOT / relative).read_text(encoding="utf-8")
            client_marker = "клиент" if "/ru/" in relative else "client"
            self.assertIn(client_marker, content.lower())
            self.assertIn("lifecycle", content.lower())
            self.assertIn("managed", content.lower())


if __name__ == "__main__":
    unittest.main()
