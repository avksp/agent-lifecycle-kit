from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.launcher import launch_from_local_profile
from agent_lifecycle.adapter_sessions.qualification import load_shipped_launch_profile

ROOT = Path(__file__).resolve().parents[2]


class PlanningLaunchQualificationTests(unittest.TestCase):
    def test_unqualified_candidate_blocks_before_host_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".alk/host-launch/codex.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(load_shipped_launch_profile("codex", repository_root=ROOT)),
                encoding="utf-8",
            )
            receipt = launch_from_local_profile(
                profile_path=path,
                operation="planningTask",
                adapter_id="codex",
                session_id="session-1",
                project_root=root,
                explicit_launch=True,
                requested_mode="plan",
                task_text="inspect only",
            )

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertEqual(receipt["processCalls"], 0)
        self.assertIn("planning-launch-qualification-required", {item["code"] for item in receipt["blockers"]})

    def test_explicit_launch_is_required_before_qualification_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".alk/host-launch/codex.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(load_shipped_launch_profile("codex", repository_root=ROOT)),
                encoding="utf-8",
            )
            receipt = launch_from_local_profile(
                profile_path=path,
                operation="planningTask",
                project_root=root,
                requested_mode="plan",
                task_text="inspect only",
            )

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertEqual(receipt["blockers"][0]["code"], "planning-launch-explicit-flag-required")


if __name__ == "__main__":
    unittest.main()
