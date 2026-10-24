from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
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

    def test_rehashed_profile_cannot_grant_trust_or_remove_review_gates(self) -> None:
        cases = [
            ("sourceTrusted", True, "dialect-profile-source-trusted"),
            ("requiresReview", False, "dialect-profile-review-not-required"),
            ("freezeBlocked", False, "dialect-profile-freeze-not-blocked"),
        ]
        for family in ("workflow", "agent"):
            for key, value, blocker in cases:
                with self.subTest(family=family, field=key):
                    profile = external_dialect_profile(family)
                    profile[key] = value
                    profile["profileDigest"] = canonical_digest(
                        {field: content for field, content in profile.items() if field != "profileDigest"}
                    )
                    validation = validate_external_dialect_profile(profile)
                    self.assertEqual(validation["status"], "FAIL")
                    codes = {item["code"] for item in validation["blockers"]}
                    self.assertIn(blocker, codes)
                    self.assertNotIn("dialect-profile-digest-mismatch", codes)
                    with self.assertRaises(LifecycleError) as caught:
                        require_external_profile_pass(validation)
                    self.assertEqual(caught.exception.code, "external-dialect-profile-validation-failed")

    def test_profile_mapping_digest_drift_is_rejected(self) -> None:
        profile = external_dialect_profile("workflow")
        profile["mapping"]["candidateStatus"] = "FROZEN"
        validation = validate_external_dialect_profile(profile)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("dialect-profile-digest-mismatch", {item["code"] for item in validation["blockers"]})
        with self.assertRaises(LifecycleError):
            require_external_profile_pass(validation)


if __name__ == "__main__":
    unittest.main()
