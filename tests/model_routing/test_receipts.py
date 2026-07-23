from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.model_routing import validate_usage_receipt  # noqa: E402


class ModelUsageReceiptTests(unittest.TestCase):
    def test_attested_receipt_passes_route_and_budget_checks(self) -> None:
        decision = _decision()
        receipt = _receipt(decision)
        result = validate_usage_receipt(receipt, route_decision=decision, budget_targets=_budget_targets())
        self.assertEqual(result["schemaVersion"], "agent-lifecycle-model-usage-validation.v1")
        self.assertEqual(result["status"], "PASS")

    def test_unattested_receipt_fails_validation(self) -> None:
        decision = _decision()
        receipt = _receipt(decision)
        receipt["attestation"]["status"] = "MISSING"
        result = validate_usage_receipt(receipt, route_decision=decision)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["checks"][0]["id"], "host-usage-attestation")

    def test_budget_overrun_fails_validation(self) -> None:
        decision = _decision()
        receipt = _receipt(decision)
        receipt["usage"]["billableTokens"] = 999999
        result = validate_usage_receipt(receipt, route_decision=decision, budget_targets=_budget_targets())
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(check["id"] == "route-max-billable-tokens" for check in result["checks"]))


def _decision() -> dict:
    return {
        "schemaVersion": "agent-lifecycle-model-route-decision.v1",
        "operationId": "route-op",
        "phase": "task-implementation",
        "sddTier": "S1",
        "routingPolicy": "balanced",
        "modelClass": "standard-code",
        "allowedFallbackModelClasses": ["strong-reasoning"],
        "targetContextWindow": "8k",
        "requiresUsageReceipt": True,
        "maxBillableTokens": 120000,
        "reasonCodes": ["tier-s1"],
        "profileDigest": "a" * 64,
        "decisionDigest": "b" * 64,
    }


def _receipt(decision: dict) -> dict:
    return {
        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
        "operationId": decision["operationId"],
        "host": "codex",
        "modelClass": decision["modelClass"],
        "providerModelHash": "redacted-provider-model",
        "routeDecisionDigest": decision["decisionDigest"],
        "usage": {
            "inputTokens": 12000,
            "outputTokens": 1800,
            "billableTokens": 13800,
            "cumulativeContextBytes": 56000,
            "toolCalls": 4,
            "wallSeconds": 90,
        },
        "attestation": {
            "source": "host",
            "status": "ATTESTED",
        },
    }


def _budget_targets() -> dict:
    return {
        "schemaVersion": "agent-lifecycle-budget-targets.v1",
        "hardCeilings": {
            "S1": {
                "billableTokens": 300000,
                "cumulativeContextBytes": 2097152,
                "toolCalls": 250,
                "wallSeconds": 14400,
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
