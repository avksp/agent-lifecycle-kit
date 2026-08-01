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

    def test_metrics_recommend_cli_writes_report_and_compact_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_a = root / "cost-a.json"
            report_b = root / "cost-b.json"
            recommendation_path = root / "recommendation.json"
            summary_path = root / "recommendation-summary.json"
            task_packet = root / "task-packet.json"
            report_a.write_text(json.dumps(_cost_report()), encoding="utf-8")
            report_b.write_text(json.dumps(_cost_report()), encoding="utf-8")
            task_packet.write_text(json.dumps(_recommendation_summary_task_packet()), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "metrics",
                    "recommend",
                    "--report",
                    str(report_a),
                    "--report",
                    str(report_b),
                    "--task-shape",
                    "feature",
                    "--current-mode",
                    "standard",
                    "--out",
                    str(recommendation_path),
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
            self.assertTrue(recommendation_path.is_file())
            self.assertTrue(summary_path.is_file())

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-lifecycle-recommendation.v1")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["recommendedMode"], "standard")
        self.assertFalse(payload["autoApply"])
        self.assertTrue(payload["qualityFloorPreserved"])
        self.assertEqual(context_code, 0)
        self.assertEqual(context_payload["status"], "PASS")

    def test_metrics_learning_cli_writes_index_signals_and_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_a = root / "outcome-a.json"
            artifact_b = root / "outcome-b.json"
            index_path = root / "outcome-index.json"
            signals_path = root / "quality-signals.json"
            recommendation_path = root / "learning-recommendation.json"
            summary_path = root / "learning-summary.json"
            artifact_a.write_text(json.dumps(_outcome("WS-01", mode="light", tokens=800)), encoding="utf-8")
            artifact_b.write_text(json.dumps(_outcome("WS-02", mode="light", tokens=900)), encoding="utf-8")

            code, index = _run_cli([
                "metrics",
                "outcome-index",
                "--artifact",
                str(artifact_a),
                "--artifact",
                str(artifact_b),
                "--out",
                str(index_path),
            ])
            signal_code, signals = _run_cli(["metrics", "quality-signals", "--index", str(index_path), "--out", str(signals_path)])
            recommendation_code, recommendation = _run_cli(
                [
                    "metrics",
                    "learn-recommend",
                    "--signals",
                    str(signals_path),
                    "--task-shape",
                    "small-fix",
                    "--current-mode",
                    "strict",
                    "--out",
                    str(recommendation_path),
                    "--summary-out",
                    str(summary_path),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(index["schemaVersion"], "agent-task-outcome-index.v1")
        self.assertEqual(signal_code, 0)
        self.assertEqual(signals["schemaVersion"], "agent-quality-cost-signals.v1")
        self.assertEqual(recommendation_code, 0)
        self.assertEqual(recommendation["schemaVersion"], "agent-lifecycle-recommendation.v1")
        self.assertEqual(recommendation["recommendedMode"], "light")
        self.assertTrue(recommendation["advisoryOnly"])
        self.assertFalse(recommendation["autoApply"])


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


def _outcome(task_id: str, *, mode: str, tokens: int) -> dict[str, object]:
    return {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "packageId": "package",
        "taskId": task_id,
        "taskShape": "small-fix",
        "lifecycleMode": mode,
        "routeClass": "local-code",
        "status": "PASS",
        "commands": [{"id": "VAL", "exitCode": 0}],
        "usage": {
            "inputTokens": tokens,
            "outputTokens": 50,
            "billableTokens": tokens + 50,
            "wallSeconds": 5,
            "toolCalls": 1,
        },
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


def _recommendation_summary_task_packet() -> dict[str, object]:
    packet = _cost_summary_task_packet()
    packet["task"]["title"] = "Review lifecycle recommendation"
    packet["task"]["plannedItems"] = ["R-RECOMMENDATION"]
    packet["task"]["acceptanceIds"] = ["AC-RECOMMENDATION"]
    packet["task"]["evidenceIds"] = ["EV-RECOMMENDATION"]
    packet["specification"]["requirements"] = ["R-RECOMMENDATION"]
    packet["validation"]["acceptanceIds"] = ["AC-RECOMMENDATION"]
    packet["validation"]["evidenceIds"] = ["EV-RECOMMENDATION"]
    packet["acceptance"] = [{"id": "AC-RECOMMENDATION", "statement": "recommendation summary fits"}]
    return packet


if __name__ == "__main__":
    unittest.main()
