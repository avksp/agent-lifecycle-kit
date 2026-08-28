from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class WorkflowContinuationSchemaTests(unittest.TestCase):
    def test_continuation_schemas_are_registered_and_bounded(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-workflow-continuation-action.v1", ids)
        self.assertIn("agent-workflow-continuation-receipt.v1", ids)

        action = get_schema("agent-workflow-continuation-action.v1")
        receipt = get_schema("agent-workflow-continuation-receipt.v1")
        self.assertEqual(action["properties"]["actionDigest"]["maxLength"], 64)
        self.assertEqual(receipt["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(receipt["properties"]["requiredInputs"]["maxItems"], 32)


if __name__ == "__main__":
    unittest.main()
