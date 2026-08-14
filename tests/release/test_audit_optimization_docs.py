from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class AuditOptimizationDocumentationTests(unittest.TestCase):
    def test_english_and_russian_guides_cover_the_same_operator_flow(self) -> None:
        english = (ROOT / "docs/reference/audit-optimization.md").read_text(encoding="utf-8")
        russian = (ROOT / "docs/ru/reference/audit-optimization.md").read_text(encoding="utf-8")
        for marker in (
            "audit-sample",
            "audit-report",
            "audit-proposal",
            "audit-apply",
            "agent-audit-optimization-report.v1",
            "holdout",
            "false",
            "Review Mesh",
        ):
            self.assertIn(marker, english)
        for marker in (
            "audit-sample",
            "audit-report",
            "audit-proposal",
            "audit-apply",
            "agent-audit-optimization-report.v1",
            "эталонн",
            "ошибочн",
            "Review Mesh",
        ):
            self.assertIn(marker, russian)
        self.assertIn("../ru/reference/audit-optimization.md", english)
        self.assertIn("https://github.com/avksp/agent-lifecycle-kit/blob/main/docs/reference/audit-optimization.md", russian)

    def test_cli_and_support_indexes_link_the_new_reference(self) -> None:
        for relative_path in (
            "docs/README.md",
            "docs/ru/README.md",
            "docs/reference/cli.md",
            "docs/ru/reference/cli.md",
            "docs/adapters/support-matrix.md",
            "docs/ru/adapters/support-matrix.md",
        ):
            content = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn("audit-optimization", content, relative_path)


if __name__ == "__main__":
    unittest.main()
