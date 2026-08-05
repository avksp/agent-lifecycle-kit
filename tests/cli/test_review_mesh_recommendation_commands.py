from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


class ReviewMeshRecommendationCliTests(unittest.TestCase):
    def test_recommend_from_text_outputs_stable_receipt(self) -> None:
        code, payload = _run_cli(["review-mesh", "recommend", "--text", "Research options and write a plan"])

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-review-mesh-recommendation.v1")
        self.assertEqual(payload["recommendedMode"], "parallel-research-synthesis")
        self.assertFalse(payload["modelCallsStarted"])

    def test_recommend_from_intake_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            intake = Path(tmp) / "intake.json"
            intake.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-adapter-task-start-receipt.v1",
                        "status": "REVIEW_REQUIRED",
                        "adapterId": "codex",
                        "input": {"label": "task.md", "byteCount": 20, "rawTextStored": False},
                        "detectedTaskShape": "bugfix",
                        "recommendedQualityProfiles": ["bug-forensics"],
                        "preImplementationAnalysis": {"required": False},
                        "receiptDigest": "a" * 64,
                    }
                ),
                encoding="utf-8",
            )

            code, payload = _run_cli(["review-mesh", "recommend", "--intake", intake.as_posix()])

        self.assertEqual(code, 0)
        self.assertEqual(payload["recommendedMode"], "leader-draft-multi-review")
        self.assertEqual(payload["source"]["kind"], "INTAKE_RECEIPT")

    def test_recommend_from_manifest_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "plan.manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-plan-manifest.v1",
                        "status": "FROZEN",
                        "package": {"id": "release-x", "title": "Release X"},
                        "specification": {
                            "tier": "S2",
                            "requirements": [{"description": "Review implementation audit evidence"}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            code, payload = _run_cli(["review-mesh", "recommend", "--manifest", manifest.as_posix()])

        self.assertEqual(code, 0)
        self.assertEqual(payload["recommendedMode"], "implementation-audit-panel")


if __name__ == "__main__":
    unittest.main()
