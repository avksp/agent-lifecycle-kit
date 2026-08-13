from __future__ import annotations

import unittest

from agent_lifecycle.workflow.checkpoint_gate import normalize_context_checkpoint_policy


class PlanAdoptionCheckpointPolicyTests(unittest.TestCase):
    def test_frozen_plan_policy_is_normalized_for_runtime_state(self) -> None:
        normalized = normalize_context_checkpoint_policy(
            {
                "enabled": True,
                "required": True,
                "milestoneEvents": ["task-completed", "plan-adopted", "task-completed"],
                "maxCheckpointsPerRun": 64,
                "retentionPolicy": "retain-latest-with-explicit-delete",
            }
        )
        self.assertEqual(normalized["milestoneEvents"], ["plan-adopted", "task-completed"])
        self.assertEqual(normalized["retentionPolicy"], "retain-latest-with-explicit-delete")


if __name__ == "__main__":
    unittest.main()
