from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics.audit_optimization import evaluate_candidate_profiles  # noqa: E402


class AuditOptimizationEvaluationTests(unittest.TestCase):
    def test_shared_holdout_pool_selects_only_quality_safe_profile(self) -> None:
        result = evaluate_candidate_profiles(
            [
                {
                    "profileId": "safe",
                    "taskShape": "feature",
                    "qualityFloor": "standard",
                    "holdoutTasks": [{"taskId": f"safe-{index}", "qualityPass": True} for index in range(3)],
                },
                {
                    "profileId": "unsafe",
                    "taskShape": "feature",
                    "qualityFloor": "standard",
                    "holdoutTasks": [
                        {"taskId": "unsafe-0", "qualityPass": True},
                        {"taskId": "unsafe-1", "qualityPass": False},
                        {"taskId": "unsafe-2", "qualityPass": True},
                    ],
                },
            ],
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual([item["profileId"] for item in result["eligibleCandidates"]], ["safe"])


if __name__ == "__main__":
    unittest.main()
