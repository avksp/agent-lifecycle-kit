from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ProcessObservabilityDocumentationTests(unittest.TestCase):
    ENGLISH = ROOT / "docs/reference/process-execution-observability.md"
    RUSSIAN = ROOT / "docs/ru/reference/process-execution-observability.md"

    def test_bilingual_pages_cover_the_same_process_contract(self) -> None:
        english = self.ENGLISH.read_text(encoding="utf-8")
        russian = self.RUSSIAN.read_text(encoding="utf-8")
        for marker in (
            "agent-process-execution-receipt.v1",
            "agent-execution-resource-report.v1",
            "metrics execution-report",
            "ATTESTED",
            "ESTIMATED",
            "UNAVAILABLE",
            "BLOCKED",
            "monotonic",
        ):
            self.assertIn(marker, english, marker)
        for marker in (
            "agent-process-execution-receipt.v1",
            "agent-execution-resource-report.v1",
            "metrics execution-report",
            "ATTESTED",
            "ESTIMATED",
            "UNAVAILABLE",
            "BLOCKED",
            "очист",
        ):
            self.assertIn(marker, russian, marker)

    def test_pages_link_to_each_other_and_indexes(self) -> None:
        english = self.ENGLISH.read_text(encoding="utf-8")
        russian = self.RUSSIAN.read_text(encoding="utf-8")
        self.assertIn("../ru/reference/process-execution-observability.md", english)
        self.assertIn("docs/reference/process-execution-observability.md", russian)
        self.assertIn("process-execution-observability.md", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("process-execution-observability.md", (ROOT / "docs/README.md").read_text(encoding="utf-8"))
        self.assertIn("process-execution-observability.md", (ROOT / "docs/ru/README.md").read_text(encoding="utf-8"))

    def test_qualification_and_support_docs_do_not_keep_old_work_paths(self) -> None:
        for relative in (
            "docs/reference/agent-plugin-qualification.md",
            "docs/ru/reference/agent-plugin-qualification.md",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("work/release-1-68", content, relative)
        for relative in (
            "docs/adapters/support-matrix.md",
            "docs/ru/adapters/support-matrix.md",
        ):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("1.68 adds", content, relative)
            self.assertNotIn("1.68 появились", content, relative)


if __name__ == "__main__":
    unittest.main()
