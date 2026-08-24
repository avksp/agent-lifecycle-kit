from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit.domain_language import (
    build_domain_language_impact_audit,
    validate_domain_language_impact_audit,
)
from agent_lifecycle.contracts import canonical_digest
from tests.project.test_domain_language import _language


class DomainLanguageImpactAuditTests(unittest.TestCase):
    def test_audit_reports_deprecated_alias_occurrence_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            source = root / "docs/domain-language.json"
            source.write_text(
                json.dumps(_language(old_alias_status="DEPRECATED"), ensure_ascii=False), encoding="utf-8"
            )
            (root / "docs/terms.md").write_text(
                "qualification receipt remains in this old reference\n", encoding="utf-8"
            )
            before = (root / "docs/terms.md").read_bytes()

            audit = build_domain_language_impact_audit(
                json.loads(source.read_text(encoding="utf-8")),
                changed_term_ids=["qualification"],
                changed_paths=["docs/terms.md"],
                project_root=root,
            )

            self.assertEqual(audit["status"], "DRIFT")
            self.assertEqual(audit["staleAliases"][0]["status"], "FOUND_IN_REFERENCE")
            self.assertEqual((root / "docs/terms.md").read_bytes(), before)
            self.assertEqual(validate_domain_language_impact_audit(audit)["status"], "PASS")

    def test_audit_rejects_missing_referenced_file(self) -> None:
        language = _language()
        language["terms"][0]["references"][0]["path"] = "docs/missing.md"
        language["languageDigest"] = canonical_digest(
            {key: value for key, value in language.items() if key != "languageDigest"}
        )

        audit = build_domain_language_impact_audit(language, project_root=Path(tempfile.mkdtemp()))

        self.assertEqual(audit["status"], "FAIL")
        self.assertIn("domain-language-reference-missing", {item["code"] for item in audit["blockers"]})

    def test_audit_defaults_to_all_terms_and_is_read_only(self) -> None:
        audit = build_domain_language_impact_audit(_language())
        self.assertEqual(audit["selectedTermIds"], ["qualification"])
        self.assertTrue(audit["readOnly"])
        self.assertFalse(audit["productionPromotionClaimed"])


if __name__ == "__main__":
    unittest.main()
