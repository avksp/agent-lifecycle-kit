from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import list_schemas


class PlanDeltaSchemaTests(unittest.TestCase):
    def test_public_plan_delta_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-project-principles.v1", ids)
        self.assertIn("agent-plan-delta.v1", ids)
        self.assertIn("agent-plan-delta-validation.v1", ids)


if __name__ == "__main__":
    unittest.main()
