from __future__ import annotations

import sys
import unittest

from agent_lifecycle.adapter_sessions.launcher import launch_from_descriptor


class SecureAdapterLauncherTests(unittest.TestCase):
    def test_supported_profile_launches_with_argv_and_redacted_env(self) -> None:
        descriptor = _descriptor(argv=[sys.executable, "-c", "print('ok')"])

        receipt = launch_from_descriptor(
            descriptor=descriptor,
            session_id="session-1",
            launch_mode="interactive",
            process_env={"SAFE_TOKEN": "secret", "OTHER": "no"},
        )

        self.assertEqual(receipt["status"], "PASS")
        self.assertFalse(receipt["shell"])
        self.assertTrue(receipt["hostLaunchStarted"])
        self.assertEqual(receipt["env"]["includedNames"], ["SAFE_TOKEN"])
        self.assertTrue(receipt["env"]["valuesRedacted"])
        self.assertIn("ok", receipt["stdout"]["tail"])

    def test_wrapper_only_profile_blocks_native_launch(self) -> None:
        descriptor = _descriptor(status="WRAPPER_ONLY", reason="wrapper required")

        receipt = launch_from_descriptor(descriptor=descriptor, session_id="session-1", launch_mode="interactive")

        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["hostLaunchStarted"])
        self.assertIn("adapter-managed-launch-unsupported", {item["code"] for item in receipt["blockers"]})


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
