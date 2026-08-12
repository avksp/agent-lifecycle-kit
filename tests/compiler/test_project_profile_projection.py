from __future__ import annotations

import unittest

from agent_lifecycle.compiler.task_packets import _strategy_projection


class ProjectProfilePacketProjectionTests(unittest.TestCase):
    def test_packet_strategy_projection_carries_profile_digest(self) -> None:
        projection = _strategy_projection(
            {
                "schemaVersion": "agent-execution-strategy.v1",
                "strategyDigest": "a" * 64,
                "projectProfileDigest": "b" * 64,
                "lineage": {"taskId": "WS-01", "operationId": "op"},
                "phaseRoutes": [{"phase": "task-implementation", "modelClass": "standard-code"}],
                "quality": {"resolvedRiskTier": "S0", "qualityFloor": "standard"},
                "packet": {"mode": "COMPACT", "authorityPreserved": True},
                "sourceDecisionDigests": {},
            },
            task_id="WS-01",
        )

        self.assertEqual(projection["projectProfileDigest"], "b" * 64)


if __name__ == "__main__":
    unittest.main()
