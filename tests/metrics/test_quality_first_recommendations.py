from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics.audit_optimization import evaluate_candidate_profiles  # noqa: E402


class QualityFirstRecommendationTests(unittest.TestCase):
    def test_candidate_with_quality_below_floor_is_not_eligible(self) -> None:
        evaluation = evaluate_candidate_profiles(
            [{
                "profileId": "below-floor",
                "taskShape": "feature",
                "qualityFloor": "standard",
                "holdoutTasks": [
                    {"taskId": "one", "qualityPass": True},
                    {"taskId": "two", "qualityPass": False},
                    {"taskId": "three", "qualityPass": True},
                ],
            }],
        )

        self.assertEqual(evaluation["status"], "NO_RECOMMENDATION")
        self.assertEqual(evaluation["candidates"][0]["eligibilityReason"], "quality-floor-not-met")

    def test_false_acceptance_is_never_eligible(self) -> None:
        evaluation = evaluate_candidate_profiles(
            [{
                "profileId": "false-acceptance",
                "taskShape": "feature",
                "qualityFloor": "standard",
                "holdoutTasks": [
                    {"taskId": "one", "qualityPass": True, "falseAcceptance": True},
                    {"taskId": "two", "qualityPass": True},
                    {"taskId": "three", "qualityPass": True},
                ],
            }],
        )

        self.assertEqual(evaluation["status"], "NO_RECOMMENDATION")
        self.assertEqual(evaluation["candidates"][0]["eligibilityReason"], "false-acceptance-increased")


if __name__ == "__main__":
    unittest.main()
