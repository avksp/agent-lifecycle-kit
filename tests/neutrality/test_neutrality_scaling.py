from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.neutrality.git_objects import iter_git_objects
from agent_lifecycle.neutrality.matching import build_literal_matcher
from agent_lifecycle.neutrality.policy import load_policy
from agent_lifecycle.neutrality.scanner import scan_repository


class NeutralityScalingTests(unittest.TestCase):
    def test_multi_pattern_matcher_preserves_simple_rule_order_and_duplicates(self) -> None:
        rules = tuple([f"rule-{index}" for index in range(70)] + ["rule-3", "rule-3"])
        text = "prefix rule-3 and rule-69 suffix"
        simple = build_literal_matcher(rules[:64])
        multi = build_literal_matcher(rules)
        self.assertEqual(simple.matching_indices(text), [3, 6])
        self.assertEqual(multi.matching_indices(text), [3, 6, 69, 70, 71])

    def test_full_repository_batch_matches_cat_file_pretty_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git(root, "init")
            self._git(root, "config", "user.email", "alk@example.invalid")
            self._git(root, "config", "user.name", "ALK test")
            (root / "a.txt").write_text("portable\n", encoding="utf-8")
            (root / "folder").mkdir()
            (root / "folder/b.txt").write_text("nested\n", encoding="utf-8")
            self._git(root, "add", ".")
            self._git(root, "commit", "-m", "fixture")
            policy_path = root / "policy.json"
            policy_path.write_text(
                '{"schemaVersion":"agent-lifecycle-neutrality-policy.v1","scan":{},"archives":{},"pathExcludes":[],"localArtifactRoots":[],"denyLiterals":[],"denyRegexes":[]}',
                encoding="utf-8",
            )
            objects = dict(iter_git_objects(root, load_policy(policy_path)))
            tree_id = self._git(root, "rev-parse", "HEAD^{tree}")
            expected = subprocess.run(["git", "cat-file", "-p", tree_id], cwd=root, check=True, stdout=subprocess.PIPE).stdout
            self.assertEqual(objects[tree_id], expected)
            report = scan_repository(
                workspace_root=root,
                policy=load_policy(policy_path),
                deny_literals=[],
                deny_regexes=[],
                scope="full-repository",
                output_paths=[],
            ).to_json({"operationId": "batch"})
        self.assertEqual(report["counters"]["incompleteScans"], 0)
        self.assertGreater(report["scanned"]["gitObjects"], 0)

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()
