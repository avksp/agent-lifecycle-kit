from __future__ import annotations

import hashlib
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_lifecycle.adapter_sessions.worktree_identity as identity
from agent_lifecycle.adapter_sessions.worktree_identity import (
    capture_git_worktree_identity,
)
from agent_lifecycle.changesets.snapshot import capture_task_change_set
from agent_lifecycle.contracts import LifecycleError, canonical_digest


class WorktreeIdentityTests(unittest.TestCase):
    def test_textconv_is_never_invoked_and_raw_content_remains_distinguishable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outer = Path(tmp)
            root = outer / "repository"
            root.mkdir()
            marker = outer / "driver-called"
            driver = outer / "textconv probe.py"
            driver.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('called')\nprint('same view')\n")
            self._git(root, "init")
            self._git(root, "config", "user.email", "alk@example.invalid")
            self._git(root, "config", "user.name", "ALK fixture")
            command = shlex.quote(sys.executable.replace("\\", "/")) + " " + shlex.quote(driver.as_posix())
            self._git(root, "config", "diff.alkfixture.textconv", command)
            (root / ".gitattributes").write_text("*.txt diff=alkfixture\n")
            tracked = root / "tracked.txt"
            tracked.write_text("baseline\n")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "fixture")
            tracked.write_text("first raw revision\n")
            self._git(root, "diff", "--textconv", "--", "tracked.txt")
            self.assertTrue(marker.exists())
            marker.unlink()
            for staged in (False, True):
                with self.subTest(staged=staged):
                    identities, snapshots = [], []
                    for contents in ("first raw revision\n", "second raw revision\n"):
                        tracked.write_text(contents)
                        if staged:
                            self._git(root, "add", "tracked.txt")
                        identities.append(capture_git_worktree_identity(root))
                        snapshots.append(capture_task_change_set(root, baseline="HEAD", write_paths=["tracked.txt"]))
                    self.assertFalse(marker.exists())
                    self.assertNotEqual(identities[0], identities[1])
                    self.assertNotEqual(snapshots[0]["diffHash"], snapshots[1]["diffHash"])

    def test_large_untracked_file_is_hashed_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git(root, "init")
            self._git(root, "config", "user.email", "alk@example.invalid")
            self._git(root, "config", "user.name", "ALK test")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "base")
            payload = b"abcde" * 1000
            (root / "large.bin").write_bytes(payload)
            with patch.object(identity, "MAX_HASH_CHUNK_BYTES", 7):
                result = capture_git_worktree_identity(root)
        self.assertEqual(result["untrackedBytes"], len(payload))
        self.assertEqual(result["untrackedCount"], 1)
        expected_row = {
            "pathBytesSha256": hashlib.sha256(b"large.bin").hexdigest(),
            "kind": "file",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        self.assertEqual(result["untrackedTreeSha256"], canonical_digest({"entries": [expected_row]}))

    def test_untracked_byte_limit_fails_without_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git(root, "init")
            self._git(root, "config", "user.email", "alk@example.invalid")
            self._git(root, "config", "user.name", "ALK test")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "base")
            (root / "large.bin").write_bytes(b"x" * 32)
            with patch.object(identity, "MAX_UNTRACKED_BYTES", 16), self.assertRaises(LifecycleError) as raised:
                capture_git_worktree_identity(root)
        self.assertEqual(raised.exception.code, "planning-worktree-untracked-limit")

    def test_symlink_hashes_link_text_and_special_file_is_rejected(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX special-file fixture")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git(root, "init")
            self._git(root, "config", "user.email", "alk@example.invalid")
            self._git(root, "config", "user.name", "ALK test")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "base")
            (root / "target.txt").write_text("target\n", encoding="utf-8")
            (root / "link").symlink_to("target.txt")
            result = capture_git_worktree_identity(root)
            expected_rows = [
                {
                    "pathBytesSha256": hashlib.sha256(name.encode()).hexdigest(),
                    "kind": "symlink" if name == "link" else "file",
                    "bytes": len(b"target.txt") if name == "link" else len(b"target\n"),
                    "sha256": hashlib.sha256(b"target.txt").hexdigest() if name == "link" else hashlib.sha256(b"target\n").hexdigest(),
                }
                for name in ("link", "target.txt")
            ]
            self.assertEqual(result["untrackedTreeSha256"], canonical_digest({"entries": expected_rows}))
            os.mkfifo(root / "pipe")
            real_git_bytes = identity._git_bytes

            def fake_git_bytes(current_root: Path, args: list[str], deadline: float) -> bytes:
                if args[:2] == ["ls-files", "--others"]:
                    return b"pipe\0"
                return real_git_bytes(current_root, args, deadline)

            with patch.object(identity, "_git_bytes", side_effect=fake_git_bytes), self.assertRaises(LifecycleError) as raised:
                capture_git_worktree_identity(root)
        self.assertEqual(raised.exception.code, "planning-worktree-special-file")

    @staticmethod
    def _git(root: Path, *args: str) -> None:
        import subprocess

        subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if __name__ == "__main__":
    unittest.main()
