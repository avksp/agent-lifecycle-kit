from __future__ import annotations

import unittest

from agent_lifecycle.contracts.compatibility import build_contract_policy, validate_contract_policy
from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class AdapterTaskSchemaTests(unittest.TestCase):
    def test_adapter_task_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-adapter-task-start-receipt.v1", ids)
        self.assertIn("agent-adapter-task-run-request.v1", ids)
        self.assertEqual(get_schema("agent-adapter-task-start-receipt.v1")["properties"]["rawTaskTextStored"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-task-start-receipt.v1")["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(get_schema("agent-adapter-task-start-receipt.v1")["properties"]["productionPromotionClaimed"], {"const": False})

    def test_public_contract_policy_lists_adapter_task_start(self) -> None:
        policy = build_contract_policy()
        validation = validate_contract_policy(policy)

        self.assertEqual(validation["status"], "PASS")
        outputs = {(item["command"], item["schemaVersion"]) for item in policy["cliOutputs"]}
        self.assertIn(("adapter task start", "agent-adapter-task-start-receipt.v1"), outputs)


if __name__ == "__main__":
    unittest.main()
