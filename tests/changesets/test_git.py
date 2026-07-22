from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.changesets import changed_files  # noqa: E402


class GitChangedFilesTests(unittest.TestCase):
    def test_changed_files_reports_staged_unstaged_and_untracked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init")
            (root / "staged.txt").write_text("staged\n", encoding="utf-8")
            _git(root, "add", "staged.txt")
            (root / "staged.txt").write_text("staged updated\n", encoding="utf-8")
            (root / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            self.assertEqual(changed_files(root), ["staged.txt", "untracked.txt"])


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
