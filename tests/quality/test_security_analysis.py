from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.quality import (
    build_security_analysis_profile,
    build_security_execution_gate_receipt,
    build_security_finding,
    security_analysis_high_severity,
    validate_security_analysis_profile,
    validate_security_execution_gate_receipt,
    validate_security_finding,
)


class SecurityAnalysisTests(unittest.TestCase):
    def test_profile_is_optional_and_disabled_by_default(self) -> None:
        profile = build_security_analysis_profile()
        self.assertEqual(validate_security_analysis_profile(profile)["status"], "PASS")
        self.assertFalse(profile["enabledByDefault"])
        self.assertTrue(profile["implementationAudit"]["independentVerificationRequired"])

    def test_high_severity_detection_is_case_insensitive(self) -> None:
        self.assertTrue(security_analysis_high_severity({"securityAnalysis": {"minimumSeverity": "high"}}))
        self.assertTrue(
            security_analysis_high_severity(
                {"securityAnalysis": {"findings": [{"severity": "critical"}]}}
            )
        )
        self.assertTrue(security_analysis_high_severity({"riskSeverity": "BLOCKER"}))

    def test_finding_is_untrusted_and_lineage_bound(self) -> None:
        finding = build_security_finding(
            title="unsafe path",
            severity="HIGH",
            confidence="MEDIUM",
            source_revision="source-1",
            source_lineage_digest="0" * 64,
            locations=[{"path": "src/example.py", "startLine": 4}],
        )
        self.assertFalse(finding["trusted"])
        self.assertEqual(validate_security_finding(finding, expected_source_revision="source-1")["status"], "PASS")
        stale = validate_security_finding(finding, expected_source_revision="source-2")
        self.assertIn("security-analysis-source-revision-mismatch", {item["code"] for item in stale["blockers"]})

    def test_private_locator_is_rejected(self) -> None:
        with self.assertRaises(LifecycleError) as caught:
            build_security_finding(
                title="private",
                severity="HIGH",
                source_revision="source-1",
                source_lineage_digest="0" * 64,
                locations=[{"path": "/" + "Users/private/secret.py"}],
            )
        self.assertEqual(caught.exception.code, "security-analysis-private-locator")

    def test_recalculated_finding_digest_cannot_bypass_locator_validation(self) -> None:
        finding = build_security_finding(
            title="unsafe path",
            severity="HIGH",
            source_revision="source-1",
            source_lineage_digest="0" * 64,
            locations=[{"path": "src/example.py"}],
        )
        finding["locations"] = [{"path": "/" + "Users/private/secret.py"}]
        finding["findingDigest"] = canonical_digest(
            {key: value for key, value in finding.items() if key != "findingDigest"}
        )
        validation = validate_security_finding(finding)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("security-analysis-private-locator", {item["code"] for item in validation["blockers"]})

    def test_profile_only_does_not_authorize_execution(self) -> None:
        receipt = build_security_execution_gate_receipt(
            task={"id": "WS-01", "securityAnalysis": {"enabled": True}}
        )
        validation = validate_security_execution_gate_receipt(receipt)
        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(validation["status"], "PASS")
        self.assertIn("security-analysis-execution-authorization-required", {item["code"] for item in receipt["blockers"]})

    def test_recalculated_execution_receipt_cannot_bypass_prerequisites(self) -> None:
        receipt = build_security_execution_gate_receipt(
            task={
                "id": "WS-01",
                "securityAnalysis": {"enabled": True, "explicitOptIn": True},
            },
            sandbox_receipt_digest="a" * 64,
            authorization_granted=True,
        )
        receipt["explicitOptIn"] = False
        receipt["receiptDigest"] = canonical_digest(
            {key: value for key, value in receipt.items() if key != "receiptDigest"}
        )
        validation = validate_security_execution_gate_receipt(receipt)
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("security-analysis-execution-authorization-required", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
