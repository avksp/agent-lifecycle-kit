from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.launcher import launch_from_descriptor


class SecureAdapterLauncherTests(unittest.TestCase):
    def test_supported_profile_is_blocked_before_process_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "launched.txt"
            descriptor = _descriptor(argv=[sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('launched')"])

            receipt = launch_from_descriptor(
                descriptor=descriptor,
                session_id="session-1",
                launch_mode="interactive",
                process_env={"SAFE_TOKEN": "secret", "OTHER": "no"},
            )

            self.assertFalse(marker.exists())

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["shell"])
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertEqual(receipt["argv"], [])
        self.assertIn("adapter-generic-launch-disabled", {item["code"] for item in receipt["blockers"]})

    def test_wrapper_only_profile_blocks_native_launch(self) -> None:
        descriptor = _descriptor(status="WRAPPER_ONLY", reason="wrapper required")

        receipt = launch_from_descriptor(descriptor=descriptor, session_id="session-1", launch_mode="interactive")

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertIn("adapter-generic-launch-disabled", {item["code"] for item in receipt["blockers"]})

    def test_invalid_profile_returns_structured_blocker(self) -> None:
        receipt = launch_from_descriptor(
            descriptor={"adapterId": "codex", "managedLaunch": {"status": "SUPPORTED"}},
            session_id="session-1",
            launch_mode="interactive",
        )

        self.assertEqual(receipt["status"], "BLOCKED")
        codes = {item["code"] for item in receipt["blockers"]}
        self.assertIn("adapter-generic-launch-invalid-descriptor", codes)
        self.assertIn("adapter-generic-launch-disabled", codes)


def _descriptor(*, argv: list[str] | None = None, status: str = "SUPPORTED", reason: str | None = None) -> dict:
    profile = {
        "status": status,
        "reason": reason,
        "shell": False,
        "timeoutSeconds": 5.0,
        "env": {"allow": ["SAFE_TOKEN"], "allowPatterns": [], "projectPolicyAllowed": False},
        "writesNativeConfig": False,
        "promptInjectionDefault": False,
    }
    if status == "SUPPORTED":
        profile["argvTemplates"] = {"interactive": argv or [sys.executable, "-c", ""], "managedTask": argv or [sys.executable, "-c", ""], "resume": argv or [sys.executable, "-c", ""]}
    return {"adapterId": "codex", "managedLaunch": profile}


if __name__ == "__main__":
    unittest.main()
