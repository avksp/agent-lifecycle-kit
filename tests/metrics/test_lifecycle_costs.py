from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import canonical_digest  # noqa: E402
from agent_lifecycle.metrics import (  # noqa: E402
    build_phase_resource_measurement,
    generate_lifecycle_cost_report,
    validate_lifecycle_cost_report,
)
from agent_lifecycle.metrics.cost_collection import build_lifecycle_cost_summary  # noqa: E402


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

    def test_phase_measurement_uses_declared_totals_instead_of_json_size(self) -> None:
        phase = build_phase_resource_measurement(
            [
                {
                    "phaseId": "audit",
                    "phaseKind": "AUDIT",
                    "tokens": {"input": 700, "output": 300, "total": 1000},
                    "steps": 7,
                    "resources": {},
                    "durationMs": 500,
                    "receiptDigests": [],
                }
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = _write_json(root / "phase.json", phase)
            report = generate_lifecycle_cost_report(artifact_paths=[artifact], root=root)

        self.assertEqual(report["entries"][0]["tokens"], 1000)
        self.assertEqual(report["entries"][0]["steps"], 7)
        self.assertEqual(report["entries"][0]["usageConfidence"], "ESTIMATED")

    def test_coordination_dominance_is_advisory_with_supplied_scope(self) -> None:
        report = {
            "schemaVersion": "agent-lifecycle-cost-report.v1",
            "mode": "standard",
            "notes": "private-input-note-do-not-echo",
            "entries": [
                {"category": category, "tokens": tokens, "steps": 1, "usageConfidence": "ATTESTED"}
                for category, tokens in (("implementation", 1000), ("pipelineCompliance", 100), ("coordination", 99000))
            ],
        }
        validation = validate_lifecycle_cost_report(report)
        summary = build_lifecycle_cost_summary(report)
        observation = validation["processObservation"]

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["blockers"], [])
        self.assertEqual(observation, summary["processObservation"])
        self.assertEqual(observation["confidence"], "ATTESTED")
        self.assertEqual(observation["scope"], "supplied_report_entries")
        self.assertAlmostEqual(observation["reportedSubtotal"]["processTokenShare"], 0.99001)
        self.assertEqual(observation["confirmedSubtotal"]["processOverheadTokens"], 99100)
        self.assertEqual(observation["wholeRunCoverage"]["status"], "UNAVAILABLE")
        self.assertIsNone(observation["wholeRunCoverage"]["processTokenShare"])
        self.assertTrue(observation["warnings"][0]["advisoryOnly"])
        self.assertNotIn(report["notes"], str(observation))
        self.assertIn("suppliedRecordsProcessTokenShare=0.99001", summary["activeDecisions"])

    def test_partial_confidence_never_establishes_whole_run_coverage(self) -> None:
        for confidences in (
            ("MISSING",),
            ("ESTIMATED",),
            (None,),
            ("MISSING", "ESTIMATED", None),
            ("ATTESTED", "MISSING", "ESTIMATED", None),
        ):
            with self.subTest(confidences=confidences):
                entries = [
                    {
                        "category": "coordination",
                        "tokens": 0 if confidence == "MISSING" else 100,
                        "steps": 1,
                        **({"usageConfidence": confidence} if confidence else {}),
                    }
                    for confidence in confidences
                ]
                report = {"schemaVersion": "agent-lifecycle-cost-report.v1", "mode": "release", "entries": entries}
                validation = validate_lifecycle_cost_report(report)
                observation = validation["processObservation"]
                self.assertEqual(validation["status"], "PASS")
                self.assertEqual(observation, build_lifecycle_cost_summary(report)["processObservation"])
                self.assertEqual(observation["reportedSubtotal"]["entryCount"], len(entries))
                self.assertEqual(observation["wholeRunCoverage"]["status"], "UNAVAILABLE")
                self.assertIsNone(observation["wholeRunCoverage"]["processTokenShare"])
                self.assertIsNone(observation["wholeRunCoverage"]["processStepShare"])
                if "ATTESTED" in confidences:
                    self.assertEqual(observation["confirmedSubtotal"]["entryCount"], 1)
                    self.assertEqual(observation["confirmedSubtotal"]["tokens"], 100)
                else:
                    self.assertIsNone(observation["confirmedSubtotal"])

    def test_zero_denominators_remain_unavailable_in_new_observation(self) -> None:
        for tokens, steps in ((0, 1), (1, 0)):
            with self.subTest(tokens=tokens, steps=steps):
                validation = validate_lifecycle_cost_report(
                    {
                        "schemaVersion": "agent-lifecycle-cost-report.v1",
                        "mode": "standard",
                        "entries": [
                            {
                                "category": "implementation",
                                "tokens": tokens,
                                "steps": steps,
                                "usageConfidence": "ATTESTED",
                            }
                        ],
                    }
                )
                subtotal = validation["processObservation"]["confirmedSubtotal"]
                self.assertIsNone(subtotal["processTokenShare"] if tokens == 0 else subtotal["processStepShare"])
                self.assertEqual(validation["ratios"]["pipelineTokenShare"], 0.0)

    def test_empty_observation_does_not_invent_confirmed_zero(self) -> None:
        report = {"schemaVersion": "agent-lifecycle-cost-report.v1", "mode": "standard", "entries": []}
        validation = validate_lifecycle_cost_report(report)
        observation = validation["processObservation"]
        self.assertEqual(validation["status"], "FAIL")
        self.assertEqual(observation["confidence"], "UNAVAILABLE")
        self.assertIsNone(observation["confirmedSubtotal"])
        self.assertIsNone(observation["reportedSubtotal"]["processTokenShare"])
        self.assertIsNone(observation["reportedSubtotal"]["processStepShare"])
        self.assertEqual(observation["warnings"], [])

    def test_generator_deduplicates_resolved_paths_but_keeps_distinct_files(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = _write_json(root / "first.json", _usage_receipt())
            second = _write_json(root / "second.json", _usage_receipt())
            link = root / "alias.json"
            link.symlink_to(first)
            expected_sha = hashlib.sha256(first.read_bytes()).hexdigest()
            report = generate_lifecycle_cost_report(
                artifact_paths=[Path("first.json"), first, root / "./first.json", link, second],
                root=root,
            )

        self.assertEqual(len(report["entries"]), 2)
        self.assertEqual([entry["id"] for entry in report["entries"]], ["artifact-1", "artifact-2"])
        self.assertEqual([source["path"] for source in report["sourceArtifacts"]], ["first.json", "second.json"])
        self.assertEqual([source["sha256"] for source in report["sourceArtifacts"]], [expected_sha, expected_sha])
        self.assertEqual(report["lineage"]["sourceRevisions"], ["source"])
        self.assertEqual(report["processObservation"]["reportedSubtotal"]["tokens"], 250)
        self.assertEqual(report["processObservation"], report["compactSummary"]["processObservation"])
        self.assertEqual(report["processObservation"], validate_lifecycle_cost_report(report)["processObservation"])


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
