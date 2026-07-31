from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.metrics import build_usage_export, validate_usage_export  # noqa: E402


class UsageExportTests(unittest.TestCase):
    def test_local_model_export_has_tokens_resources_and_no_money(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "local-usage.json"
            _write_json(
                artifact,
                {
                    "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
                    "adapterId": "local-agent",
                    "runId": "run-1",
                    "packageId": "pkg",
                    "taskId": "WS-01",
                    "operationId": "op-1",
                    "usage": {
                        "inputTokens": 120,
                        "outputTokens": 30,
                        "toolCalls": 2,
                        "cumulativeContextBytes": 4096,
                        "wallSeconds": 1.25,
                    },
                    "receiptDigest": "a" * 64,
                },
            )

            export = build_usage_export(artifact_paths=[artifact], project_root=root)
            validation = validate_usage_export(export)

            self.assertEqual(validation["status"], "PASS")
            self.assertEqual(export["entries"][0]["tokens"], {"input": 120, "output": 30, "total": 150})
            self.assertEqual(export["entries"][0]["resources"]["contextBytes"], 4096)
            self.assertEqual(export["entries"][0]["durationMs"], 1250)
            self.assertNotIn("monetary", export["entries"][0])
            self.assertEqual(export["totals"]["hostReportedCost"]["entryCount"], 0)

    def test_metered_host_export_allows_nullable_host_reported_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "metered-usage.json"
            _write_json(
                artifact,
                {
                    "schemaVersion": "agent-host-operation-receipt.v1",
                    "host": "metered-host",
                    "runId": "run-1",
                    "taskId": "WS-02",
                    "operationId": "op-2",
                    "usage": {
                        "billableTokens": 42,
                        "toolCalls": 1,
                        "cost_usd": None,
                    },
                    "budgetDecision": {"action": "continue", "remainingTokens": 1000},
                },
            )

            export = build_usage_export(artifact_paths=[artifact], project_root=root)
            validation = validate_usage_export(export)

            self.assertEqual(validation["status"], "PASS")
            self.assertEqual(export["entries"][0]["monetary"]["cost_usd"], None)
            self.assertFalse(export["entries"][0]["monetary"]["canonical"])
            self.assertEqual(export["totals"]["tokens"]["total"], 42)
            self.assertEqual(export["totals"]["meteredEntries"], 1)

    def test_validation_rejects_canonical_money_claim(self) -> None:
        export = {
            "schemaVersion": "agent-usage-export.v1",
            "status": "PASS",
            "generatedBy": "test",
            "sourceArtifacts": [],
            "entries": [
                {
                    "entryId": "usage-1",
                    "tokens": {"input": 1, "output": 1, "total": 2},
                    "steps": 1,
                    "resources": {},
                    "durationMs": 0,
                    "monetary": {
                        "hostReported": False,
                        "currency": "USD",
                        "cost_usd": 1.0,
                        "canonical": True,
                    },
                }
            ],
            "totals": {
                "tokens": {"input": 1, "output": 1, "total": 2},
                "steps": 1,
                "durationMs": 0,
                "resources": {},
                "entries": 1,
                "meteredEntries": 1,
                "hostReportedCost": {"currency": "USD", "entryCount": 1, "total": 1.0, "canonical": False},
            },
            "blockers": [],
            "productionPromotionClaimed": False,
        }

        validation = validate_usage_export(export)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("usage-export-monetary-authority", {item["code"] for item in validation["blockers"]})


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
