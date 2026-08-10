from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.launcher import capture_git_worktree_identity
from agent_lifecycle.adapter_sessions.local_launch_profile import (
    render_planning_launch_argv,
    validate_local_launch_profile,
)
from agent_lifecycle.adapter_sessions.qualification import (
    build_qualification_receipt,
    load_shipped_launch_profile,
    planning_support_status,
)

ROOT = Path(__file__).resolve().parents[2]


class PlanningLaunchProfileTests(unittest.TestCase):
    def test_profiles_are_independent_and_fail_closed(self) -> None:
        expected = {
            "codex": ("CANDIDATE", "PLANNING_ONLY_UNSUPPORTED"),
            "claude": ("CANDIDATE", "PLANNING_ONLY_UNSUPPORTED"),
            "opencode": ("UNSUPPORTED", "PLANNING_ONLY_UNSUPPORTED"),
        }
        for adapter_id, (profile_status, support_status) in expected.items():
            with self.subTest(adapter=adapter_id):
                profile = load_shipped_launch_profile(adapter_id, repository_root=ROOT)
                descriptor = json.loads(
                    (ROOT / f"adapters/{adapter_id}/adapter.descriptor.json").read_text(encoding="utf-8")
                )
                self.assertEqual(validate_local_launch_profile(profile)["status"], "PASS")
                self.assertEqual(profile["planningOnly"]["status"], profile_status)
                self.assertEqual(planning_support_status(profile), support_status)
                self.assertEqual(descriptor["qualifiedLaunch"]["planningSupportStatus"], support_status)

    def test_candidate_argv_is_stdin_only_and_rejects_dangerous_flags(self) -> None:
        codex = load_shipped_launch_profile("codex", repository_root=ROOT)
        argv = render_planning_launch_argv(codex)
        self.assertEqual(argv[-1], "-")
        self.assertIn("read-only", argv)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", argv)

        invalid = copy.deepcopy(codex)
        invalid["planningOnly"]["argvTemplate"].append("--dangerously-bypass-approvals-and-sandbox")
        validation = validate_local_launch_profile(invalid)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("planning-launch-dangerous-flag", {item["code"] for item in validation["blockers"]})

    def test_generic_preflight_receipt_carries_additive_planning_status(self) -> None:
        profile = load_shipped_launch_profile("codex", repository_root=ROOT)
        probe = {
            "status": "PASS",
            "stdout": {"tail": "codex-cli 0.147.0"},
            "stderr": {"tail": ""},
            "receiptDigest": "a" * 64,
        }
        receipt = build_qualification_receipt(
            profile=profile,
            profile_digest="b" * 64,
            probe_receipt=probe,
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["planningSupportStatus"], "PLANNING_ONLY_UNSUPPORTED")

    def test_git_identity_supports_dirty_baseline_and_detects_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git(root, "init")
            self._git(root, "config", "user.email", "alk@example.invalid")
            self._git(root, "config", "user.name", "ALK test")
            tracked = root / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            self._git(root, "add", "tracked.txt")
            self._git(root, "commit", "-m", "base")
            tracked.write_text("dirty before\n", encoding="utf-8")
            (root / "untracked.txt").write_text("local\n", encoding="utf-8")

            before = capture_git_worktree_identity(root)
            same = capture_git_worktree_identity(root)
            tracked.write_text("dirty after\n", encoding="utf-8")
            after = capture_git_worktree_identity(root)

        self.assertEqual(before["identityDigest"], same["identityDigest"])
        self.assertNotEqual(before["identityDigest"], after["identityDigest"])
        self.assertEqual(before["untrackedCount"], 1)

    @staticmethod
    def _git(root: Path, *args: str) -> None:
        import subprocess

        subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


if __name__ == "__main__":
    unittest.main()
