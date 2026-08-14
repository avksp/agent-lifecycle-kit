from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, read_json_object
from agent_lifecycle.contracts.agent_plugin_qualification_schemas import validate_qualification_profile


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginProfileValidationTests(unittest.TestCase):
    def test_all_shipped_profiles_are_supported_without_launch_promotion(self) -> None:
        for adapter in ("codex", "claude", "cursor"):
            profile = read_json_object(ROOT / "adapters" / adapter / "agent_plugin_profile.json")
            self.assertEqual(validate_qualification_profile(profile)["status"], "PASS")
            self.assertFalse(profile["qualification"]["managedLaunchProof"])
            self.assertTrue(profile["descriptorBoundary"]["managedLaunchReadOnly"])

    def test_reported_version_policy_is_explicit_and_bounded_to_observation(self) -> None:
        profile = read_json_object(ROOT / "adapters" / "codex" / "agent_plugin_profile.json")
        self.assertEqual(profile["hostVersionPolicy"], {"mode": "reported", "accepted": "any-version"})
        for policy, expected_code in (
            ({"mode": "reported", "accepted": "promote-any-version"}, "profile-host-version-policy-reported-invalid"),
            ({"mode": "exact", "accepted": "1.68.0"}, "profile-host-version-policy-unsupported"),
            ({"mode": "range", "accepted": "1.68.x"}, "profile-host-version-policy-unsupported"),
        ):
            invalid = deepcopy(profile)
            invalid["hostVersionPolicy"] = policy
            invalid["profileDigest"] = canonical_digest({key: value for key, value in invalid.items() if key != "profileDigest"})
            result = validate_qualification_profile(invalid)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn(expected_code, {item["code"] for item in result["blockers"]})

        tampered = deepcopy(profile)
        tampered["qualification"] = dict(profile["qualification"])
        tampered["qualification"]["maxProcesses"] = 3
        result = validate_qualification_profile(tampered)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("profile-digest-mismatch", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
