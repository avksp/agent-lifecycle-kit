from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ProjectProfileSchemaTests(unittest.TestCase):
    def test_project_profile_contracts_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-project-workflow-profile.v1",
            "agent-effective-project-workflow-profile.v1",
            "agent-guided-action-receipt.v1",
            "agent-project-profile-boundary-validation.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, ids)
                self.assertEqual(get_schema(schema_id)["properties"]["schemaVersion"], {"const": schema_id})

    def test_profile_schema_uses_canonical_stage_and_neutral_values(self) -> None:
        schema = get_schema("agent-project-workflow-profile.v1")
        self.assertEqual(
            set(schema["properties"]["stages"]["propertyNames"]["enum"]),
            {"intake", "research", "planning", "review", "implementation", "audit", "finalization"},
        )
        self.assertIn("modelClass", schema["properties"]["stages"]["additionalProperties"]["properties"])
        self.assertIn("threadBridge", schema["properties"])
        self.assertEqual(
            set(schema["properties"]["threadBridge"]["properties"]["mode"]["enum"]),
            {"off", "advisory", "read-only", "controlled"},
        )
        self.assertEqual(
            schema["properties"]["productionPromotionClaimed"],
            {"const": False},
        )


if __name__ == "__main__":
    unittest.main()
