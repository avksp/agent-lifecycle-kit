from __future__ import annotations

import unittest

from agent_lifecycle.contracts.schemas import get_schema, list_schemas


class ReviewMeshRecommendationSchemaTests(unittest.TestCase):
    def test_recommendation_schema_is_registered(self) -> None:
        schema_ids = {item["id"] for item in list_schemas()["schemas"]}

        self.assertIn("agent-review-mesh-recommendation.v1", schema_ids)

    def test_recommendation_schema_is_advisory_and_provider_neutral(self) -> None:
        schema = get_schema("agent-review-mesh-recommendation.v1")

        self.assertEqual(schema["properties"]["budgetUnits"], {"const": "tokens-and-resources"})
        self.assertEqual(schema["properties"]["advisoryOnly"], {"const": True})
        self.assertEqual(schema["properties"]["requiresOperatorConfirmation"], {"const": True})
        self.assertEqual(schema["properties"]["blockingGateActivated"], {"const": False})
        self.assertEqual(schema["properties"]["modelCallsStarted"], {"const": False})
        self.assertEqual(schema["properties"]["hostLaunchStarted"], {"const": False})
        self.assertEqual(schema["properties"]["concreteProviderModelNamesInPortableContract"], {"const": False})

    def test_recommendation_schema_uses_review_mesh_modes_plus_off(self) -> None:
        schema = get_schema("agent-review-mesh-recommendation.v1")

        self.assertEqual(
            set(schema["properties"]["recommendedMode"]["enum"]),
            {
                "off",
                "leader-draft-multi-review",
                "parallel-research-synthesis",
                "implementation-audit-panel",
            },
        )


if __name__ == "__main__":
    unittest.main()
