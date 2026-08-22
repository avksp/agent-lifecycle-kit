from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/planning/fixtures/canonical-plan-manifest.v1.json"


class ManifestContractTests(unittest.TestCase):
    def test_canonical_fixture_passes(self) -> None:
        result = validate_plan_manifest_contract(json.loads(FIXTURE.read_text(encoding="utf-8")))
        self.assertEqual(result["status"], "PASS")

    def test_unknown_top_level_field_is_rejected(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["integrationSeams"] = []
        result = validate_plan_manifest_contract(manifest)
        self.assertIn("plan-manifest-authority-field-unknown", _codes(result))

    def test_unknown_nested_authority_field_is_rejected(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["workstreams"][0]["forbiddenWriteExceptions"] = []
        result = validate_plan_manifest_contract(manifest)
        self.assertIn("plan-manifest-authority-field-unknown", _codes(result))

    def test_authority_bearing_extension_is_rejected(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["extensions"] = {"x-review": {"writes": ["src"]}}
        result = validate_plan_manifest_contract(manifest)
        self.assertIn("plan-manifest-extension-authority", _codes(result))

    def test_package_integrity_cannot_weaken_v2(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["packageIntegrity"]["inventorySource"] = "discovered"
        result = validate_plan_manifest_contract(manifest)
        self.assertIn("plan-manifest-inventory-source-invalid", _codes(result))


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


if __name__ == "__main__":
    unittest.main()
