from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.cli import main
from agent_lifecycle.research.evidence import claim_digest, package_digest, quote_digest, snapshot_digest


def _package() -> dict:
    source_text = "A frozen plan defines the implementation boundary."
    snapshot_hash = snapshot_digest(source_text)
    package = {
        "schemaVersion": "agent-research-evidence-package.v1",
        "packageId": "cli-research",
        "status": "PASS",
        "sources": [
            {
                "schemaVersion": "agent-research-source.v1",
                "sourceId": "source-1",
                "kind": "file",
                "locator": {"kind": "snapshot", "value": "source-1"},
                "title": "Plan note",
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
                "claim": source_text,
                "claimDigest": claim_digest(source_text),
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
                "locator": {"kind": "snapshot", "start": 0, "end": len(source_text)},
                "quoteDigest": quote_digest(source_text),
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


class ResearchEvidenceCliTests(unittest.TestCase):
    def test_validate_and_summary_are_local_json_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path = root / "package.json"
            snapshot_path = root / "source.txt"
            validation_path = root / "validation.json"
            summary_path = root / "summary.json"
            package_path.write_text(json.dumps(_package()), encoding="utf-8")
            snapshot_path.write_text("A frozen plan defines the implementation boundary.", encoding="utf-8")

            code = main(
                [
                    "research",
                    "validate",
                    "--package",
                    str(package_path),
                    "--snapshot",
                    f"source-1={snapshot_path}",
                    "--out",
                    str(validation_path),
                ]
            )
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(validation["status"], "PASS")

            code = main(
                [
                    "research",
                    "summary",
                    "--package",
                    str(package_path),
                    "--validation",
                    str(validation_path),
                    "--out",
                    str(summary_path),
                ]
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(summary["supportedClaims"], ["claim-1"])

    def test_invalid_snapshot_binding_returns_typed_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "package.json"
            package_path.write_text(json.dumps(_package()), encoding="utf-8")
            code = main(["research", "validate", "--package", str(package_path), "--snapshot", "broken-binding"])

        self.assertEqual(code, 2)

    def test_output_is_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package_path = root / "package.json"
            output_path = root / "validation.json"
            package_path.write_text(json.dumps(_package()), encoding="utf-8")
            output_path.write_text("occupied", encoding="utf-8")
            code = main(["research", "validate", "--package", str(package_path), "--out", str(output_path)])

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
