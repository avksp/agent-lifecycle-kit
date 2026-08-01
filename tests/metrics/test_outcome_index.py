from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from agent_lifecycle.metrics import build_quality_cost_signals, build_task_outcome_index  # noqa: E402


class OutcomeIndexTests(unittest.TestCase):
    def test_outcome_index_groups_receipts_by_task_shape_mode_and_route(self) -> None:
        artifacts = [
            _task_result("WS-01", mode="light", route="budget-code", tokens=1000, attempt=1),
            _completion_gate("WS-01", decision="STOP"),
            _task_result("WS-02", mode="light", route="budget-code", tokens=1200, attempt=2),
            _completion_gate("WS-02", decision="FOLLOW_UP"),
        ]

        first = build_task_outcome_index(artifacts, source_paths=["a.json", "b.json", "c.json", "d.json"])
        second = build_task_outcome_index(artifacts, source_paths=["a.json", "b.json", "c.json", "d.json"])

        self.assertEqual(first["schemaVersion"], "agent-task-outcome-index.v1")
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["taskCount"], 2)
        self.assertEqual(first["groups"][0]["sampleCount"], 2)
        self.assertEqual(first["groups"][0]["successCount"], 2)
        self.assertFalse(first["telemetryStarted"])
        self.assertFalse(first["providerModelLeaderboard"])
        self.assertFalse(first["monetaryFieldsUsed"])
        self.assertEqual(canonical_digest(first), canonical_digest(second))

    def test_quality_cost_signals_are_advisory_and_resource_based(self) -> None:
        index = build_task_outcome_index([
            _task_result("WS-01", mode="light", route="budget-code", tokens=1000),
            _completion_gate("WS-01", decision="STOP"),
            _task_result("WS-02", mode="strict", route="strong-code", tokens=4000),
            _completion_gate("WS-02", decision="STOP"),
        ])

        signals = build_quality_cost_signals(index)

        self.assertEqual(signals["schemaVersion"], "agent-quality-cost-signals.v1")
        self.assertEqual(signals["status"], "PASS")
        self.assertTrue(signals["advisoryOnly"])
        self.assertFalse(signals["autoApply"])
        self.assertFalse(signals["monetaryFieldsUsed"])
        self.assertEqual(signals["compactSummary"]["schemaVersion"], "agent-quality-cost-signals-summary.v1")

    def test_outcome_index_fails_closed_on_invalid_artifact(self) -> None:
        index = build_task_outcome_index([{"schemaVersion": "agent-task-result.v2"}, "bad"])  # type: ignore[list-item]

        self.assertEqual(index["status"], "FAIL")
        self.assertIn("outcome-artifact-type", {item["code"] for item in index["blockers"]})


def _task_result(task_id: str, *, mode: str, route: str, tokens: int, attempt: int = 1) -> dict:
    return {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "packageId": "package",
        "taskId": task_id,
        "attempt": attempt,
        "taskShape": "small-fix",
        "lifecycleMode": mode,
        "routeClass": route,
        "profile": "local",
        "status": "PASS",
        "commands": [{"id": "VAL", "exitCode": 0}],
        "usage": {
            "inputTokens": tokens,
            "outputTokens": 100,
            "billableTokens": tokens + 100,
            "wallSeconds": 10,
            "toolCalls": 2,
        },
        "productionPromotionClaimed": False,
    }


def _completion_gate(task_id: str, *, decision: str) -> dict:
    return {
        "schemaVersion": "agent-completion-gate-receipt.v1",
        "runId": "run",
        "packageId": "package",
        "taskId": task_id,
        "taskShape": "small-fix",
        "status": "PASS",
        "decision": decision,
        "productionPromotionClaimed": False,
    }


if __name__ == "__main__":
    unittest.main()
