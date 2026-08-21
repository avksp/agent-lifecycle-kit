from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

# Helpers are intentionally imported conditionally for package and file execution.
# ruff: noqa: F405

try:
    from .helpers import *  # noqa: F403
except ImportError:
    from helpers import *  # noqa: F403


class CliModelRoutingCommandTests(unittest.TestCase):
    def test_model_profile_check_cli_validates_routing_profile(self) -> None:
        code, payload = _run_cli(
            [
                "model",
                "profile-check",
                "--profile",
                str(ROOT / "profiles/model-routing-profile.v1.json"),
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-model-routing-profile-validation.v1")
        self.assertIn("strong-reasoning", payload["classes"])

    def test_model_route_cli_outputs_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp) / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-lifecycle-model-route-request.v1",
                        "operationId": "route-op",
                        "phase": "triage",
                        "sddTier": "S0",
                        "riskFlags": {},
                        "capabilityRequirements": ["text", "json"],
                        "targetContextWindow": "8k",
                        "routingPolicy": "balanced",
                        "budgetClass": "normal",
                        "userPolicy": {"localModelsAllowed": False, "cloudModelsAllowed": True},
                    }
                ),
                encoding="utf-8",
            )
            code, payload = _run_cli(
                [
                    "model",
                    "route",
                    "--profile",
                    str(ROOT / "profiles/model-routing-profile.v1.json"),
                    "--request",
                    str(request),
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-lifecycle-model-route-decision.v1")
            self.assertEqual(payload["modelClass"], "budget")

    def test_model_usage_check_cli_fails_unattested_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decision = {
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
            receipt = {
                "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
                "operationId": "route-op",
                "host": "codex",
                "modelClass": "standard-code",
                "providerModelHash": "redacted",
                "routeDecisionDigest": "b" * 64,
                "usage": {
                    "inputTokens": 1,
                    "outputTokens": 1,
                    "billableTokens": 2,
                    "cumulativeContextBytes": 10,
                    "toolCalls": 0,
                    "wallSeconds": 1,
                },
                "attestation": {"source": "host", "status": "MISSING"},
            }
            decision_path = root / "decision.json"
            receipt_path = root / "receipt.json"
            decision_path.write_text(json.dumps(decision), encoding="utf-8")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            code, payload = _run_cli(
                [
                    "model",
                    "usage-check",
                    "--receipt",
                    str(receipt_path),
                    "--route-decision",
                    str(decision_path),
                ]
            )
            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "model-usage-validation-failed")

    def test_tier_resolve_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tier-request.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-sdd-tier-resolution-request.v1",
                        "taskCount": 1,
                        "executableOwners": ["worker"],
                        "capabilityHints": ["bounded-mechanical"],
                        "riskFlags": {},
                        "requirementsBytes": 1200,
                        "externalSpecification": False,
                    }
                ),
                encoding="utf-8",
            )
            code, payload = _run_cli(["tier", "resolve", "--request", str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-sdd-tier-resolution.v1")
            self.assertEqual(payload["tier"], "S0")


if __name__ == "__main__":
    unittest.main()
