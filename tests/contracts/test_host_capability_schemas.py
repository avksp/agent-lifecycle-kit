from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class HostCapabilitySchemaTests(unittest.TestCase):
    def test_host_capability_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-host-capability.v1", ids)
        self.assertIn("agent-host-capability-validation.v1", ids)
        self.assertIn("agent-acp-probe-receipt.v1", ids)
        self.assertEqual(get_schema("agent-host-capability.v1")["properties"]["providerIdentityUsed"], {"const": False})
        self.assertEqual(get_schema("agent-acp-probe-receipt.v1")["properties"]["liveCallsStarted"], {"const": False})


if __name__ == "__main__":
    unittest.main()
