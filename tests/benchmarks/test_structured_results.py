from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.benchmarks.contracts import (
    build_benchmark_run_receipt,
    build_structured_result_measurement,
    load_suite,
    load_task,
    validate_benchmark_run_receipt,
    validate_structured_result_measurement,
)
from agent_lifecycle.benchmarks.qualification import qualify_structured_result_runs
from agent_lifecycle.contracts import canonical_digest

ROOT = Path(__file__).resolve().parents[2]
SUITE_PATH = ROOT / "benchmarks/reference-tasks/manifest.json"


class StructuredResultBenchmarkTests(unittest.TestCase):
    def test_measurement_rejects_repair_budget_over_two(self) -> None:
        measurement = build_structured_result_measurement(
            operation_id="reference-evaluation",
            mode="JSON_ENFORCED",
            valid=True,
            repair_attempts=3,
            selection_digest="a" * 64,
            required_schema_digest="b" * 64,
            validation_digest="c" * 64,
            fixture_results={"positive": True, "boundary": True, "malformed": True},
        )

        validation = validate_structured_result_measurement(measurement)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("structured-result-measurement-repair-attempts", {item["code"] for item in validation["blockers"]})

    def test_structured_qualification_requires_complete_minimums(self) -> None:
        suite = load_suite(SUITE_PATH)
        task = load_task(suite, "rt01-planning")
        result = qualify_structured_result_runs([_receipt(task, "one")], suite=suite)

        self.assertEqual(result["status"], "NO_RECOMMENDATION")
        self.assertTrue(result["decision"]["advisoryOnly"])
        self.assertFalse(result["decision"]["automaticRouteAdoptionEligible"])

    def test_structured_qualification_accepts_only_complete_five_by_two_sample(self) -> None:
        suite = load_suite(SUITE_PATH)
        receipts = []
        for row in suite.payload["tasks"]:
            task = load_task(suite, row["id"])
            receipts.extend([_receipt(task, "one"), _receipt(task, "two")])

        result = qualify_structured_result_runs(receipts, suite=suite)

        self.assertEqual(result["status"], "QUALIFIED")
        self.assertEqual(result["routes"][0]["structuredResult"]["measurementCount"], 10)
        self.assertEqual(result["routes"][0]["structuredResult"]["repairAttempts"], 0)

    def test_invalid_structured_measurement_blocks_receipt(self) -> None:
        suite = load_suite(SUITE_PATH)
        task = load_task(suite, "rt01-planning")
        measurement = _measurement()
        measurement["repairAttempts"] = 4
        receipt = _receipt(task, "one", measurement=measurement)

        validation = validate_benchmark_run_receipt(receipt, suite=suite)

        self.assertEqual(validation["status"], "FAIL")


def _receipt(task, run_id: str, *, measurement: dict | None = None) -> dict:
    route = {"adapterClass": "wrapper", "routeClass": "structured", "routeDigest": canonical_digest({"route": "structured"})}
    return build_benchmark_run_receipt(
        receipt_id=f"structured-{task.row['id']}-{run_id}",
        task={
            "taskId": task.row["id"],
            "taskVersion": task.row["version"],
            "taskDigest": task.task_digest,
            "family": task.row["family"],
            "tier": task.row["tier"],
            "shape": task.row["shape"],
        },
        route=route,
        environment={"environmentClass": "local", "environmentDigest": canonical_digest({"environment": "stable"})},
        scorer={"scorerClass": "oracle", "scorerDigest": canonical_digest({"scorer": "stable"})},
        source={"sourceClass": "structured-fixture", "sourceDigest": canonical_digest({"source": run_id})},
        completed=True,
        quality={"criteriaTotal": 3, "criteriaPassed": 3, "falseAcceptance": False, "measurementGap": []},
        measurements={"usageConfidence": "ATTESTED", "tokens": 10, "elapsedMilliseconds": 5, "retries": 0, "remediations": 0},
        structured_result=measurement or _measurement(),
    )


def _measurement() -> dict:
    return build_structured_result_measurement(
        operation_id="reference-evaluation",
        mode="JSON_ENFORCED",
        valid=True,
        repair_attempts=0,
        selection_digest="a" * 64,
        required_schema_digest="b" * 64,
        validation_digest="c" * 64,
        fixture_results={"positive": True, "boundary": True, "malformed": True},
    )


if __name__ == "__main__":
    unittest.main()
