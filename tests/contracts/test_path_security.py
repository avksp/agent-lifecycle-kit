from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.contracts.paths import (
    normalize_git_revision,
    normalize_repo_path,
    read_stable_repository_file,
    resolve_repository_file,
)


class RepositoryPathSecurityTests(unittest.TestCase):
    def test_normalization_rejects_option_shaped_git_revision(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            normalize_git_revision("--output=/tmp/owned")
        self.assertEqual(raised.exception.code, "invalid-git-revision")

    def test_stable_read_accepts_contained_regular_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "artifact.json").write_bytes(b'{"schemaVersion":"agent-change-summary-receipt.v1"}')

            self.assertEqual(
                read_stable_repository_file(root, "artifact.json", max_bytes=1024),
                b'{"schemaVersion":"agent-change-summary-receipt.v1"}',
            )
            self.assertEqual(resolve_repository_file(root, "artifact.json"), (root / "artifact.json").resolve())

    @unittest.skipIf(os.name == "nt", "symlink fixture requires POSIX semantics")
    def test_rejects_file_symlink_even_when_target_is_inside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.json").write_text("{}", encoding="utf-8")
            link = root / "link.json"
            try:
                link.symlink_to(root / "real.json")
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            with self.assertRaises(LifecycleError) as raised:
                read_stable_repository_file(root, "link.json", max_bytes=1024)
            self.assertEqual(raised.exception.code, "repository-input-symlink")

    @unittest.skipIf(os.name == "nt", "symlink fixture requires POSIX semantics")
    def test_rejects_symlinked_directory_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            (target / "artifact.json").write_text("{}", encoding="utf-8")
            link = root / "evidence"
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            with self.assertRaises(LifecycleError) as raised:
                resolve_repository_file(root, "evidence/artifact.json")
            self.assertEqual(raised.exception.code, "repository-input-symlink")

    def test_path_aliases_and_traversal_are_rejected(self) -> None:
        for value in ("./artifact.json", "evidence/../artifact.json", "../artifact.json", "/tmp/artifact.json"):
            with self.subTest(value=value), self.assertRaises(LifecycleError):
                normalize_repo_path(value)


if __name__ == "__main__":
    unittest.main()
