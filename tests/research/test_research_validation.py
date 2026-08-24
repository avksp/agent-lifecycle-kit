from __future__ import annotations

import unittest

from agent_lifecycle.research.evidence import package_digest
from agent_lifecycle.research.validation import validate_evidence_package


def _package(locator: str) -> dict:
    package = {
        "schemaVersion": "agent-research-evidence-package.v1",
        "packageId": "research-redaction",
        "status": "PASS",
        "sources": [
            {
                "schemaVersion": "agent-research-source.v1",
                "sourceId": "source-1",
                "kind": "web",
                "locator": {"kind": "url", "value": locator, "start": 0, "end": 0},
                "title": "Public source",
                "status": "reviewed",
                "sourceDigest": "a" * 64,
                "snapshotDigest": None,
                "metadata": {},
                "redactionStatus": {"status": "PASS"},
                "sourceOfTruth": False,
                "rawContentStored": False,
                "productionPromotionClaimed": False,
            }
        ],
        "claims": [],
        "citations": [],
        "provenance": [],
        "resourceCaps": {"maxEvidenceBytes": 33_554_432},
        "redaction": {"status": "PASS", "rawContentStored": False},
        "sourceOfTruth": False,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    package["packageDigest"] = package_digest(package)
    return package


class ResearchValidationRedactionTests(unittest.TestCase):
    def test_public_url_locator_is_accepted(self) -> None:
        validation = validate_evidence_package(_package("https://github.com/avksp/agent-lifecycle-kit"))

        self.assertEqual(validation["status"], "PASS")

    def test_local_absolute_locator_remains_rejected(self) -> None:
        private_path = "/" + "Users/private/source.md"
        validation = validate_evidence_package(_package(private_path))

        self.assertEqual(validation["status"], "FAIL")
        codes = {item["code"] for item in validation["blockers"]}
        self.assertIn("research-locator-private-path", codes)


if __name__ == "__main__":
    unittest.main()
