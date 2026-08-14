from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.research.evidence import claim_digest, package_digest, quote_digest, snapshot_digest


ROOT = Path(__file__).resolve().parents[2]


def _package() -> dict:
    text = "Research evidence is additional context, not lifecycle authority."
    snapshot_hash = snapshot_digest(text)
    package = {
        "schemaVersion": "agent-research-evidence-package.v1",
        "packageId": "release-evidence",
        "status": "PASS",
        "sources": [
            {
                "schemaVersion": "agent-research-source.v1",
                "sourceId": "source-1",
                "kind": "file",
                "locator": {"kind": "snapshot", "value": "source-1"},
                "title": "Research note",
                "status": "reviewed",
                "sourceDigest": "a" * 64,
                "snapshotDigest": snapshot_hash,
                "metadata": {},
                "redactionStatus": {"status": "PASS"},
                "sourceOfTruth": False,
                "rawContentStored": False,
                "productionPromotionClaimed": False,
            }
        ],
        "claims": [
            {
                "schemaVersion": "agent-research-claim.v1",
                "claimId": "claim-1",
                "claim": text,
                "claimDigest": claim_digest(text),
                "status": "accepted",
                "supportingSourceIds": ["source-1"],
                "citationIds": ["citation-1"],
                "sourceOfTruth": False,
                "lifecycleAuthority": "none",
                "productionPromotionClaimed": False,
            }
        ],
        "citations": [
            {
                "schemaVersion": "agent-research-citation.v1",
                "citationId": "citation-1",
                "claimId": "claim-1",
                "sourceId": "source-1",
                "locator": {"kind": "snapshot", "start": 0, "end": len(text)},
                "quoteDigest": quote_digest(text),
                "snapshotDigest": snapshot_hash,
                "matchStatus": "MATCHED",
                "redactionStatus": {"status": "PASS"},
                "productionPromotionClaimed": False,
            }
        ],
        "provenance": [],
        "resourceCaps": {"maxEvidenceBytes": 33_554_432},
        "redaction": {"status": "PASS", "rawContentStored": False},
        "sourceOfTruth": False,
        "blockers": [],
        "productionPromotionClaimed": False,
    }
    package["packageDigest"] = package_digest(package)
    return package


class ResearchEvidenceValidatorTests(unittest.TestCase):
    def test_release_validator_passes_explicit_package_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence.json"
            (root / "snapshots").mkdir()
            (root / "research-evidence.json").write_text(json.dumps(_package()), encoding="utf-8")
            (root / "snapshots/source-1.txt").write_text(
                "Research evidence is additional context, not lifecycle authority.", encoding="utf-8"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_research_evidence.py"),
                    "--root",
                    str(root),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["productionPromotionClaimed"])

    def test_release_validator_fails_closed_when_package_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/release/validate_research_evidence.py"),
                    "--root",
                    str(root),
                    "--evidence",
                    str(evidence),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("research-package-missing", {item["code"] for item in payload["blockers"]})


if __name__ == "__main__":
    unittest.main()
