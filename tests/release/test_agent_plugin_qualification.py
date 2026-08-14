from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import read_json_object
from agent_lifecycle.host_protocol.agent_plugin_qualification import build_offline_qualification_receipt
from tools.release.validate_agent_plugin_profiles import validate_profiles
from tools.release.validate_agent_plugin_qualification import main as offline_main


ROOT = Path(__file__).resolve().parents[2]


class AgentPluginQualificationReleaseTests(unittest.TestCase):
    def test_profile_release_validator_covers_three_clients(self) -> None:
        result = validate_profiles([ROOT / "adapters" / adapter / "agent_plugin_profile.json" for adapter in ("codex", "claude", "cursor")])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["checks"]), 3)

    def test_offline_receipt_has_no_host_authority(self) -> None:
        profile = read_json_object(ROOT / "adapters/codex/agent_plugin_profile.json")
        receipt = build_offline_qualification_receipt(
            package_root=ROOT / "skills",
            profile=profile,
            package_result={"status": "FAIL", "blockers": [{"code": "test-only"}], "skillNames": []},
        )
        self.assertEqual(receipt["status"], "BLOCKED")
        self.assertFalse(receipt["managedLaunchProofClaimed"])
        self.assertFalse(receipt["modelCallsStarted"])


if __name__ == "__main__":
    unittest.main()
