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

    def test_lifecycle_mode_cannot_be_below_quality_floor(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            resolve_model_route(
                _request(
                    phase="triage",
                    tier="S1",
                    lifecycle_mode="light",
                    quality_floor="standard",
                ),
                _routing_profile(),
            )

        self.assertEqual(raised.exception.code, "model-route-lifecycle-floor")

    def test_light_lifecycle_mode_can_choose_budget_route(self) -> None:
        decision = resolve_model_route(
            _request(
                phase="triage",
                tier="S1",
                lifecycle_mode="light",
                quality_floor="light",
            ),
            _routing_profile(),
        )

        self.assertEqual(decision["modelClass"], "budget")
        self.assertIn("lifecycle-mode-light", decision["reasonCodes"])
        self.assertIn("quality-floor-light", decision["reasonCodes"])

    def test_api_contract_failure_escalates_budget_to_standard_code(self) -> None:
        decision = resolve_model_route(
            _request(
                phase="triage",
                tier="S0",
                capabilities=["text", "json", "tool-use"],
                failure_signals={
                    "failureClass": "api-contract",
                    "confidence": "HIGH",
                    "validationStatus": "FAIL",
                    "classificationDigest": "a" * 64,
                },
            ),
            _routing_profile(),
        )

        self.assertEqual(decision["modelClass"], "standard-code")
        self.assertTrue(decision["escalation"]["escalated"])
        self.assertEqual(decision["escalation"]["ladderStep"], "standard-implementation")
        self.assertIn("failure-class-api-contract", decision["reasonCodes"])
        self.assertIn("failure-classification-digest-bound", decision["reasonCodes"])

    def test_security_failure_routes_to_stronger_review_and_recommends_cross_check(self) -> None:
        decision = resolve_model_route(
            _request(
                phase="task-implementation",
                tier="S1",
                risk_flags={"security": True},
                failure_signals={"failureClass": "security-bug", "retryCount": 1},
            ),
            _routing_profile(),
        )

        self.assertEqual(decision["modelClass"], "strong-reasoning")
        self.assertEqual(decision["escalation"]["ladderStep"], "stronger-review")
        self.assertTrue(decision["escalation"]["optionalCrossCheckRecommended"])

    def test_repeated_failure_never_downgrades_previous_model_class(self) -> None:
        decision = resolve_model_route(
            _request(
                phase="triage",
                tier="S0",
                failure_signals={
                    "failureClass": "edge-case",
                    "retryCount": 1,
                    "previousModelClass": "standard-code",
                },
            ),
            _routing_profile(),
        )

        self.assertEqual(decision["modelClass"], "standard-code")
        self.assertIn("no-downgrade-after-failure", decision["reasonCodes"])
        self.assertTrue(decision["escalation"]["downgradeBlocked"])

    def test_failure_signals_reject_provider_model_names(self) -> None:
        with self.assertRaises(LifecycleError) as raised:
            resolve_model_route(
                _request(
                    phase="triage",
                    tier="S0",
                    failure_signals={"failureClass": "edge-case", "providerModel": "host-specific"},
                ),
                _routing_profile(),
            )

        self.assertEqual(raised.exception.code, "invalid-model-route-request")


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
    lifecycle_mode: str | None = None,
    quality_floor: str | None = None,
    failure_signals: dict | None = None,
) -> dict:
    request = {
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
    if lifecycle_mode is not None:
        request["lifecycleMode"] = lifecycle_mode
    if quality_floor is not None:
        request["qualityFloor"] = quality_floor
    if failure_signals is not None:
        request["failureSignals"] = failure_signals
    return request


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
