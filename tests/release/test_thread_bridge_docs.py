from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ThreadBridgeDocumentationTests(unittest.TestCase):
    def test_thread_bridge_pages_exist_in_both_locales(self) -> None:
        pairs = (
            ("docs/reference/optional-thread-bridge.md", "docs/ru/reference/optional-thread-bridge.md"),
            ("docs/reference/project-workflow-profile.md", "docs/ru/reference/project-workflow-profile.md"),
            ("docs/reference/review-mesh.md", "docs/ru/reference/review-mesh.md"),
            ("docs/reference/context-checkpoints.md", "docs/ru/reference/context-checkpoints.md"),
        )
        for english, russian in pairs:
            with self.subTest(english=english, russian=russian):
                self.assertTrue((ROOT / english).is_file())
                self.assertTrue((ROOT / russian).is_file())

    def test_bilingual_pages_cover_the_same_thread_contract_surface(self) -> None:
        english = (ROOT / "docs/reference/optional-thread-bridge.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/optional-thread-bridge.md").read_text(encoding="utf-8")
        for text in (english, russian):
            for marker in (
                "agent-thread-operation-request.v1",
                "agent-thread-operation-receipt.v1",
                "agent-thread-context-import.v1",
                "thread request",
                "thread import",
                "read",
                "list",
                "send",
                "create",
                "Review Mesh",
                "sourceOfTruth",
                "proof",
            ):
                self.assertIn(marker, text)

    def test_profile_review_context_and_architecture_pages_link_the_feature(self) -> None:
        paths = (
            ROOT / "docs/reference/project-workflow-profile.md",
            ROOT / "docs/ru/reference/project-workflow-profile.md",
            ROOT / "docs/reference/review-mesh.md",
            ROOT / "docs/ru/reference/review-mesh.md",
            ROOT / "docs/reference/context-checkpoints.md",
            ROOT / "docs/ru/reference/context-checkpoints.md",
            ROOT / "docs/architecture/system-architecture.md",
            ROOT / "docs/ru/architecture/system-architecture.md",
            ROOT / "skills/agent-workflow-orchestrator/SKILL.md",
        )
        for path in paths:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertIn("thread", text.lower())
                self.assertIn("threadBridge" if path.suffix == ".md" and "project-workflow-profile" in path.name else "thread", text)


if __name__ == "__main__":
    unittest.main()
