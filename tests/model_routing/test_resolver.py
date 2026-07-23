from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.model_routing import resolve_model_route  # noqa: E402


class ModelRouteResolverTests(unittest.TestCase):
    def test_deterministic_validation_uses_no_model(self) -> None:
        decision = resolve_model_route(
            _request(phase="deterministic-validation", tier="S1"),
            _routing_profile(),
        )
        self.assertEqual(decision["modelClass"], "no-model")
        self.assertFalse(decision["requiresUsageReceipt"])
        self.assertEqual(decision["maxBillableTokens"], 0)

    def test_s0_low_risk_routes_to_budget_without_host_profile(self) -> None:
        decision = resolve_model_route(
            _request(phase="triage", tier="S0", capabilities=["text", "json"]),
            _routing_profile(),
        )
        self.assertEqual(decision["modelClass"], "budget")
        self.assertIn("tier-s0", decision["reasonCodes"])

    def test_s2_security_review_routes_to_strong_reasoning(self) -> None:
        decision = resolve_model_route(
            _request(phase="security-review", tier="S2", risk_flags={"security": True}),
            _routing_profile(),
        )
        self.assertEqual(decision["modelClass"], "strong-reasoning")
        self.assertTrue(decision["criticalReview"])

    def test_local_only_final_audit_accepts_calibrated_local_strong_review(self) -> None:
        decision = resolve_model_route(
            _request(
                phase="final-audit",
                tier="S2",
                capabilities=["text", "json", "tool-use", "deep-review"],
                policy="local-only",
                user_policy={"localModelsAllowed": True, "cloudModelsAllowed": False},
            ),
            _routing_profile(),
            host_profile=_host_profile(local_strong=True),
        )
        self.assertEqual(decision["modelClass"], "local-strong-review")
        self.assertIn("local-only", decision["reasonCodes"])

    def test_local_only_final_audit_rejects_local_compact_only_profile(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            resolve_model_route(
                _request(
                    phase="final-audit",
                    tier="S2",
                    capabilities=["text", "json", "tool-use", "deep-review"],
                    policy="local-only",
                    user_policy={"localModelsAllowed": True, "cloudModelsAllowed": False},
                ),
                _routing_profile(),
                host_profile=_host_profile(local_strong=False),
            )
        self.assertEqual(raised.exception.code, "model-route-unsupported")

    def test_context_window_must_fit_selected_host_binding(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            resolve_model_route(
                _request(
                    phase="task-implementation",
                    tier="S1",
                    target_window="64k",
                    capabilities=["text", "json", "tool-use", "code-edit"],
                    policy="local-only",
                    user_policy={"localModelsAllowed": True, "cloudModelsAllowed": False},
                ),
                _routing_profile(),
                host_profile=_host_profile(local_strong=True),
            )
        self.assertEqual(raised.exception.code, "model-route-unsupported")


def _routing_profile() -> dict:
    return json.loads((ROOT / "profiles/model-routing-profile.v1.json").read_text(encoding="utf-8"))


def _request(
    *,
    phase: str,
    tier: str,
    capabilities: list[str] | None = None,
    risk_flags: dict | None = None,
    target_window: str = "8k",
    policy: str = "balanced",
    user_policy: dict | None = None,
) -> dict:
    return {
        "schemaVersion": "agent-lifecycle-model-route-request.v1",
        "operationId": "route-op",
        "phase": phase,
        "sddTier": tier,
        "riskFlags": risk_flags or {},
        "capabilityRequirements": capabilities or ["text", "json", "tool-use"],
        "targetContextWindow": target_window,
        "routingPolicy": policy,
        "budgetClass": "normal",
        "userPolicy": user_policy or {"localModelsAllowed": False, "cloudModelsAllowed": True},
    }


def _host_profile(*, local_strong: bool) -> dict:
    bindings = {
        "local-compact": {
            "providerModel": "host-specific-compact",
            "contextWindow": "8k",
            "capabilities": ["text", "json"],
            "jsonReliability": "best-effort",
            "toolUse": "unsupported",
            "allowedForTiers": ["S0"],
            "allowedForPhases": ["triage", "task-implementation"],
            "usageAccounting": "host-attested",
            "dataPolicy": "local-only",
            "calibrationStatus": "PASSED",
        },
        "local-standard-code": {
            "providerModel": "host-specific-local-code",
            "contextWindow": "32k",
            "capabilities": ["text", "json", "tool-use", "code-edit"],
            "jsonReliability": "strict",
            "toolUse": "supported",
            "allowedForTiers": ["S0", "S1"],
            "allowedForPhases": ["task-implementation"],
            "usageAccounting": "host-attested",
            "dataPolicy": "local-only",
            "calibrationStatus": "PASSED",
        },
    }
    if local_strong:
        bindings["local-strong-review"] = {
            "providerModel": "host-specific-local-review",
            "contextWindow": "32k",
            "capabilities": ["text", "json", "tool-use", "deep-review"],
            "jsonReliability": "strict",
            "toolUse": "supported",
            "allowedForTiers": ["S1", "S2"],
            "allowedForPhases": ["final-audit", "security-review", "performance-review", "independent-review"],
            "usageAccounting": "host-attested",
            "dataPolicy": "local-only",
            "calibrationStatus": "PASSED",
            "reviewStrategy": "large-context-or-sliced-review",
        }
    return {
        "schemaVersion": "agent-lifecycle-host-model-profile.v1",
        "host": "local-host",
        "profileId": "test-local-profile",
        "bindings": bindings,
    }


if __name__ == "__main__":
    unittest.main()
