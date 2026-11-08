from __future__ import annotations

import unittest

from agent_lifecycle.policy.execution_strategy import execution_strategy_summary
from tests.policy.test_execution_strategy import ExecutionStrategyTests


class ExecutionStrategyProjectProfileTests(ExecutionStrategyTests):
    def test_stage_references_are_local_defaults_and_preserve_existing_risk_floor(self) -> None:
        from agent_lifecycle.project.merge import build_effective_project_profile

        profile = {"schemaVersion": "agent-project-workflow-profile.v1", "profileId": "stage", "defaultAdapter": "codex", "defaultMode": "auto", "defaultRisk": "auto", "policies": {"executionBindings": ".alk/host-launch/registry.json"}, "stages": {"audit": {"executionBindingRefs": ["primary", "reserve"]}}, "productionPromotionClaimed": False}
        effective = build_effective_project_profile(profile)
        self.assertEqual(effective["stages"]["audit"]["executionBindingRefs"], ["primary", "reserve"])
        self.assertFalse(effective["authority"]["planBound"])
        self.assertFalse(effective["productionPromotionClaimed"])

    def test_strategy_and_summary_carry_project_profile_digest(self) -> None:
        strategy = self._resolve(
            project_profile_digest="d" * 64,
            project_profile_path=".alk/project-profile.json",
        )
        summary = execution_strategy_summary(strategy)

        self.assertEqual(summary["projectProfileDigest"], "d" * 64)

    def test_legacy_strategy_summary_omits_profile_digest(self) -> None:
        strategy = self._resolve()
        self.assertNotIn("projectProfileDigest", execution_strategy_summary(strategy))

    @staticmethod
    def _digest(strategy: dict) -> str:
        from agent_lifecycle.contracts import canonical_digest

        return canonical_digest({key: value for key, value in strategy.items() if key != "strategyDigest"})


if __name__ == "__main__":
    unittest.main()
