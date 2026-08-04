from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ProgressHookSchemaTests(unittest.TestCase):
    def test_progress_hook_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-progress-hook-policy.v1", schema_ids)
        self.assertIn("agent-progress-hook-receipt.v1", schema_ids)

    def test_progress_hook_schemas_preserve_read_only_invariants(self) -> None:
        policy = get_schema("agent-progress-hook-policy.v1")
        receipt = get_schema("agent-progress-hook-receipt.v1")

        self.assertEqual(policy["properties"]["defaultEnabled"], {"const": False})
        self.assertEqual(policy["properties"]["stdoutJsonPreserved"], {"const": True})
        self.assertEqual(policy["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(policy["properties"]["tokenSpendForProgress"], {"const": False})
        self.assertEqual(policy["properties"]["pluginInstalledIsLifecycleProof"], {"const": False})
        self.assertEqual(receipt["properties"]["stdoutJsonPreserved"], {"const": True})
        self.assertEqual(receipt["properties"]["readOnly"], {"const": True})
        self.assertEqual(receipt["properties"]["stateWritten"], {"const": False})
        self.assertEqual(receipt["properties"]["tokenCountsInferred"], {"const": False})
        self.assertEqual(receipt["properties"]["pluginInstalledIsLifecycleProof"], {"const": False})


if __name__ == "__main__":
    unittest.main()
