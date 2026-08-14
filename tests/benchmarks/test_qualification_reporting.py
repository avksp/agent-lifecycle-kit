from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.benchmarks import (
    build_benchmark_run_receipt,
    compare_qualified_routes,
    validate_qualified_route_comparison,
)
from agent_lifecycle.benchmarks.contracts import load_suite, load_task
from agent_lifecycle.contracts import canonical_digest


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"


class BenchmarkQualificationReportingTests(unittest.TestCase):
    def test_route_comparison_reports_quality_and_changed_axes(self) -> None:
        suite = load_suite(SUITE)
        baseline = _receipts(suite, "baseline")
        candidate = _receipts(suite, "candidate")

        result = compare_qualified_routes(baseline, candidate, suite=suite)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["lineage"]["changedAxes"], [])
        self.assertEqual(validate_qualified_route_comparison(result)["status"], "PASS")

    def test_different_environment_is_incomparable_not_a_route_win(self) -> None:
        suite = load_suite(SUITE)
        baseline = _receipts(suite, "baseline", environment="one")
        candidate = _receipts(suite, "candidate", environment="two")

        result = compare_qualified_routes(baseline, candidate, suite=suite)

        self.assertEqual(result["status"], "INCOMPARABLE")
        self.assertIn("environment", result["lineage"]["changedAxes"])
        self.assertFalse(result["decision"]["automaticRouteAdoptionEligible"])


def _receipts(suite, route: str, *, environment: str = "stable"):
    result = []
    for row in suite.payload["tasks"]:
        task = load_task(suite, row["id"])
        for run_id in ("one", "two"):
            result.append(
                build_benchmark_run_receipt(
                    receipt_id=f"{route}-{row['id']}-{run_id}",
                    task={
                        "taskId": task.row["id"],
                        "taskVersion": task.row["version"],
                        "taskDigest": task.task_digest,
                        "family": task.row["family"],
                        "tier": task.row["tier"],
                        "shape": task.row["shape"],
                    },
                    route={"adapterClass": "wrapper", "routeClass": route, "routeDigest": canonical_digest({"route": route})},
                    environment={"environmentClass": "local", "environmentDigest": canonical_digest({"environment": environment})},
                    scorer={"scorerClass": "oracle", "scorerDigest": canonical_digest({"scorer": "stable"})},
                    source={"sourceClass": "external-receipt", "sourceDigest": canonical_digest({"source": f"{route}-{run_id}"})},
                    completed=True,
                    quality={"criteriaTotal": 3, "criteriaPassed": 3, "falseAcceptance": False, "measurementGap": []},
                    measurements={"usageConfidence": "ATTESTED", "tokens": 100, "elapsedMilliseconds": 10, "retries": 0, "remediations": 0},
                )
            )
    return result


if __name__ == "__main__":
    unittest.main()
