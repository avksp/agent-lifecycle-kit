from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.changesets import changed_files  # noqa: E402
from agent_lifecycle.contracts import LifecycleError  # noqa: E402


class GitChangedFilesTests(unittest.TestCase):
    def test_renames_preserve_both_paths_for_every_diff_mode_and_config(self) -> None:
        for renames in ("true", "false", "copies"):
            for mode in ("staged", "unstaged", "baseline"):
                with self.subTest(renames=renames, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _git(root, "init")
                    _git(root, "config", "user.email", "test@example.com")
                    _git(root, "config", "user.name", "Test User")
                    _git(root, "config", "diff.renames", renames)
                    (root / "protected.txt").write_text("unchanged content\n", encoding="utf-8")
                    _git(root, "add", ".")
                    _git(root, "commit", "-m", "baseline")
                    (root / "protected.txt").rename(root / "allowed.txt")
                    if mode != "unstaged":
                        _git(root, "add", "-A")
                    self.assertEqual(
                        changed_files(root, base="HEAD" if mode == "baseline" else None),
                        ["allowed.txt", "protected.txt"],
                    )

    def test_copy_does_not_claim_unchanged_source_as_write(self) -> None:
        for renames in ("true", "false", "copies"):
            for mode in ("staged", "unstaged", "baseline"):
                with self.subTest(renames=renames, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    _git(root, "init")
                    _git(root, "config", "user.email", "test@example.com")
                    _git(root, "config", "user.name", "Test User")
                    _git(root, "config", "diff.renames", renames)
                    (root / "protected.txt").write_text("same content\n", encoding="utf-8")
                    _git(root, "add", ".")
                    _git(root, "commit", "-m", "baseline")
                    source = (root / "protected.txt").read_bytes()
                    (root / "copy.txt").write_bytes(source)
                    if mode != "unstaged":
                        _git(root, "add", ".")
                    self.assertEqual(changed_files(root, base="HEAD" if mode == "baseline" else None), ["copy.txt"])
                    self.assertEqual((root / "protected.txt").read_bytes(), source)

    def test_changed_files_reports_staged_unstaged_and_untracked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            (root / "staged.txt").write_text("staged\n", encoding="utf-8")
            _git(root, "add", "staged.txt")
            (root / "staged.txt").write_text("staged updated\n", encoding="utf-8")
            (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            self.assertEqual(changed_files(root), ["staged.txt", "untracked.txt"])

    def test_option_shaped_revision_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            _git(root, "config", "user.email", "test@example.com")
            _git(root, "config", "user.name", "Test User")
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
            _git(root, "add", "tracked.txt")
            _git(root, "commit", "-m", "initial")
            sentinel = root / "read-only-must-not-write"

            with self.assertRaises(LifecycleError) as raised:
                changed_files(root, base=f"--output={sentinel}")

            self.assertEqual(raised.exception.code, "invalid-git-revision")
            self.assertFalse(sentinel.exists())

    def test_missing_revision_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            with self.assertRaises(LifecycleError) as raised:
                changed_files(root, base="does-not-exist")
            self.assertEqual(raised.exception.code, "invalid-git-revision")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
