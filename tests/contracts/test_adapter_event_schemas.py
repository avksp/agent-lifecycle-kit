from __future__ import annotations

import unittest

from agent_lifecycle.contracts.adapter_event_schemas import ADAPTER_EVENT_SCHEMAS
from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class AdapterEventSchemaTests(unittest.TestCase):
    def test_adapter_event_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertTrue(set(ADAPTER_EVENT_SCHEMAS).issubset(schema_ids))
        for schema_id in ADAPTER_EVENT_SCHEMAS:
            self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_lifecycle_control_validation_schema_is_bounded_and_non_promoting(self) -> None:
        schema = get_schema("agent-adapter-lifecycle-control-validation.v1")

        self.assertTrue(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertEqual(
            schema["required"],
            ["schemaVersion", "status", "blockers", "productionPromotionClaimed"],
        )


if __name__ == "__main__":
    unittest.main()
