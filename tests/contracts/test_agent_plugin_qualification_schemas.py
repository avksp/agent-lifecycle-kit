from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest, read_json_object, write_json_create
from agent_lifecycle.contracts.agent_plugin_qualification_schemas import (
    build_qualification_receipt,
    validate_qualification_profile,
    validate_qualification_receipt,
)

ROOT = Path(__file__).resolve().parents[2]


class AgentPluginQualificationSchemaTests(unittest.TestCase):
    def test_shipped_profiles_are_digest_bound(self) -> None:
        for adapter in ("codex", "claude", "cursor"):
            profile = read_json_object(ROOT / "adapters" / adapter / "agent_plugin_profile.json")
            self.assertEqual(validate_qualification_profile(profile)["status"], "PASS")

    def test_receipt_states_and_digest_are_validated(self) -> None:
        profile = read_json_object(ROOT / "adapters" / "codex" / "agent_plugin_profile.json")
        receipt = build_qualification_receipt(
            profile=profile,
            status="OFFLINE_VALIDATED",
            package_version="1.68.0",
            package_digest="a" * 64,
            package_skill_count=7,
            checks=[{"name": "offline", "status": "PASS"}],
        )
        self.assertEqual(validate_qualification_receipt(receipt)["status"], "PASS")
        tampered = {**receipt, "packageVersion": "1.67.0"}
        self.assertEqual(validate_qualification_receipt(tampered)["status"], "FAIL")
        tampered_digest = {**receipt, "packageDigest": "c" * 64}
        self.assertEqual(validate_qualification_receipt(tampered_digest)["status"], "FAIL")

    def test_receipts_are_write_once_at_the_artifact_boundary(self) -> None:
        profile = read_json_object(ROOT / "adapters" / "codex" / "agent_plugin_profile.json")
        receipt = build_qualification_receipt(
            profile=profile,
            status="OFFLINE_VALIDATED",
            package_version="1.68.0",
            package_digest="b" * 64,
            package_skill_count=7,
            checks=[],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            write_json_create(path, receipt)
            with self.assertRaises(FileExistsError):
                write_json_create(path, receipt)

    def test_multiple_invalid_sections_keep_blocker_order_and_fields(self) -> None:
        result = validate_qualification_profile({})
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            [item["code"] for item in result["blockers"]],
            ["schema-version-mismatch"]
            + ["profile-field-invalid"] * 4
            + [
                "profile-package-invalid",
                "profile-discovery-invalid",
                "profile-installation-invalid",
                "profile-environment-invalid",
                "profile-host-version-policy-invalid",
                "profile-qualification-invalid",
                "profile-descriptor-boundary",
                "profile-digest-mismatch",
            ],
        )
        self.assertEqual(
            [item["field"] for item in result["blockers"][1:5]], ["profileId", "adapterId", "client", "host"]
        )
        self.assertIsNone(result["checkedDigest"])
        self.assertFalse(result["productionPromotionClaimed"])

    def test_valid_sections_still_accumulate_ordered_negative_boundaries(self) -> None:
        profile = read_json_object(ROOT / "adapters/codex/agent_plugin_profile.json")
        profile["package"]["name"] = "unexpected"
        profile["installation"]["automatic"] = True
        profile["environment"]["allowPatterns"] = ["*"]
        profile["qualification"]["modelCalls"] = 1
        profile["managedLaunch"] = {}
        profile["profileDigest"] = canonical_digest({k: v for k, v in profile.items() if k != "profileDigest"})
        result = validate_qualification_profile(profile)
        self.assertEqual(
            [item["code"] for item in result["blockers"]],
            [
                "profile-package-name",
                "profile-installation-boundary",
                "profile-environment-wildcard",
                "profile-qualification-safety",
                "profile-descriptor-override",
            ],
        )
        self.assertEqual(result["checkedDigest"], profile["profileDigest"])


if __name__ == "__main__":
    unittest.main()
