from __future__ import annotations

import copy
import unittest

from tests.policy.test_execution_strategy import ExecutionStrategyTests
from agent_lifecycle.policy.execution_strategy import execution_strategy_summary


class ExecutionStrategyProjectProfileTests(ExecutionStrategyTests):
    def test_strategy_and_summary_carry_project_profile_digest(self) -> None:
        strategy = self._resolve()
        strategy["projectProfileDigest"] = "d" * 64
        strategy["strategyDigest"] = self._digest(strategy)
        summary = execution_strategy_summary(strategy)

        self.assertEqual(summary["projectProfileDigest"], "d" * 64)

    def test_legacy_strategy_summary_omits_profile_digest(self) -> None:
        strategy = self._resolve()
        strategy["strategyDigest"] = self._digest(strategy)
        self.assertNotIn("projectProfileDigest", execution_strategy_summary(strategy))

    @staticmethod
    def _digest(strategy: dict) -> str:
        from agent_lifecycle.contracts import canonical_digest

        return canonical_digest({key: value for key, value in strategy.items() if key != "strategyDigest"})


if __name__ == "__main__":
    unittest.main()
