from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class BenchmarkQualificationSchemaTests(unittest.TestCase):
    def test_qualification_schema_ids_are_public_and_additive(self) -> None:
        expected = {
            "agent-benchmark-run-receipt.v1",
            "agent-benchmark-stratified-sample.v1",
            "agent-benchmark-qualification.v1",
            "agent-benchmark-qualification-validation.v1",
            "agent-benchmark-route-comparison.v1",
            "agent-benchmark-route-comparison-validation.v1",
        }
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertTrue(expected.issubset(schema_ids))
        for schema_id in expected:
            self.assertTrue(get_schema(schema_id)["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
