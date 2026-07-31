from __future__ import annotations

import unittest

from agent_lifecycle.contracts import LifecycleError
from agent_lifecycle.metrics import build_phase_resource_measurement, validate_phase_resource_measurement


class PhaseResourceTests(unittest.TestCase):
    def test_phase_measurement_reuses_usage_export_without_money(self) -> None:
        measurement = build_phase_resource_measurement(
            [
                {
                    "phaseId": "implementation",
                    "phaseKind": "code",
                    "taskId": "WS22-04",
                    "tokens": {"input": 100, "output": 25},
                    "steps": 2,
                    "resources": {"toolCalls": 3, "contextBytes": 4096},
                    "durationMs": 1200,
                    "receiptDigests": ["a" * 64],
                },
                {
                    "phaseId": "validation",
                    "phaseKind": "test",
                    "tokens": {"input": 20, "output": 5, "total": 25},
                    "steps": 1,
                    "resources": {"validationRuns": 1},
                    "durationMs": 800,
                    "receiptDigests": [],
                },
            ],
            lineage={"runId": "run-22"},
        )

        validation = validate_phase_resource_measurement(measurement)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(measurement["phaseCount"], 2)
        self.assertEqual(measurement["usageExport"]["schemaVersion"], "agent-usage-export.v1")
        self.assertEqual(measurement["totals"]["tokens"]["total"], 150)
        self.assertEqual(measurement["totals"]["hostReportedCost"]["entryCount"], 0)
        self.assertNotIn("monetary", measurement["phases"][0])
        self.assertFalse(measurement["productionPromotionClaimed"])

    def test_monetary_phase_fields_are_rejected(self) -> None:
        with self.assertRaises(LifecycleError):
            build_phase_resource_measurement(
                [
                    {
                        "phaseId": "implementation",
                        "phaseKind": "code",
                        "tokens": {"input": 1, "output": 1},
                        "steps": 1,
                        "resources": {},
                        "durationMs": 1,
                        "receiptDigests": [],
                        "cost_usd": 1.0,
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
