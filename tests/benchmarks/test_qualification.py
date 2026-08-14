from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.benchmarks import build_benchmark_run_receipt, qualify_benchmark_runs, select_stratified_tasks
from agent_lifecycle.benchmarks.contracts import load_suite, load_task
from agent_lifecycle.contracts import canonical_digest


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"


class BenchmarkQualificationTests(unittest.TestCase):
    def test_incomplete_route_returns_no_recommendation(self) -> None:
        suite = load_suite(SUITE)
        task = load_task(suite, "rt01-planning")
        receipt = _receipt(task, route="baseline", run_id="one")

        result = qualify_benchmark_runs([receipt], suite=suite)

        self.assertEqual(result["status"], "NO_RECOMMENDATION")
        self.assertTrue(result["routes"][0]["gaps"])

    def test_complete_route_meets_quality_before_resources(self) -> None:
        suite = load_suite(SUITE)
        receipts = []
        for row in suite.payload["tasks"]:
            task = load_task(suite, row["id"])
            receipts.extend([_receipt(task, route="baseline", run_id="one"), _receipt(task, route="baseline", run_id="two")])

        result = qualify_benchmark_runs(
            receipts,
            suite=suite,
            sample=select_stratified_tasks(SUITE, seed="all", max_tasks=24, max_strata=16),
        )

        self.assertEqual(result["status"], "QUALIFIED")
        self.assertTrue(result["decision"]["resourceComparisonAllowed"])
        self.assertEqual(result["routes"][0]["quality"]["falseAcceptanceCount"], 0)


def _receipt(task, *, route: str, run_id: str):
    return build_benchmark_run_receipt(
        receipt_id=f"{route}-{task.row['id']}-{run_id}",
        task={
            "taskId": task.row["id"],
            "taskVersion": task.row["version"],
            "taskDigest": task.task_digest,
            "family": task.row["family"],
            "tier": task.row["tier"],
            "shape": task.row["shape"],
        },
        route={"adapterClass": "wrapper", "routeClass": route, "routeDigest": canonical_digest({"route": route})},
        environment={"environmentClass": "local", "environmentDigest": canonical_digest({"environment": "stable"})},
        scorer={"scorerClass": "oracle", "scorerDigest": canonical_digest({"scorer": "stable"})},
        source={"sourceClass": "external-receipt", "sourceDigest": canonical_digest({"source": run_id})},
        completed=True,
        quality={"criteriaTotal": 3, "criteriaPassed": 3, "falseAcceptance": False, "measurementGap": []},
        measurements={"usageConfidence": "ATTESTED", "tokens": 100, "elapsedMilliseconds": 10, "retries": 0, "remediations": 0},
    )


if __name__ == "__main__":
    unittest.main()
