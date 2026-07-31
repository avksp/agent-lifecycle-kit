from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class UsageExportSchemaTests(unittest.TestCase):
    def test_usage_export_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-usage-export.v1", schema_ids)
        self.assertIn("agent-usage-export-validation.v1", schema_ids)
        self.assertIn("agent-usage-export-generation.v1", schema_ids)

    def test_usage_export_schema_keeps_money_optional(self) -> None:
        schema = get_schema("agent-usage-export.v1")

        self.assertNotIn("cost_usd", schema["required"])
        self.assertFalse(schema["properties"]["productionPromotionClaimed"]["const"])


if __name__ == "__main__":
    unittest.main()
