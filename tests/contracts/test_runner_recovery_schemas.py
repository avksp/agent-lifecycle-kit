from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class RunnerRecoverySchemaTests(unittest.TestCase):
    def test_runner_recovery_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-runner-attempt-snapshot-receipt.v1",
            "agent-runner-attempt-snapshot-receipt-validation.v1",
            "agent-worker-lease-receipt.v1",
            "agent-worker-lease-receipt-validation.v1",
            "agent-phase-resource-measurement.v1",
            "agent-phase-resource-measurement-validation.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, schema_ids)

    def test_recovery_schemas_do_not_claim_production_promotion(self) -> None:
        self.assertEqual(get_schema("agent-runner-attempt-snapshot-receipt.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-worker-lease-receipt.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(get_schema("agent-phase-resource-measurement.v1")["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertIn("usageExport", get_schema("agent-phase-resource-measurement.v1")["required"])


if __name__ == "__main__":
    unittest.main()
