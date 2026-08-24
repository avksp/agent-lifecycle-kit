from __future__ import annotations

import unittest

from agent_lifecycle.contracts.compatibility import build_contract_policy
from agent_lifecycle.contracts.schemas import get_schema


class LegacyRunnerSchemaTests(unittest.TestCase):
    def test_runner_state_remains_readable_but_is_deprecated(self) -> None:
        policy = build_contract_policy()
        row = next(item for item in policy["schemas"] if item["id"] == "agent-runner-state.v1")

        self.assertEqual(row["status"], "DEPRECATED_COMPATIBLE")
        self.assertEqual(row["behavior"], "accepted-compatible")
        self.assertEqual(row["replacement"], "agent-workflow-state.v4")
        self.assertEqual(get_schema("agent-runner-state.v1")["$schema"], "https://json-schema.org/draft/2020-12/schema")


if __name__ == "__main__":
    unittest.main()
