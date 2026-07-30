from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.compatibility import build_contract_policy  # noqa: E402
from agent_lifecycle.contracts.schemas import get_schema, list_schemas  # noqa: E402


class PolicyTuningContractTests(unittest.TestCase):
    def test_policy_tuning_schemas_are_registered(self) -> None:
        ids = {item["id"] for item in list_schemas()["schemas"]}

        for schema_id in [
            "agent-lifecycle-regression-signals.v1",
            "agent-lifecycle-policy-proposal.v1",
            "agent-lifecycle-policy-summary.v1",
            "agent-lifecycle-tuned-policy.v1",
            "agent-lifecycle-policy-apply-result.v1",
            "agent-lifecycle-policy-tune-result.v1",
        ]:
            self.assertIn(schema_id, ids)

        proposal = get_schema("agent-lifecycle-policy-proposal.v1")
        self.assertEqual(proposal["properties"]["advisoryOnly"], {"const": True})
        self.assertEqual(proposal["properties"]["autoApply"], {"const": False})

    def test_contract_policy_lists_policy_tune_cli_output(self) -> None:
        policy = build_contract_policy()
        rows = {item["command"]: item for item in policy["cliOutputs"]}

        self.assertEqual(rows["policy tune"]["schemaVersion"], "agent-lifecycle-policy-tune-result.v1")
        self.assertEqual(rows["policy tune"]["compatibility"], "stable-json")


if __name__ == "__main__":
    unittest.main()
