from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts.compatibility import build_contract_policy, validate_contract_policy  # noqa: E402


class ContractCompatibilityTests(unittest.TestCase):
    def test_public_contract_policy_validates_current_registry(self) -> None:
        policy = build_contract_policy()

        validation = validate_contract_policy(policy)

        self.assertEqual(policy["schemaVersion"], "agent-public-contract-policy.v1")
        self.assertEqual(validation["schemaVersion"], "agent-public-contract-policy-validation.v1")
        self.assertEqual(validation["status"], "PASS")
        schema_ids = {item["id"] for item in policy["schemas"]}
        self.assertIn("agent-lifecycle-error.v1", schema_ids)
        self.assertIn("agent-completion-check.v1", schema_ids)
        self.assertIn("agent-lifecycle-cost-report.v1", schema_ids)
        self.assertIn("agent-lifecycle-cost-generation.v1", schema_ids)
        self.assertIn("agent-lifecycle-recommendation.v1", schema_ids)
        cli_outputs = {(item["command"], item["schemaVersion"]) for item in policy["cliOutputs"]}
        self.assertIn(("metrics cost-report", "agent-lifecycle-cost-generation.v1"), cli_outputs)
        self.assertIn(("metrics recommend", "agent-lifecycle-recommendation.v1"), cli_outputs)
        self.assertFalse(policy["productionPromotionClaimed"])

    def test_public_contract_policy_keeps_deprecated_schema_readable(self) -> None:
        policy = build_contract_policy()
        row = next(item for item in policy["schemas"] if item["id"] == "agent-lifecycle-host-model-profile.v1")

        self.assertEqual(row["status"], "DEPRECATED_COMPATIBLE")
        self.assertEqual(row["replacement"], "agent-host-model-selection-profile.v1")
        self.assertEqual(row["behavior"], "accepted-compatible")

    def test_public_contract_policy_rejects_unknown_cli_schema(self) -> None:
        policy = build_contract_policy()
        policy["cliOutputs"][0]["schemaVersion"] = "missing.v1"

        validation = validate_contract_policy(policy)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("contract-policy-cli-schema", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
