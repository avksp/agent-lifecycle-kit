from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class AdapterSessionSchemaTests(unittest.TestCase):
    def test_adapter_session_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-adapter-session-receipt.v1", ids)
        self.assertIn("agent-managed-adapter-launch-receipt.v1", ids)
        self.assertIn("agent-adapter-session-resume-receipt.v1", ids)

    def test_adapter_session_schemas_reject_secret_and_config_writes(self) -> None:
        session = get_schema("agent-adapter-session-receipt.v1")
        launch = get_schema("agent-managed-adapter-launch-receipt.v1")

        self.assertEqual(session["properties"]["secretsWritten"], {"const": False})
        self.assertEqual(session["properties"]["nativeConfigWritten"], {"const": False})
        self.assertEqual(session["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(launch["properties"]["shell"], {"const": False})
        self.assertEqual(launch["properties"]["secretsWritten"], {"const": False})
        self.assertEqual(launch["properties"]["nativeConfigWritten"], {"const": False})


if __name__ == "__main__":
    unittest.main()
