from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest
from agent_lifecycle.planning.manifest_contract import validate_plan_manifest_contract

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/planning/fixtures/canonical-plan-manifest.v1.json"


class ManifestContractTests(unittest.TestCase):
    def test_plan_review_round_budget_is_bounded_and_boolean_safe(self) -> None:
        for value in (True, False, 0, -1, 11):
            with self.subTest(value=value):
                manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
                manifest["orchestration"] = {"maxPlanReviewRounds": value}
                self.assertIn("plan-review-round-budget-invalid", _codes(validate_plan_manifest_contract(manifest)))
        for value in (1, 10):
            with self.subTest(value=value):
                manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
                manifest["orchestration"] = {"maxPlanReviewRounds": value}
                self.assertNotIn("plan-review-round-budget-invalid", _codes(validate_plan_manifest_contract(manifest)))

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

    def test_enabled_remediation_requires_two_bounded_attempts(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["orchestration"] = {"remediationMode": "ask", "maxTaskAttempts": 1}
        result = validate_plan_manifest_contract(manifest)
        self.assertIn("plan-remediation-attempt-budget-too-low", _codes(result))

        manifest["orchestration"]["maxTaskAttempts"] = 2
        self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")

    def test_attempt_budget_rejects_boolean_and_unbounded_values(self) -> None:
        for attempts in (True, 0, 11):
            manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
            manifest["orchestration"] = {"remediationMode": "off", "maxTaskAttempts": attempts}
            result = validate_plan_manifest_contract(manifest)
            self.assertIn("plan-task-attempt-budget-invalid", _codes(result))

    def test_validation_ladder_fields_are_closed(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        command = manifest["validation"]["commands"][0]
        checks = [{"id": "full", "commandDigest": canonical_digest(command)}]
        catalog_body = {"schemaVersion": "agent-validation-check-catalog.v1", "checks": checks}
        manifest["validation"].update(
            {
                "checkCatalog": {**catalog_body, "catalogDigest": canonical_digest(catalog_body)},
                "validationLadderProfile": {"path": "profiles/validation.json", "digest": "1" * 64},
            }
        )

        self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")
        manifest["validation"]["checkCatalog"]["command"] = command
        self.assertIn("plan-manifest-field-unknown", _codes(validate_plan_manifest_contract(manifest)))

    def test_implementation_audit_policy_is_optional_and_closed(self) -> None:
        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")

        manifest["implementationAudit"] = {"required": True, "finalRequired": True}
        self.assertEqual(validate_plan_manifest_contract(manifest)["status"], "PASS")

        manifest["implementationAudit"]["reviewerMaySelfCertify"] = True
        self.assertIn("plan-manifest-field-unknown", _codes(validate_plan_manifest_contract(manifest)))

    def test_implementation_audit_policy_requires_booleans_and_task_audits_for_final(self) -> None:
        for field, code in (
            ("required", "plan-implementation-audit-required-invalid"),
            ("finalRequired", "plan-implementation-audit-final-required-invalid"),
        ):
            with self.subTest(field=field):
                manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
                manifest["implementationAudit"] = {"required": True, "finalRequired": True}
                manifest["implementationAudit"][field] = 1
                self.assertIn(code, _codes(validate_plan_manifest_contract(manifest)))

        manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        manifest["implementationAudit"] = {"required": False, "finalRequired": True}
        self.assertIn(
            "plan-implementation-audit-final-without-task",
            _codes(validate_plan_manifest_contract(manifest)),
        )


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["blockers"]}


if __name__ == "__main__":
    unittest.main()
