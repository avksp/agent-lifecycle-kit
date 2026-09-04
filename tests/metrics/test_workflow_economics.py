from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.metrics.cost_collection import generate_lifecycle_cost_report
from agent_lifecycle.metrics.phase_resources import build_phase_resource_measurement
from agent_lifecycle.metrics.workflow_economics import (
    DERIVED_AGGREGATE_STATUSES,
    SOURCE_AVAILABILITY_STATUSES,
    WORKFLOW_METRIC_KEYS,
    build_workflow_metric_set,
    build_workflow_resource_summary,
    validate_workflow_resource_summary,
)


class WorkflowEconomicsTests(unittest.TestCase):
    def test_phase_summary_is_preserved_by_cost_report(self) -> None:
        phase = {
            "phaseId": "audit",
            "phaseKind": "AUDIT",
            "tokens": {"input": 10, "output": 5, "total": 15},
            "steps": 2,
            "resources": {"toolCalls": 2},
            "durationMs": 40,
            "receiptDigests": [],
            "workflowMetrics": {
                "parallelComputeMs": {"status": "MEASURED", "value": 55},
            },
        }
        measurement = build_phase_resource_measurement(
            [phase],
            enclosing_elapsed_wall={"status": "MEASURED", "value": 35},
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json_create(root / "measurement.json", measurement)
            report = generate_lifecycle_cost_report(artifact_paths=[Path("measurement.json")], root=root)

        self.assertEqual(report["workflowEconomics"], [measurement["workflowEconomics"]])
        self.assertEqual(report["compactSummary"]["workflowEconomics"], report["workflowEconomics"])

    def test_missing_source_values_remain_unavailable_in_complete_metric_set(self) -> None:
        metrics = build_workflow_metric_set(
            {
                "modelInputTokens": {"status": "MEASURED", "value": 120},
                "modelCachedInputTokens": {"status": "ESTIMATED", "value": 80},
                "elapsedWallMs": {"status": "TIME_WINDOW_ONLY", "value": 900},
            }
        )

        self.assertEqual(set(metrics), set(WORKFLOW_METRIC_KEYS))
        self.assertEqual(metrics["modelInputTokens"], {"status": "MEASURED", "value": 120})
        self.assertEqual(metrics["modelTurns"], {"status": "UNAVAILABLE", "value": None})
        self.assertNotEqual(metrics["modelTurns"], {"status": "MEASURED", "value": 0})

    def test_derived_statuses_and_time_window_compute_are_rejected_as_sources(self) -> None:
        invalid = (
            ("modelTurns", {"status": "PARTIAL", "value": 1}),
            ("parallelComputeMs", {"status": "TIME_WINDOW_ONLY", "value": 1}),
            ("toolCalls", {"status": "UNAVAILABLE", "value": 0}),
        )
        for name, value in invalid:
            with self.subTest(name=name), self.assertRaises(LifecycleError):
                build_workflow_metric_set({name: value})

        for malformed in ([], "", 0):
            with self.subTest(malformed=malformed), self.assertRaises(LifecycleError):
                build_workflow_metric_set(malformed)  # type: ignore[arg-type]
        with self.assertRaises(LifecycleError):
            build_workflow_resource_summary([], enclosing_elapsed_wall={})

    def test_parallel_compute_sums_but_wall_requires_enclosing_window(self) -> None:
        rows = [
            build_workflow_metric_set(
                {
                    "elapsedWallMs": {"status": "MEASURED", "value": 100},
                    "parallelComputeMs": {"status": "MEASURED", "value": 100},
                }
            ),
            build_workflow_metric_set(
                {
                    "elapsedWallMs": {"status": "MEASURED", "value": 80},
                    "parallelComputeMs": {"status": "MEASURED", "value": 80},
                }
            ),
        ]

        without_window = build_workflow_resource_summary(rows)
        with_window = build_workflow_resource_summary(
            rows,
            enclosing_elapsed_wall={"status": "MEASURED", "value": 110},
        )

        self.assertEqual(without_window["metrics"]["elapsedWallMs"], {"status": "UNAVAILABLE", "value": None})
        self.assertEqual(with_window["metrics"]["elapsedWallMs"], {"status": "MEASURED", "value": 110})
        self.assertEqual(with_window["metrics"]["parallelComputeMs"], {"status": "MEASURED", "value": 180})
        self.assertEqual(validate_workflow_resource_summary(with_window)["status"], "PASS")

    def test_aggregate_overflow_is_rejected_before_artifact_creation(self) -> None:
        rows = [
            build_workflow_metric_set(
                {"toolCalls": {"status": "MEASURED", "value": (1 << 63) - 1}}
            ),
            build_workflow_metric_set({"toolCalls": {"status": "MEASURED", "value": 1}}),
        ]

        with self.assertRaisesRegex(LifecycleError, "aggregate exceeds"):
            build_workflow_resource_summary(rows)

    def test_mixed_and_partial_are_derived_only(self) -> None:
        first = build_workflow_metric_set(
            {
                "toolCalls": {"status": "MEASURED", "value": 2},
                "modelTurns": {"status": "MEASURED", "value": 1},
            }
        )
        second = build_workflow_metric_set(
            {
                "toolCalls": {"status": "ESTIMATED", "value": 3},
            }
        )

        summary = build_workflow_resource_summary([first, second])

        self.assertEqual(summary["sourceAvailabilityStatuses"], list(SOURCE_AVAILABILITY_STATUSES))
        self.assertEqual(summary["derivedAggregateStatuses"], list(DERIVED_AGGREGATE_STATUSES))
        self.assertEqual(summary["metrics"]["toolCalls"], {"status": "MIXED", "value": 5})
        self.assertEqual(summary["metrics"]["modelTurns"], {"status": "PARTIAL", "value": 1})

    def test_digest_and_metric_shape_mutations_fail_validation(self) -> None:
        summary = build_workflow_resource_summary([build_workflow_metric_set()])
        summary["metrics"]["modelTurns"] = {"status": "MEASURED", "value": -1}
        summary["summaryDigest"] = canonical_digest(
            {key: value for key, value in summary.items() if key != "summaryDigest"}
        )

        validation = validate_workflow_resource_summary(summary)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("workflow-metric-value-invalid", {item["code"] for item in validation["blockers"]})


if __name__ == "__main__":
    unittest.main()
