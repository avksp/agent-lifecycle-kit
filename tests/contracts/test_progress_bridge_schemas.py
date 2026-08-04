from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ProgressBridgeSchemaTests(unittest.TestCase):
    def test_progress_bridge_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-progress-bridge-config.v1", schema_ids)
        self.assertIn("agent-progress-bridge-receipt.v1", schema_ids)

    def test_progress_bridge_schemas_are_read_only(self) -> None:
        config = get_schema("agent-progress-bridge-config.v1")
        receipt = get_schema("agent-progress-bridge-receipt.v1")

        self.assertEqual(config["properties"]["readOnly"], {"const": True})
        self.assertEqual(config["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(config["properties"]["stateWritten"], {"const": False})
        self.assertEqual(receipt["properties"]["readOnly"], {"const": True})
        self.assertEqual(receipt["properties"]["tokenSpendForProgress"], {"const": False})
        self.assertEqual(receipt["properties"]["hostTelemetryParsedInCore"], {"const": False})


if __name__ == "__main__":
    unittest.main()
