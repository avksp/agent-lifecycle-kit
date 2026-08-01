from __future__ import annotations

import unittest

from agent_lifecycle.imports import (
    external_dialect_profile,
    external_dialect_registry,
    require_external_profile_pass,
    validate_external_dialect_profile,
)


class ExternalDialectFrameworkTests(unittest.TestCase):
    def test_profile_registry_lists_generic_families_as_untrusted(self) -> None:
        registry = external_dialect_registry()

        self.assertEqual(registry["schemaVersion"], "agent-external-dialect-profile-registry.v1")
        self.assertFalse(registry["enabledByDefault"])
        self.assertEqual(registry["families"], ["workflow", "agent"])
        self.assertTrue(all(item["freezeBlocked"] for item in registry["profiles"]))

    def test_external_profile_uses_existing_import_profile_contract(self) -> None:
        profile = external_dialect_profile("workflow")
        validation = validate_external_dialect_profile(profile)

        self.assertEqual(require_external_profile_pass(validation)["status"], "PASS")
        self.assertEqual(profile["schemaVersion"], "agent-import-dialect-profile.v1")
        self.assertEqual(profile["dialectId"], "external-workflow-generic")
        self.assertFalse(profile["sourceTrusted"])
        self.assertTrue(profile["requiresReview"])
        self.assertTrue(profile["freezeBlocked"])

    def test_invalid_family_fails_closed(self) -> None:
        profile = external_dialect_profile("agent")
        profile["family"] = "runtime"

        validation = validate_external_dialect_profile(profile)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("external-dialect-family-invalid", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
