from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_lifecycle.changesets.git_io import run_bounded_command
from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.reporting import build_change_summary_receipt
from agent_lifecycle.reporting.change_summary import _run_git


class ChangeSummaryTests(unittest.TestCase):
    def test_failed_command_redacts_full_stdout_and_stderr_before_error_tail(self) -> None:
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), tempfile.TemporaryDirectory() as tmp:
                source = f"import sys; sys.{stream}.write('api_key='+'q'*5000); raise SystemExit(7)"

                def inert_command(_argv, fixture_source=source, **kwargs):
                    return run_bounded_command([sys.executable, "-c", fixture_source], **kwargs)

                with (
                    patch("agent_lifecycle.reporting.change_summary.run_bounded_command", side_effect=inert_command),
                    self.assertRaises(LifecycleError) as raised,
                ):
                    _run_git(Path(tmp), ["diff"])
                self.assertEqual(raised.exception.code, "change-summary-git-failed")
                self.assertNotIn("q" * 30, str(raised.exception))
                self.assertIn("<redacted>", str(raised.exception))
                self.assertTrue(raised.exception.details[stream + "Redacted"])

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

    def test_option_shaped_base_and_head_fail_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            _git(root, "config", "user.email", "test@example.com")
            _git(root, "config", "user.name", "Test User")
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            _git(root, "add", "tracked.txt")
            _git(root, "commit", "-m", "initial")
            sentinel = root / "read-only-must-not-write"

            for kwargs in (
                {"base": f"--output={sentinel}"},
                {"base": "HEAD", "head": f"--output={sentinel}"},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(LifecycleError) as raised:
                    build_change_summary_receipt(project_root=root, **kwargs)
                self.assertEqual(raised.exception.code, "invalid-git-revision")

            self.assertFalse(sentinel.exists())


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
