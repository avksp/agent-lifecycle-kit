from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.host_protocol import validate_adapter_descriptor
from agent_lifecycle.host_protocol.validation import validate_installation_facts, validate_managed_launch_profile

ROOT = Path(__file__).resolve().parents[2]


class AdapterLaunchProfileTests(unittest.TestCase):
    def test_current_adapters_declare_truthful_managed_launch_profiles(self) -> None:
        for descriptor_path in sorted((ROOT / "adapters").glob("*/adapter.descriptor.json")):
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            with self.subTest(path=descriptor_path.relative_to(ROOT).as_posix()):
                validation = validate_adapter_descriptor(descriptor)
                profile_validation = validate_managed_launch_profile(descriptor["managedLaunch"])
                self.assertEqual(validation["status"], "PASS", validation["blockers"])
                self.assertEqual(profile_validation["status"], "PASS", profile_validation["blockers"])
                self.assertFalse(descriptor["managedLaunch"]["shell"])
                self.assertFalse(descriptor["managedLaunch"]["writesNativeConfig"])
                self.assertFalse(descriptor["managedLaunch"]["promptInjectionDefault"])

    def test_installation_facts_are_data_only(self) -> None:
        descriptor = json.loads((ROOT / "adapters/codex/adapter.descriptor.json").read_text(encoding="utf-8"))
        facts = descriptor["installation"]

        validation = validate_installation_facts(facts)

        self.assertEqual(validation["status"], "PASS", validation["blockers"])
        self.assertEqual(facts["binaryAliases"], ["codex"])
        self.assertTrue(all("command" not in item and "shell" not in item for item in facts["commands"]))

    def test_supported_launch_profile_requires_argv_templates(self) -> None:
        validation = validate_managed_launch_profile(
            {
                "status": "SUPPORTED",
                "shell": False,
                "timeoutSeconds": 5,
                "env": {"allow": [], "allowPatterns": [], "projectPolicyAllowed": False},
                "writesNativeConfig": False,
                "promptInjectionDefault": False,
            }
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("adapter-managed-launch-argv", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
