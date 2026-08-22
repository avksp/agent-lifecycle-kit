from __future__ import annotations

import unittest
from pathlib import Path

from tools.release.validate_neutrality_performance import validate_neutrality_performance


ROOT = Path(__file__).resolve().parents[2]


class NeutralityPerformanceValidatorTests(unittest.TestCase):
    def test_current_batch_and_matching_routes_pass(self) -> None:
        payload = validate_neutrality_performance(
            scanner_path=ROOT / "src/agent_lifecycle/neutrality/scanner.py",
            policy_path=ROOT / "policy/neutrality.policy.json",
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["blockers"])

    def test_release_performance_budget_is_an_accepted_policy_source(self) -> None:
        payload = validate_neutrality_performance(
            scanner_path=ROOT / "src/agent_lifecycle/neutrality/scanner.py",
            policy_path=ROOT / "policy/performance-budgets.json",
        )
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["limits"]["maxSimpleLiteralRules"], 64)


if __name__ == "__main__":
    unittest.main()
