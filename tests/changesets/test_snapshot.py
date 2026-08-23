from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.changesets import capture_task_change_set, require_current_task_change_set
from agent_lifecycle.contracts import LifecycleError


class TaskChangeSetSnapshotTests(unittest.TestCase):
    def test_snapshot_is_task_scoped_and_detects_content_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            baseline = _git(root, "rev-parse", "HEAD")
            (root / "src/task.py").write_text("value = 2\n", encoding="utf-8")
            (root / "other.txt").write_text("outside\n", encoding="utf-8")

            evidence = capture_task_change_set(root, baseline=baseline, write_paths=["src"])
            result = {
                "changedFiles": evidence["changedFiles"],
                "changeSet": {
                    "schemaVersion": "agent-task-change-set-claim.v1",
                    **{
                        key: evidence[key]
                        for key in ("provider", "baselineSha", "fileSetHash", "diffHash", "snapshotHash")
                    },
                },
            }
            require_current_task_change_set(result, evidence)
            self.assertEqual(evidence["changedFiles"], ["src/task.py"])
            self.assertEqual(evidence["allChangedFiles"], ["other.txt", "src/task.py"])

            (root / "src/task.py").write_text("value = 3\n", encoding="utf-8")
            current = capture_task_change_set(root, baseline=baseline, write_paths=["src"])
            with self.assertRaises(LifecycleError) as raised:
                require_current_task_change_set(result, current)
            self.assertEqual(raised.exception.code, "task-result-stale-snapshot")

    def test_snapshot_handles_spaces_with_nul_delimited_git_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            baseline = _git(root, "rev-parse", "HEAD")
            target = root / "src/path with space.py"
            target.write_text("value = 1\n", encoding="utf-8")

            evidence = capture_task_change_set(root, baseline=baseline, write_paths=["src"])

            self.assertEqual(evidence["changedFiles"], ["src/path with space.py"])


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "ALK Tests"], cwd=root, check=True)
    source = root / "src/task.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/task.py"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()
