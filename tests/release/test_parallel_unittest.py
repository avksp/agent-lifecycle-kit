"""Exercise immutable fixture seed isolation while preserving live authority checks."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError
from tests.workflow.limited_usage_fixture_support import git_seed, install_git_seed
from tests.workflow.test_limited_usage import BASE, DeclaredFixture


class DeclaredFixtureIsolationTests(unittest.TestCase):
    def test_only_git_seed_bytes_are_reused_and_mutable_authority_is_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            roots = [parent / name for name in ("first", "second")]
            for root in roots:
                root.mkdir()
            first, second = (DeclaredFixture(root) for root in roots)
            before = second.snapshot()
            self.assertIsNot(first.state, second.state)
            self.assertIsNot(first.policy, second.policy)
            first.state["runId"] = "mutated-first-only"
            self.assertEqual(second.state["runId"], "run")
            first.append_window(398)
            self.assertEqual(second.snapshot(), before)
            for name in ("run.state.json", first.admission_ref["path"], BASE + "/COORDINATOR-COST-HEAD.json"):
                self.assertFalse((roots[0] / name).samefile(roots[1] / name))
            original = next(path for path in (roots[0] / ".git/objects").glob("*/*") if path.is_file())
            self.assertFalse(original.samefile(roots[1] / original.relative_to(roots[0])))
            (roots[0] / "src/example.py").write_bytes(b"value = 99\n")
            subprocess.run(["git", "add", "src/example.py"], cwd=roots[0], check=True)
            subprocess.run(["git", "commit", "-qm", "first root mutation"], cwd=roots[0], check=True)
            self.assertEqual((roots[1] / "src/example.py").read_bytes(), b"value = 1\n")
            self.assertNotEqual(
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=roots[0], text=True).strip(), second.revision
            )
            self.assertEqual(
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=roots[1], text=True).strip(), second.revision
            )
            revision, files, elapsed = git_seed()
            self.assertEqual(revision, second.revision)
            self.assertGreaterEqual(elapsed, 0)
            self.assertTrue(all(isinstance(data, bytes) for _, data in files))
            self.assertFalse(any(name.startswith(("work/", "tasks/", "run.state")) for name, _ in files))

    def test_reused_git_seed_does_not_replace_live_identity_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = DeclaredFixture(root)
            (root / ".git").rename(root / "removed-git")
            with self.assertRaises(LifecycleError):
                fixture.snapshot()

    def test_seed_installation_refuses_to_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "unrelated.txt"
            marker.write_bytes(b"retain")
            with self.assertRaises(ValueError):
                install_git_seed(root)
            self.assertEqual(marker.read_bytes(), b"retain")
            self.assertFalse((root / ".git").exists())


if __name__ == "__main__":
    unittest.main()
