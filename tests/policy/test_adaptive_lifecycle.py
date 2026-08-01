from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.policy import build_adaptive_lifecycle_decision, validate_adaptive_lifecycle_decision  # noqa: E402


class AdaptiveLifecyclePolicyTests(unittest.TestCase):
    def test_tight_low_risk_work_is_advisory_by_default(self) -> None:
        decision = build_adaptive_lifecycle_decision(
            _request(taskShape="small-fix", resourceCaps={"maxInvocations": 1}),
            _baselines(),
        )
        validation = validate_adaptive_lifecycle_decision(decision)

        self.assertEqual(decision["status"], "PASS")
        self.assertEqual(decision["recommendedMode"], "light")
        self.assertEqual(decision["qualityFloor"], "light")
        self.assertFalse(decision["applyAutomatically"])
        self.assertTrue(decision["advisoryOnly"])
        self.assertFalse(decision["monetaryFieldsUsed"])
        self.assertEqual(validation["status"], "PASS")

    def test_opt_in_auto_preserves_security_floor(self) -> None:
        decision = build_adaptive_lifecycle_decision(
            _request(
                taskShape="small-fix",
                sddTier="S2",
                riskFlags=["security"],
                automaticSelectionEnabled=True,
            ),
            _baselines(),
        )

        self.assertEqual(decision["status"], "PASS")
        self.assertEqual(decision["qualityFloor"], "strict")
        self.assertEqual(decision["selectedMode"], "strict")
        self.assertTrue(decision["applyAutomatically"])
        self.assertFalse(decision["advisoryOnly"])

    def test_release_proof_sets_release_mode(self) -> None:
        decision = build_adaptive_lifecycle_decision(
            _request(taskShape="feature", requiredEvidence=["release-proof"]),
            _baselines(),
        )

        self.assertEqual(decision["status"], "PASS")
        self.assertEqual(decision["qualityFloor"], "release")
        self.assertEqual(decision["recommendedMode"], "release")

    def test_provider_or_model_keys_are_rejected(self) -> None:
        request = _request()
        request["provider"] = "example"

        decision = build_adaptive_lifecycle_decision(request, _baselines())
        validation = validate_adaptive_lifecycle_decision(decision)

        self.assertEqual(decision["status"], "FAIL")
        self.assertIn("adaptive-request-provider-model-key", {item["code"] for item in decision["blockers"]})
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["decisionStatus"], "FAIL")

    def test_monetary_metadata_requires_metered_mode_and_is_not_used(self) -> None:
        local_decision = build_adaptive_lifecycle_decision(
            _request(resourceCaps={"meteredCostUsd": 0.02}),
            _baselines(),
        )
        metered_decision = build_adaptive_lifecycle_decision(
            _request(budgetMode="metered", resourceCaps={"meteredCostUsd": 0.02}),
            _baselines(),
        )

        self.assertEqual(local_decision["status"], "FAIL")
        self.assertIn("adaptive-request-monetary-field-not-metered", {item["code"] for item in local_decision["blockers"]})
        self.assertEqual(metered_decision["status"], "PASS")
        self.assertFalse(metered_decision["monetaryFieldsUsed"])
        self.assertIn("$.resourceCaps.meteredCostUsd", metered_decision["neutralInputs"]["monetaryMetadataKeys"])

    def test_repeated_attempts_escalate_to_strict(self) -> None:
        decision = build_adaptive_lifecycle_decision(
            _request(taskShape="small-fix", priorAttempts=2),
            _baselines(),
        )

        self.assertEqual(decision["recommendedMode"], "strict")
        self.assertIn("retry-escalation", decision["reasonCodes"])


def _request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schemaVersion": "agent-adaptive-lifecycle-policy-request.v1",
        "taskShape": "feature",
        "sddTier": "S1",
        "riskFlags": [],
        "requiredEvidence": [],
        "priorAttempts": 0,
        "contextTokens": 0,
        "resourceCaps": {},
        "budgetMode": "local",
        "currentMode": "standard",
        "automaticSelectionEnabled": False,
    }
    request.update(overrides)
    return request


def _baselines() -> dict[str, object]:
    return json.loads((ROOT / "profiles/lifecycle-baselines.v1.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
