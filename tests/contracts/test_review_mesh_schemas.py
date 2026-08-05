from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ReviewMeshSchemaTests(unittest.TestCase):
    def test_review_mesh_schemas_are_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in (
            "agent-review-mesh-profile.v1",
            "agent-review-mesh-assignment.v1",
            "agent-review-mesh-result.v1",
            "agent-review-mesh-synthesis.v1",
            "agent-review-mesh-quorum-receipt.v1",
            "agent-review-mesh-quorum-validation.v1",
        ):
            with self.subTest(schema_id=schema_id):
                self.assertIn(schema_id, schema_ids)

    def test_profile_schema_is_optional_and_resource_budgeted(self) -> None:
        schema = get_schema("agent-review-mesh-profile.v1")

        self.assertEqual(schema["properties"]["enabledByDefault"], {"const": False})
        self.assertEqual(schema["properties"]["activationMode"], {"const": "opt-in"})
        self.assertEqual(schema["properties"]["budgetUnits"], {"const": "tokens-and-resources"})
        self.assertEqual(schema["properties"]["concreteProviderModelNamesInPortableContract"], {"const": False})
        self.assertEqual(schema["properties"]["productionPromotionClaimed"], {"const": False})
        self.assertIn("crossCheckProfile", schema["required"])

    def test_assignment_schema_uses_canonical_mode_enum(self) -> None:
        schema = get_schema("agent-review-mesh-assignment.v1")
        mode_enum = set(schema["properties"]["mode"]["enum"])

        self.assertEqual(
            mode_enum,
            {
                "leader-draft-multi-review",
                "parallel-research-synthesis",
                "implementation-audit-panel",
            },
        )

    def test_quorum_validation_schema_is_public(self) -> None:
        schema = get_schema("agent-review-mesh-quorum-validation.v1")

        self.assertIn("quorumSatisfied", schema["required"])
        self.assertEqual(schema["properties"]["status"], {"enum": ["PASS", "FAIL"]})


if __name__ == "__main__":
    unittest.main()
