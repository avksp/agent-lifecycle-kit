from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.cli.helpers import _run_cli


class ImportCommandTests(unittest.TestCase):
    def test_import_plan_accepts_external_dialect_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "spec.md"
            source.write_text("# Spec\n\n- Review the imported task before freeze.\n", encoding="utf-8")

            code, payload = _run_cli(["import", "plan", "--source", str(source), "--dialect", "openspec"])

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-planning-import-result.v1")
            self.assertEqual(payload["dialectProfile"]["dialectId"], "openspec-planning")
            self.assertEqual(payload["candidatePlan"]["status"], "DRAFT")

    def test_import_plan_accepts_markdown_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "02-plan.md").write_text("# Plan\n\n- Check ordering.\n", encoding="utf-8")
            (root / "01-task.md").write_text("# Task\n\n- Review this first.\n", encoding="utf-8")

            code, payload = _run_cli(["import", "plan", "--source", str(root), "--dialect", "spec-kit"])

            self.assertEqual(code, 0)
            self.assertEqual(payload["markdownCollection"]["sourceKind"], "directory")
            self.assertEqual([item["label"] for item in payload["markdownCollection"]["files"]], ["01-task.md", "02-plan.md"])
            self.assertEqual(payload["candidatePlan"]["status"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
