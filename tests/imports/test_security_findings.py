from __future__ import annotations

import unittest

from agent_lifecycle.imports.security_findings import (
    export_security_findings_sarif,
    import_security_findings,
    validate_security_finding_import,
)


class SecurityFindingImportTests(unittest.TestCase):
    def test_normalized_import_is_untrusted_and_validated(self) -> None:
        payload = import_security_findings(
            {
                "sourceRevision": "source-1",
                "findings": [{"id": "SEC-1", "title": "issue", "severity": "HIGH", "path": "src/a.py"}],
            },
            expected_source_revision="source-1",
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["trusted"])
        self.assertEqual(validate_security_finding_import(payload, expected_source_revision="source-1")["status"], "PASS")

    def test_stale_and_private_imports_fail_closed(self) -> None:
        payload = import_security_findings(
            {
                "sourceRevision": "old",
                "findings": [{"title": "issue", "severity": "HIGH", "path": "/tmp/private.py"}],
            },
            expected_source_revision="current",
        )
        codes = {item["code"] for item in payload["blockers"]}
        self.assertIn("security-analysis-source-revision-mismatch", codes)
        self.assertIn("security-analysis-private-locator", codes)

    def test_sarif_export_does_not_claim_trust(self) -> None:
        payload = import_security_findings(
            {"sourceRevision": "source-1", "findings": [{"title": "issue", "severity": "LOW", "path": "src/a.py"}]},
            expected_source_revision="source-1",
        )
        sarif = export_security_findings_sarif(payload["findings"])
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertFalse(sarif["runs"][0]["results"][0]["properties"]["alkTrusted"])


if __name__ == "__main__":
    unittest.main()
