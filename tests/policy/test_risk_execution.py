from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.contracts.schemas import get_schema
from agent_lifecycle.policy.risk_execution import (
    derive_risk_execution_profile,
    resolve_risk_tier,
    validate_risk_execution_policy,
)

ROOT = Path(__file__).resolve().parents[2]


class RiskExecutionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = _load("profiles/risk-execution-policy.v1.json")
        self.routing = _load("profiles/model-routing-profile.v1.json")
        self.baseline = _load("profiles/lifecycle-baselines.v1.json")
        self.host = _load("profiles/hosts/codex-live-profile.v1.json")
        self.manifest = _manifest()
        self.state = _state(self.manifest)

    def test_policy_and_profile_schemas_are_public(self) -> None:
        self.assertEqual(get_schema("agent-risk-execution-policy.v1")["$id"], "agent-risk-execution-policy.v1")
        self.assertEqual(get_schema("agent-risk-execution-profile.v1")["$id"], "agent-risk-execution-profile.v1")

    def test_default_policy_is_valid(self) -> None:
        self.assertEqual(validate_risk_execution_policy(self.policy)["status"], "PASS")

    def test_auto_derives_digest_bound_s2_profile(self) -> None:
        profile = self._derive("auto")
        self.assertEqual(profile["resolvedRiskTier"], "S2")
        self.assertEqual(profile["modelRoute"]["sddTier"], "S2")
        self.assertEqual(profile["resourceCaps"]["maxBillableTokens"], profile["modelRoute"]["maxBillableTokens"])
        self.assertEqual(profile["resourceCaps"]["maxInvocations"], 33)
        self.assertEqual(profile["resourceCaps"]["maxWallSeconds"], 3600)
        self.assertTrue(profile["usageEvidence"]["hostAttestationRequired"])
        self.assertEqual(profile["profileDigest"], canonical_digest({k: v for k, v in profile.items() if k != "profileDigest"}))
        serialized = json.dumps(profile).lower()
        for binding in self.host["bindings"].values():
            self.assertNotIn(binding["providerModel"].lower(), serialized)
        self.assertNotIn("glm-", serialized)

    def test_explicit_lower_tier_is_rejected(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "requested risk cannot be lower"):
            resolve_risk_tier("S2", "S1")

    def test_s1_and_s2_require_host_profile(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "requires a host model profile"):
            derive_risk_execution_profile(
                manifest=self.manifest,
                state=self.state,
                task_id="WS-01",
                adapter_id="codex",
                adapter_host="codex",
                operation_id="route-op",
                source_revision="source",
                requested_risk="auto",
                risk_policy=self.policy,
                routing_profile=self.routing,
                baseline_profile=self.baseline,
                host_profile=None,
            )

    def test_s0_task_implementation_uses_positive_budget_route(self) -> None:
        manifest = _manifest()
        manifest["specification"]["tier"] = "S0"
        manifest["specification"]["tierResolutionRequest"] = {
            "riskFlags": {},
            "capabilityHints": [],
        }
        profile = derive_risk_execution_profile(
            manifest=manifest,
            state=_state(manifest),
            task_id="WS-01",
            adapter_id="codex",
            adapter_host="codex",
            operation_id="route-op",
            source_revision="source",
            requested_risk="auto",
            risk_policy=self.policy,
            routing_profile=self.routing,
            baseline_profile=self.baseline,
            host_profile=None,
        )

        self.assertEqual(profile["modelRoute"]["modelClass"], "standard-code")
        self.assertEqual(profile["resourceCaps"]["maxBillableTokens"], 20000)

    def test_host_profile_must_match_adapter_descriptor_host(self) -> None:
        with self.assertRaisesRegex(LifecycleError, "does not match"):
            derive_risk_execution_profile(
                manifest=self.manifest,
                state=self.state,
                task_id="WS-01",
                adapter_id="claude",
                adapter_host="claude-code",
                operation_id="route-op",
                source_revision="source",
                requested_risk="auto",
                risk_policy=self.policy,
                routing_profile=self.routing,
                baseline_profile=self.baseline,
                host_profile=self.host,
            )

    def _derive(self, requested_risk: str) -> dict:
        return derive_risk_execution_profile(
            manifest=self.manifest,
            state=self.state,
            task_id="WS-01",
            adapter_id="codex",
            adapter_host="codex",
            operation_id="route-op",
            source_revision="source",
            requested_risk=requested_risk,
            risk_policy=self.policy,
            routing_profile=self.routing,
            baseline_profile=self.baseline,
            host_profile=self.host,
        )


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _manifest() -> dict:
    manifest = {
        "schemaVersion": "agent-plan-manifest.v1",
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package"},
        "specification": {
            "tier": "S2",
            "tierResolutionRequest": {
                "riskFlags": {"architecture": True, "security": True},
                "capabilityHints": ["architecture"],
            },
        },
        "workstreams": [{"id": "WS-01"}],
    }
    return manifest


def _state(manifest: dict) -> dict:
    return {
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": canonical_digest(manifest),
        "sourceRevision": "source",
        "tasks": [{"id": "WS-01"}],
    }


if __name__ == "__main__":
    unittest.main()
