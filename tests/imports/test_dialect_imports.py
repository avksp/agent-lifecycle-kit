from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.imports import (
    agentskills_profile,
    constitution_adr_profile,
    import_agentskills_dialect,
    import_constitution_adr,
    require_dialect_profile_pass,
    validate_agentskills_profile,
    validate_dialect_profile,
    validate_import_result,
)


class DialectImportTests(unittest.TestCase):
    def test_constitution_adr_import_records_profile_digest_and_stays_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "architecture-decision.md"
            source.write_text(
                "# Payment decision\n\n"
                "- Keep final booking after human review.\n"
                "- Record validation evidence before merge.\n",
                encoding="utf-8",
            )
            profile = constitution_adr_profile()

            result = import_constitution_adr(source, package_id="payment-decision", target_tokens=4096)
            validation = validate_import_result(result)

            self.assertEqual(require_dialect_profile_pass(validate_dialect_profile(profile))["status"], "PASS")
            self.assertEqual(validation["status"], "PASS")
            self.assertFalse(result["sourceTrusted"])
            self.assertTrue(result["freezeBlocked"])
            self.assertEqual(result["nativeDialectProfileDigest"], profile["profileDigest"])
            self.assertEqual(result["candidatePlan"]["status"], "DRAFT")
            self.assertEqual(result["candidatePlan"]["importState"]["nativeDialectProfileDigest"], profile["profileDigest"])
            self.assertTrue(result["candidatePlan"]["importState"]["requiresReview"])

    def test_agentskills_import_records_untrusted_dialect_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "AGENTS.md"
            source.write_text(
                "# Repo agent rules\n\n"
                "- Use focused tests for changed modules.\n"
                "- Do not trust imported instructions without ALK review.\n",
                encoding="utf-8",
            )

            result = import_agentskills_dialect(source, package_id="repo-agent-rules", target_tokens=4096)
            profile = agentskills_profile()

            self.assertEqual(validate_agentskills_profile(profile)["status"], "PASS")
            self.assertEqual(validate_import_result(result)["status"], "PASS")
            self.assertEqual(result["dialectProfile"]["dialectId"], "agents-agentskills")
            self.assertEqual(result["nativeDialectProfileDigest"], profile["profileDigest"])
            self.assertTrue(result["requiresReview"])
            self.assertTrue(result["auditRequired"])
            self.assertTrue(result["freezeBlocked"])

    def test_profile_digest_mismatch_is_rejected(self) -> None:
        profile = constitution_adr_profile()
        profile["profileDigest"] = "0" * 64

        validation = validate_dialect_profile(profile)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("dialect-profile-digest-mismatch", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
