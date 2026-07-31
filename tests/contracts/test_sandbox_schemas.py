from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class SandboxSchemaTests(unittest.TestCase):
    def test_sandbox_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-sandbox-receipt.v1",
            "agent-sandbox-receipt-validation.v1",
            "agent-sandbox-requirement.v1",
            "agent-sandbox-requirement-validation.v1",
            "agent-sandbox-capability.v1",
            "agent-sandbox-capability-validation.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, schema_ids)

    def test_sandbox_receipt_schema_is_canonical_owner(self) -> None:
        schema = get_schema("agent-sandbox-receipt.v1")

        self.assertIn("boundaries", schema["required"])
        self.assertIn("enforcement", schema["required"])
        self.assertIn("writeScopeBoundary", schema["required"])
        self.assertFalse(schema["properties"]["productionPromotionClaimed"]["const"])


if __name__ == "__main__":
    unittest.main()
