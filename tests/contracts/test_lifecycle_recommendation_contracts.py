from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.compatibility import build_contract_policy  # noqa: E402
from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class LifecycleRecommendationContractTests(unittest.TestCase):
    def test_recommendation_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in [
            "agent-lifecycle-baselines.v1",
            "agent-lifecycle-baselines-validation.v1",
            "agent-lifecycle-overhead-statistics.v1",
            "agent-lifecycle-recommendation.v1",
            "agent-lifecycle-recommendation-summary.v1",
        ]:
            self.assertIn(schema_id, ids)

        self.assertEqual(get_schema("agent-lifecycle-recommendation.v1")["properties"]["autoApply"], {"const": False})
        self.assertEqual(get_schema("agent-lifecycle-recommendation.v1")["properties"]["advisoryOnly"], {"const": True})

    def test_contract_policy_lists_recommendation_cli_output(self) -> None:
        policy = build_contract_policy()
        rows = {item["command"]: item for item in policy["cliOutputs"]}

        self.assertEqual(rows["metrics recommend"]["schemaVersion"], "agent-lifecycle-recommendation.v1")
        self.assertEqual(rows["metrics recommend"]["compatibility"], "stable-json")


if __name__ == "__main__":
    unittest.main()
