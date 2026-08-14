from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.review_mesh.results import project_review_result_for_optimization  # noqa: E402


class ReviewResultOptimizationProjectionTests(unittest.TestCase):
    def test_projection_keeps_findings_summary_and_neutral_identity_hashes(self) -> None:
        projection = project_review_result_for_optimization(
            {
                "schemaVersion": "agent-review-mesh-result.v1",
                "status": "PASS",
                "phase": "plan-review",
                "subject": {"taskShape": "architecture"},
                "reviewer": {"role": "architecture-reviewer", "modelClass": "strong-reasoning", "modelIdentityHash": "b" * 64},
                "findings": [
                    {"id": "F1", "severity": "HIGH", "status": "open"},
                    {"id": "F2", "severity": "LOW", "status": "accepted"},
                ],
                "independence": {"status": "INDEPENDENT"},
            }
        )

        self.assertEqual(projection["findingCount"], 2)
        self.assertEqual(projection["severityCounts"], {"HIGH": 1, "LOW": 1})
        self.assertEqual(projection["acceptedCount"], 1)
        self.assertEqual(projection["modelIdentityHash"], "b" * 64)
        self.assertNotIn("findings", projection)


if __name__ == "__main__":
    unittest.main()
