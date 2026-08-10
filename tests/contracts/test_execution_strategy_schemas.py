from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ExecutionStrategySchemaTests(unittest.TestCase):
    def test_strategy_schemas_are_public(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-execution-strategy.v1", ids)
        self.assertIn("agent-execution-strategy-validation.v1", ids)
        self.assertEqual(
            get_schema("agent-execution-strategy.v1")["$id"],
            "agent-execution-strategy.v1",
        )


if __name__ == "__main__":
    unittest.main()
