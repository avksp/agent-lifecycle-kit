from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import *  # noqa: F401,F403,E402
except ImportError:
    from helpers import *  # noqa: F401,F403,E402


class CliContractMetricsCommandTests(unittest.TestCase):
    def test_contract_policy_and_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "policy.json"

            code, policy = _run_cli(["contract", "policy", "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(policy["schemaVersion"], "agent-public-contract-policy.v1")
            self.assertTrue(out.is_file())

            code, validation = _run_cli(["contract", "check", "--policy", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(validation["schemaVersion"], "agent-public-contract-policy-validation.v1")
            self.assertEqual(validation["status"], "PASS")

    def test_contract_check_cli_fails_closed_on_invalid_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.json"
            policy.write_text(
                json.dumps(
                    {
                        "schemaVersion": "agent-public-contract-policy.v1",
                        "status": "PASS",
                        "rules": {},
                        "requiredCoreSchemas": [],
                        "schemas": [],
                        "cliOutputs": [],
                        "productionPromotionClaimed": False,
                        "policyDigest": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

            code, payload = _run_cli(["contract", "check", "--policy", str(policy)])

        self.assertEqual(code, 2)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-error.v1")
        self.assertEqual(payload["code"], "contract-policy-validation-failed")

    def test_metrics_cost_check_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "cost.json"
            report.write_text(json.dumps(_cost_report()), encoding="utf-8")

            code, payload = _run_cli(["metrics", "cost-check", "--receipt", str(report)])

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-cost-validation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertLessEqual(payload["ratios"]["pipelineTokenShare"], payload["limits"]["maxPipelineTokenShare"])

    def test_metrics_cost_report_cli_writes_report_and_compact_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "usage.json"
            report_path = root / "generated-cost.json"
            summary_path = root / "cost-summary.json"
            task_packet = root / "task-packet.json"
            artifact.write_text(json.dumps(_usage_receipt()), encoding="utf-8")
            task_packet.write_text(json.dumps(_cost_summary_task_packet()), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "metrics",
                    "cost-report",
                    "--project-root",
                    str(root),
                    "--artifact",
                    str(artifact),
                    "--out",
                    str(report_path),
                    "--summary-out",
                    str(summary_path),
                ]
            )
            context_code, context_payload = _run_cli(
                [
                    "context",
                    "check",
                    "--profile",
                    str(ROOT / "profiles/small-context-profile.v1.json"),
                    "--task-packet",
                    str(task_packet),
                    "--summary",
                    str(summary_path),
                    "--target-window",
                    "4k-strict",
                ]
            )
            self.assertTrue(report_path.is_file())
            self.assertTrue(summary_path.is_file())

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-cost-generation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertFalse(payload["liveCallsStarted"])
        self.assertFalse(payload["productionPromotionClaimed"])
        self.assertEqual(context_code, 0)
        self.assertEqual(context_payload["status"], "PASS")


def _cost_report() -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-cost-report.v1",
        "mode": "standard",
        "entries": [
            {"category": "implementation", "tokens": 8000, "steps": 5},
            {"category": "productValidation", "tokens": 3000, "steps": 3},
            {"category": "pipelineCompliance", "tokens": 2200, "steps": 3},
            {"category": "coordination", "tokens": 600, "steps": 1},
        ],
        "productionPromotionClaimed": False,
    }


def _usage_receipt() -> dict[str, object]:
    return {
        "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
        "operationId": "impl-op",
        "runId": "run",
        "packageId": "package",
        "taskId": "WS-01",
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "host": "codex",
        "modelClass": "standard-code",
        "providerModelHash": "redacted",
        "usage": {
            "inputTokens": 100,
            "outputTokens": 20,
            "billableTokens": 120,
            "cumulativeContextBytes": 4096,
            "toolCalls": 1,
            "wallSeconds": 2,
        },
        "attestation": {"source": "host", "status": "ATTESTED"},
    }


def _cost_summary_task_packet() -> dict[str, object]:
    return {
        "schemaVersion": "agent-task-packet.v1",
        "plan": {"packageId": "package", "planRevision": 1, "planDigest": "0" * 64},
        "task": {
            "id": "WS-01",
            "title": "Review lifecycle cost",
            "owner": "worker",
            "reviewer": "reviewer",
            "dependsOn": [],
            "required": True,
            "plannedItems": ["R-COST"],
            "acceptanceIds": ["AC-COST"],
            "evidenceIds": ["EV-COST"],
            "artifactPaths": {},
            "capabilityHints": [],
            "requiredTools": [],
            "executionPolicy": {},
        },
        "ownership": {
            "writes": ["src/agent_lifecycle/metrics"],
            "readOnly": ["profiles/small-context-profile.v1.json"],
            "forbiddenWrites": [],
            "leadOwned": [],
        },
        "specification": {
            "tier": "S1",
            "revision": 1,
            "requirements": ["R-COST"],
            "traceDigest": "1" * 64,
        },
        "context": {"refs": ["profiles/small-context-profile.v1.json"]},
        "validation": {"acceptanceIds": ["AC-COST"], "evidenceIds": ["EV-COST"]},
        "acceptance": [{"id": "AC-COST", "statement": "cost summary fits"}],
    }


if __name__ == "__main__":
    unittest.main()
