from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from agent_lifecycle.host_protocol import NormalizedUsage, build_model_usage_sidecar  # noqa: E402
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

    def test_qualified_sidecar_passes_all_binding_checks(self) -> None:
        decision = _decision()
        receipt = _sidecar(decision, normalizer_status="QUALIFIED", source_kind="host")

        result = validate_usage_receipt(receipt, route_decision=decision, budget_targets=_budget_targets())

        self.assertEqual(result["status"], "PASS", result["checks"])
        self.assertIn("host-usage-normalizer-qualified", {check["id"] for check in result["checks"]})

    def test_fixture_sidecar_cannot_satisfy_usage_gate(self) -> None:
        decision = _decision()
        receipt = _sidecar(decision, normalizer_status="FIXTURE_ONLY", source_kind="fixture")

        result = validate_usage_receipt(receipt, route_decision=decision)

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["checks"][0]["id"], "host-usage-attestation")
        self.assertEqual(result["checks"][1]["id"], "host-usage-normalizer-qualified")

    def test_sidecar_rejects_path_and_digest_tampering(self) -> None:
        decision = _decision()
        receipt = _sidecar(decision, normalizer_status="QUALIFIED", source_kind="host")
        receipt["sourceArtifact"]["localPath"] = "/private/host/output.jsonl"
        receipt["receiptDigest"] = canonical_digest({key: value for key, value in receipt.items() if key != "receiptDigest"})

        with self.assertRaisesRegex(Exception, "must not contain paths"):
            validate_usage_receipt(receipt, route_decision=decision)

        receipt = _sidecar(decision, normalizer_status="QUALIFIED", source_kind="host")
        receipt["usage"]["billableTokens"] += 1
        with self.assertRaisesRegex(Exception, "receiptDigest does not match"):
            validate_usage_receipt(receipt, route_decision=decision)


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


def _sidecar(decision: dict, *, normalizer_status: str, source_kind: str) -> dict:
    return build_model_usage_sidecar(
        usage=NormalizedUsage(input_tokens=120, output_tokens=30, billable_tokens=150),
        operation_id=decision["operationId"],
        adapter_id="qwen-code",
        host="qwen-code",
        model_class=decision["modelClass"],
        provider_model_hash="a" * 64,
        route_decision_digest=decision["decisionDigest"],
        source_bytes=b'{"usage":{"inputTokens":120,"outputTokens":30}}\n',
        source_format="stream-jsonl",
        source_kind=source_kind,
        normalizer_status=normalizer_status,
        normalizer_digest="c" * 64,
    )


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
