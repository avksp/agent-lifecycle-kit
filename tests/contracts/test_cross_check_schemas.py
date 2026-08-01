from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class CrossCheckSchemaTests(unittest.TestCase):
    def test_cross_check_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-cross-check-profile.v1",
            "agent-cross-check-profile-validation.v1",
            "agent-cross-check-receipt.v1",
            "agent-cross-check-receipt-validation.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, schema_ids)

    def test_profile_schema_is_optional_and_token_budgeted(self) -> None:
        schema = get_schema("agent-cross-check-profile.v1")

        self.assertEqual(schema["properties"]["enabledByDefault"], {"const": False})
        self.assertEqual(schema["properties"]["activationMode"], {"const": "opt-in"})
        self.assertEqual(schema["properties"]["budgetUnits"], {"const": "tokens-and-resources"})
        self.assertIn("independencePolicy", schema["required"])
        self.assertEqual(schema["properties"]["monetaryCostCanonical"], {"const": False})

    def test_receipt_schema_records_independence_status(self) -> None:
        receipt_schema = get_schema("agent-cross-check-receipt.v1")
        validation_schema = get_schema("agent-cross-check-receipt-validation.v1")

        self.assertIn("independence", receipt_schema["required"])
        self.assertIn("independenceStatus", validation_schema["required"])


if __name__ == "__main__":
    unittest.main()
