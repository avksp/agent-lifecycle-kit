from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class WorkflowRunSchemaTests(unittest.TestCase):
    def test_active_workflow_envelopes_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-workflow-next-action.v1", ids)
        self.assertIn("agent-workflow-run-receipt.v1", ids)
        self.assertEqual(
            get_schema("agent-workflow-run-receipt.v1")["properties"]["stateWritten"],
            {"const": False},
        )


if __name__ == "__main__":
    unittest.main()
