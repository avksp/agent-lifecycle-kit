from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics import validate_lifecycle_cost_report  # noqa: E402


class LifecycleCostTests(unittest.TestCase):
    def test_standard_task_cost_report_separates_pipeline_overhead(self) -> None:
        validation = validate_lifecycle_cost_report(
            {
                "schemaVersion": "agent-lifecycle-cost-report.v1",
                "mode": "standard",
                "entries": [
                    {"category": "implementation", "tokens": 9000, "steps": 4},
                    {"category": "productValidation", "tokens": 2500, "steps": 2},
                    {"category": "pipelineCompliance", "tokens": 2400, "steps": 3},
                    {"category": "coordination", "tokens": 500, "steps": 1},
                ],
                "productionPromotionClaimed": False,
            }
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["totals"]["pipelineCompliance"]["tokens"], 2400)
        self.assertEqual(validation["totals"]["productValidation"]["steps"], 2)
        self.assertLess(validation["ratios"]["pipelineTokenShare"], 0.30)

    def test_pipeline_overhead_requires_reason_when_over_limit(self) -> None:
        validation = validate_lifecycle_cost_report(
            {
                "schemaVersion": "agent-lifecycle-cost-report.v1",
                "mode": "light",
                "entries": [
                    {"category": "implementation", "tokens": 1000, "steps": 1},
                    {"category": "productValidation", "tokens": 200, "steps": 1},
                    {"category": "pipelineCompliance", "tokens": 3000, "steps": 5},
                    {"category": "coordination", "tokens": 100, "steps": 1},
                ],
                "productionPromotionClaimed": False,
            }
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("pipeline-compliance-over-limit", {item["code"] for item in validation["blockers"]})

    def test_strict_pipeline_overhead_can_be_explained(self) -> None:
        validation = validate_lifecycle_cost_report(
            {
                "schemaVersion": "agent-lifecycle-cost-report.v1",
                "mode": "strict",
                "entries": [
                    {"category": "implementation", "tokens": 3000, "steps": 3},
                    {"category": "productValidation", "tokens": 3000, "steps": 3},
                    {"category": "pipelineCompliance", "tokens": 12000, "steps": 10},
                    {"category": "coordination", "tokens": 1000, "steps": 1},
                ],
                "overLimitReason": "Release-sensitive review needed full lifecycle checks.",
                "productionPromotionClaimed": False,
            }
        )

        self.assertEqual(validation["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
