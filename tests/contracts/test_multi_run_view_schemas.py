from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class MultiRunViewSchemaTests(unittest.TestCase):
    def test_multi_run_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        for schema_id in (
            "agent-multi-run-attention-item.v1",
            "agent-multi-run-overlap.v1",
            "agent-multi-run-attention-view.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, ids)
                self.assertEqual(get_schema(schema_id)["$id"], schema_id)

    def test_view_contract_keeps_authority_false(self) -> None:
        schema = get_schema("agent-multi-run-attention-view.v1")
        self.assertEqual(schema["properties"]["sourceOfTruth"], {"const": False})
        self.assertEqual(schema["properties"]["readOnly"], {"const": True})
        self.assertEqual(schema["properties"]["stateWritten"], {"const": False})


if __name__ == "__main__":
    unittest.main()
