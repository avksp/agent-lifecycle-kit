from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.project.profile import normalize_project_profile
from tests.project.test_profile import _profile


class ThreadBridgeProfileTests(unittest.TestCase):
    def test_profile_can_opt_into_bounded_read_bridge(self) -> None:
        profile = _profile(
            threadBridge={
                "mode": "read-only",
                "operations": {
                    "read": {"enabled": True, "scope": "explicit-target", "approval": "none", "blocking": "required"},
                    "list": {"enabled": True, "scope": "project", "approval": "none", "blocking": "non-blocking"},
                    "send": {"enabled": False, "scope": "explicit-target", "approval": "operator", "blocking": "required"},
                    "create": {"enabled": False, "scope": "project", "approval": "operator", "blocking": "required"},
                },
                "phaseRules": {"research": {"read": {"enabled": True, "scope": "explicit-target"}}},
                "limits": {"maxImportedBytes": 8192, "maxImportedTokens": 512},
            }
        )

        normalized = normalize_project_profile(profile)

        self.assertEqual(normalized["threadBridge"]["mode"], "read-only")
        self.assertTrue(normalized["threadBridge"]["operations"]["read"]["enabled"])

    def test_profile_rejects_provider_and_unknown_thread_fields(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "sensitive"):
            normalize_project_profile(_profile(threadBridge={"provider": "host"}))

        with self.assertRaisesRegex(LifecycleError, "invalid"):
            normalize_project_profile(_profile(threadBridge={"mode": "off", "operations": {}, "phaseRules": {}, "limits": {}, "extra": 1}))


if __name__ == "__main__":
    unittest.main()
