from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ProjectProfilePresetSchemaTests(unittest.TestCase):
    def test_preset_contracts_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}
        self.assertIn("agent-project-workflow-preset.v1", ids)
        self.assertIn("agent-project-workflow-preset-validation.v1", ids)
        self.assertIn("agent-project-workflow-preset-list.v1", ids)
        self.assertIn("agent-project-workflow-preset-operation.v1", ids)
        self.assertIn("agent-project-workflow-preset-render-receipt.v1", ids)

    def test_preset_schema_has_digest_and_safety_fields(self) -> None:
        schema = get_schema("agent-project-workflow-preset-render-receipt.v1")
        self.assertIn("receiptDigest", schema["required"])
        self.assertEqual(schema["properties"]["explicitOutputPath"], {"const": True})
        self.assertEqual(schema["properties"]["modelCallsStarted"], {"const": False})


if __name__ == "__main__":
    unittest.main()
