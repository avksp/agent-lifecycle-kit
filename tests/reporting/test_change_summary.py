from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.reporting import build_change_summary_receipt


class ChangeSummaryTests(unittest.TestCase):
    def test_change_summary_matches_git_style_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            _git(root, "config", "user.email", "test@example.com")
            _git(root, "config", "user.name", "Test User")
            (root / "a.txt").write_text("one\n", encoding="utf-8")
            (root / "b.txt").write_text("remove\n", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-m", "initial")

            (root / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
            (root / "c.txt").write_text("new\n", encoding="utf-8")
            _git(root, "add", "c.txt")
            _git(root, "rm", "b.txt")

            summary = build_change_summary_receipt(project_root=root)

        self.assertEqual(summary["schemaVersion"], "agent-change-summary-receipt.v1")
        self.assertEqual(summary["filesChanged"], 3)
        self.assertEqual(summary["insertions"], 2)
        self.assertEqual(summary["deletions"], 1)
        self.assertEqual(summary["modified"], 1)
        self.assertEqual(summary["added"], 1)
        self.assertEqual(summary["deleted"], 1)
        self.assertIn("3 files changed", summary["line"])
        self.assertTrue(summary["readOnly"])
        self.assertFalse(summary["modelCallsStarted"])


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
