from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from agent_lifecycle.metrics import generate_lifecycle_cost_report, validate_lifecycle_cost_report  # noqa: E402


class LifecycleCostTests(unittest.TestCase):
    def test_standard_task_cost_report_separates_pipeline_overhead(self) -> None:
        validation = validate_lifecycle_cost_report(
            {
                "schemaVersion": "agent-lifecycle-cost-report.v1",
                "mode": "standard",
                "entries": [
                    {"category": "implementation", "tokens": 9000, "steps": 4},
                    {"category": "productValidation", "tokens": 2500, "steps": 2},
                    {"category": "pipelineCompliance", "tokens": 2400, "steps": 3},
                    {"category": "coordination", "tokens": 500, "steps": 1},
                ],
                "productionPromotionClaimed": False,
            }
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["totals"]["pipelineCompliance"]["tokens"], 2400)
        self.assertEqual(validation["totals"]["productValidation"]["steps"], 2)
        self.assertLess(validation["ratios"]["pipelineTokenShare"], 0.30)

    def test_pipeline_overhead_requires_reason_when_over_limit(self) -> None:
        validation = validate_lifecycle_cost_report(
            {
                "schemaVersion": "agent-lifecycle-cost-report.v1",
                "mode": "light",
                "entries": [
                    {"category": "implementation", "tokens": 1000, "steps": 1},
                    {"category": "productValidation", "tokens": 200, "steps": 1},
                    {"category": "pipelineCompliance", "tokens": 3000, "steps": 5},
                    {"category": "coordination", "tokens": 100, "steps": 1},
                ],
                "productionPromotionClaimed": False,
            }
        )

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("pipeline-compliance-over-limit", {item["code"] for item in validation["blockers"]})

    def test_strict_pipeline_overhead_can_be_explained(self) -> None:
        validation = validate_lifecycle_cost_report(
            {
                "schemaVersion": "agent-lifecycle-cost-report.v1",
                "mode": "strict",
                "entries": [
                    {"category": "implementation", "tokens": 3000, "steps": 3},
                    {"category": "productValidation", "tokens": 3000, "steps": 3},
                    {"category": "pipelineCompliance", "tokens": 12000, "steps": 10},
                    {"category": "coordination", "tokens": 1000, "steps": 1},
                ],
                "overLimitReason": "Release-sensitive review needed full lifecycle checks.",
                "productionPromotionClaimed": False,
            }
        )

        self.assertEqual(validation["status"], "PASS")

    def test_generated_cost_report_binds_lineage_and_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            usage = _write_json(root / "work/release-1-4/evidence/usage.json", _usage_receipt())
            review = _write_json(root / "task-review.json", _task_review())

            first = generate_lifecycle_cost_report(artifact_paths=[usage, review], mode="standard", root=root)
            second = generate_lifecycle_cost_report(artifact_paths=[usage, review], mode="standard", root=root)
            validation = validate_lifecycle_cost_report(first)

        self.assertEqual(canonical_digest(first), canonical_digest(second))
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(first["usageConfidence"]["attestedEntries"], 1)
        self.assertEqual(first["usageConfidence"]["estimatedEntries"], 1)
        self.assertEqual(first["lineage"]["runIds"], ["run"])
        self.assertEqual(first["lineage"]["taskIds"], ["WS-01"])
        self.assertEqual(first["lineage"]["planDigests"], ["0" * 64])
        self.assertEqual(first["entries"][0]["usageConfidence"], "ATTESTED")
        self.assertEqual(first["entries"][0]["category"], "implementation")
        self.assertEqual(first["entries"][1]["category"], "productValidation")
        self.assertEqual(first["compactSummary"]["schemaVersion"], "agent-lifecycle-cost-summary.v1")

    def test_generated_report_represents_missing_usage_separately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing_usage = _write_json(
                root / "missing-usage.json",
                {
                    "schemaVersion": "agent-lifecycle-model-usage-receipt.v1",
                    "operationId": "op",
                    "runId": "run",
                    "taskId": "WS-01",
                    "planDigest": "0" * 64,
                    "sourceRevision": "source",
                },
            )

            report = generate_lifecycle_cost_report(artifact_paths=[missing_usage], root=root)
            validation = validate_lifecycle_cost_report(report)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(report["usageConfidence"]["missingEntries"], 1)
        self.assertEqual(report["entries"][0]["tokens"], 0)
        self.assertEqual(report["entries"][0]["steps"], 1)
        self.assertEqual(report["compactSummary"]["nextRequiredAction"], "review missing usage entries")

    def test_manual_reports_without_usage_confidence_remain_valid(self) -> None:
        validation = validate_lifecycle_cost_report(
            {
                "schemaVersion": "agent-lifecycle-cost-report.v1",
                "mode": "standard",
                "entries": [
                    {"category": "implementation", "tokens": 1000, "steps": 2},
                    {"category": "productValidation", "tokens": 1000, "steps": 1},
                    {"category": "pipelineCompliance", "tokens": 500, "steps": 1},
                    {"category": "coordination", "tokens": 100, "steps": 1},
                ],
                "productionPromotionClaimed": False,
            }
        )

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["usageConfidence"]["unspecifiedEntries"], 4)


def _write_json(path: Path, payload: dict) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _usage_receipt() -> dict:
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
            "outputTokens": 25,
            "billableTokens": 125,
            "cumulativeContextBytes": 2048,
            "toolCalls": 2,
            "wallSeconds": 3,
        },
        "attestation": {"source": "host", "status": "ATTESTED"},
    }


def _task_review() -> dict:
    return {
        "schemaVersion": "agent-task-review.v2",
        "runId": "run",
        "packageId": "package",
        "taskId": "WS-01",
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "verdict": "ACCEPTED",
        "usageTotals": {"reportedTokens": 50, "toolCalls": 1},
        "resultDigest": "1" * 64,
        "reviewDigest": "2" * 64,
    }


if __name__ == "__main__":
    unittest.main()
