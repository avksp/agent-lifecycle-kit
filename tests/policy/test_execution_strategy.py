from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.policy.execution_strategy import (
    DEFERRED_STRATEGY_STATUS,
    deferred_execution_strategy_summary,
    execution_strategy_summary,
    resolve_execution_strategy,
    validate_execution_strategy,
)

ROOT = Path(__file__).resolve().parents[2]


class ExecutionStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _manifest()
        self.lock = {
            "schemaVersion": "agent-plan-lock.v1",
            "packageId": "strategy-package",
            "planRevision": 1,
            "manifestHash": canonical_digest(self.manifest),
        }
        self.state = {
            "runId": "run-1",
            "packageId": "strategy-package",
            "planRevision": 1,
            "planDigest": canonical_digest(self.manifest),
            "stateRevision": 3,
            "sourceRevision": "source-sha",
            "tasks": [{"id": "WS-01", "attemptCount": 0}],
        }

    def test_s2_strategy_preserves_quality_and_full_packet(self) -> None:
        strategy = self._resolve()
        self.assertEqual(strategy["status"], "PASS")
        self.assertEqual(strategy["quality"]["resolvedRiskTier"], "S2")
        self.assertIn(strategy["quality"]["qualityFloor"], {"strict", "release"})
        self.assertEqual(strategy["packet"]["mode"], "FULL")
        self.assertFalse(strategy["authority"]["automaticAdoptionEligible"])
        self.assertFalse(strategy["modelCallsStarted"])
        self.assertFalse(strategy["hostLaunchStarted"])
        self.assertEqual(validate_execution_strategy(strategy)["status"], "PASS")
        summary = execution_strategy_summary(strategy)
        self.assertEqual(summary["strategyDigest"], strategy["strategyDigest"])
        self.assertLess(len(json.dumps(summary)), len(json.dumps(strategy)))

    def test_state_revision_and_lock_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "state revision"):
            self._resolve(expected_revision=2)
        bad_lock = dict(self.lock)
        bad_lock["manifestHash"] = "0" * 64
        with self.assertRaisesRegex(LifecycleError, "manifestHash mismatch"):
            self._resolve(lock=bad_lock)

    def test_validation_rejects_quality_downgrade_and_authority(self) -> None:
        strategy = self._resolve()
        strategy["quality"]["selectedMode"] = "light"
        strategy["authority"]["canAuthorizeImplementation"] = True
        strategy["strategyDigest"] = canonical_digest(
            {key: value for key, value in strategy.items() if key != "strategyDigest"}
        )
        validation = validate_execution_strategy(strategy)
        codes = {item["code"] for item in validation["blockers"]}
        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("strategy-quality-floor-lowered", codes)
        self.assertIn("strategy-authority-escalation", codes)

    def test_raw_intake_summary_is_deferred_without_route(self) -> None:
        summary = deferred_execution_strategy_summary()
        self.assertEqual(summary["status"], DEFERRED_STRATEGY_STATUS)
        self.assertIsNone(summary["implementationModelClass"])
        self.assertIsNone(summary["packetMode"])
        self.assertFalse(summary["automaticAdoptionEligible"])

    def _resolve(
        self,
        *,
        expected_revision: int = 3,
        lock: dict | None = None,
    ) -> dict:
        return resolve_execution_strategy(
            manifest=deepcopy(self.manifest),
            lock=deepcopy(lock or self.lock),
            state=deepcopy(self.state),
            task_id="WS-01",
            adapter_id="codex",
            adapter_host="codex",
            operation_id="strategy-op",
            expected_revision=expected_revision,
            source_revision="source-sha",
            requested_risk="auto",
            risk_policy=_load("profiles/risk-execution-policy.v1.json"),
            routing_profile=_load("profiles/model-routing-profile.v1.json"),
            baseline_profile=_load("profiles/lifecycle-baselines.v1.json"),
            host_profile=_load("profiles/hosts/codex-live-profile.v1.json"),
        )


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _manifest() -> dict:
    return {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "strategy-package", "title": "Architecture change"},
        "specification": {
            "tier": "S2",
            "requirements": [{"id": "R-1", "description": "Review architecture before implementation"}],
            "tierResolutionRequest": {
                "riskFlags": {"architecture": True, "security": True},
                "capabilityHints": ["architecture"],
            },
        },
        "workstreams": [
            {
                "id": "WS-01",
                "title": "Implement architecture change",
                "owner": "worker",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "acceptanceIds": ["AC-1"],
                "evidenceIds": ["EV-1"],
            }
        ],
        "acceptance": {"criteria": [{"id": "AC-1", "requirementIds": ["R-1"], "evidenceIds": ["EV-1"]}]},
    }


if __name__ == "__main__":
    unittest.main()
