from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.adapter_sessions.env import resolve_launch_env


class AdapterSessionEnvPolicyTests(unittest.TestCase):
    def test_env_resolution_passes_only_exact_allowlisted_names(self) -> None:
        profile = {
            "env": {
                "allow": ["ALK_ALLOWED"],
                "allowPatterns": [],
                "projectPolicyAllowed": False,
            }
        }
        env, receipt = resolve_launch_env(
            profile,
            process_env={"ALK_ALLOWED": "1", "HOST_TOKEN": "secret", "OTHER": "no"},
        )

        self.assertEqual(set(env), {"ALK_ALLOWED"})
        self.assertTrue(receipt["valuesRedacted"])
        self.assertFalse(receipt["secretValuesStored"])

    def test_env_resolution_rejects_descriptor_wildcard(self) -> None:
        profile = {"env": {"allow": [], "allowPatterns": ["HOST_*"], "projectPolicyAllowed": False}}

        with self.assertRaisesRegex(Exception, "exact environment variable names") as caught:
            resolve_launch_env(profile, process_env={"HOST_TOKEN": "secret"})

        self.assertEqual(caught.exception.code, "adapter-env-wildcard-disallowed")

    def test_project_policy_extends_names_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "env-policy.json"
            policy.write_text(json.dumps({"allow": ["PROJECT_KEY"], "allowPatterns": []}), encoding="utf-8")
            profile = {"env": {"allow": [], "allowPatterns": [], "projectPolicyAllowed": True}}

            env, receipt = resolve_launch_env(profile, policy_path=policy, process_env={"PROJECT_KEY": "secret"})

        self.assertEqual(env, {"PROJECT_KEY": "secret"})
        self.assertEqual(receipt["includedNames"], ["PROJECT_KEY"])
        self.assertFalse(receipt["secretValuesStored"])

    def test_project_policy_rejects_wildcard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "env-policy.json"
            policy.write_text(json.dumps({"allow": [], "allowPatterns": ["HOST_*"]}), encoding="utf-8")
            profile = {"env": {"allow": [], "allowPatterns": [], "projectPolicyAllowed": True}}

            with self.assertRaisesRegex(Exception, "exact environment variable names") as caught:
                resolve_launch_env(profile, policy_path=policy, process_env={"HOST_TOKEN": "secret"})

        self.assertEqual(caught.exception.code, "adapter-env-wildcard-disallowed")


if __name__ == "__main__":
    unittest.main()
