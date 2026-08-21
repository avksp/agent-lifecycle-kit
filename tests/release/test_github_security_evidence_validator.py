from __future__ import annotations

import copy
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS_RELEASE = ROOT / "tools" / "release"
sys.path.insert(0, str(TOOLS_RELEASE))

from validate_github_security_evidence import validate_github_security_evidence  # noqa: E402


def _evidence() -> dict:
    return {
        "schemaVersion": "github-security-posture.v1",
        "repository": "avksp/agent-lifecycle-kit",
        "observedAt": "2026-08-21T00:00:00Z",
        "source": {"kind": "github-api-read-only", "tool": "gh-api"},
        "productionPromotionClaimed": False,
        "main": {
            "protected": True,
            "administratorsCannotBypass": True,
            "forcePushesDisabled": True,
            "deletionsDisabled": True,
            "requiredChecks": ["ci", "neutrality", "codeql"],
        },
        "releaseRefs": {"immutableTags": True, "protectedReleaseRefs": True},
        "actions": {"immutablePins": True},
        "codeql": {"required": True},
        "pypi": {"trustedPublishing": True, "environmentProtected": True, "tagRestriction": True, "selfReviewPrevented": True},
        "security": {"secretScanning": True, "pushProtection": True, "dependencyUpdates": True},
        "reviewPosture": {
            "eligibleIndependentMaintainers": 0,
            "singleMaintainerCompensatingControls": {
                "mandatoryChecksWithoutAdministratorBypass": True,
                "codeqlRequired": True,
                "immutableActionIdentities": True,
                "protectedReleaseRefs": True,
                "protectedPyPITrustedPublishing": True,
                "residualRisk": "Independent human approval is unavailable for this single-maintainer repository.",
            },
        },
    }


class GithubSecurityEvidenceValidatorTests(unittest.TestCase):
    def test_complete_single_maintainer_compensating_controls_pass(self) -> None:
        result = validate_github_security_evidence(_evidence())

        self.assertEqual(result["status"], "PASS", result["blockers"])
        self.assertTrue(result["externalEvidenceAccepted"])

    def test_missing_pypi_environment_protection_blocks(self) -> None:
        payload = copy.deepcopy(_evidence())
        payload["pypi"]["environmentProtected"] = False

        result = validate_github_security_evidence(payload)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("github-protection-missing", {item["code"] for item in result["blockers"]})
        self.assertFalse(result["externalEvidenceAccepted"])


if __name__ == "__main__":
    unittest.main()
