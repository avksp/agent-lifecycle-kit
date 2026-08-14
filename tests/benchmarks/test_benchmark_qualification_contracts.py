from __future__ import annotations

import unittest
from pathlib import Path

from agent_lifecycle.benchmarks.contracts import (
    build_benchmark_run_receipt,
    load_suite,
    load_task,
    validate_benchmark_run_receipt,
)
from agent_lifecycle.contracts import canonical_digest


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"


class BenchmarkQualificationContractTests(unittest.TestCase):
    def test_external_receipt_is_lineage_bound_and_side_effect_free(self) -> None:
        suite = load_suite(SUITE)
        task = load_task(suite, "rt01-planning")
        receipt = build_benchmark_run_receipt(
            receipt_id="run-1",
            task={
                "taskId": task.row["id"],
                "taskVersion": task.row["version"],
                "taskDigest": task.task_digest,
                "family": task.row["family"],
                "tier": task.row["tier"],
                "shape": task.row["shape"],
            },
            route={"adapterClass": "wrapper", "routeClass": "standard", "routeDigest": canonical_digest({"route": "a"})},
            environment={"environmentClass": "local", "environmentDigest": canonical_digest({"environment": "a"})},
            scorer={"scorerClass": "oracle", "scorerDigest": canonical_digest({"scorer": "a"})},
            source={"sourceClass": "external-receipt", "sourceDigest": canonical_digest({"source": "a"})},
            completed=True,
            quality={"criteriaTotal": 3, "criteriaPassed": 3, "falseAcceptance": False, "measurementGap": []},
            measurements={"usageConfidence": "ATTESTED", "tokens": 10, "elapsedMilliseconds": 20, "retries": 0, "remediations": 0},
        )

        result = validate_benchmark_run_receipt(receipt, suite=suite)

        self.assertEqual(result["status"], "PASS")
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["hostLaunchStarted"])

    def test_portable_receipt_rejects_commands_and_absolute_paths(self) -> None:
        suite = load_suite(SUITE)
        task = load_task(suite, "rt01-planning")
        receipt = build_benchmark_run_receipt(
            receipt_id="run-2",
            task={
                "taskId": task.row["id"],
                "taskVersion": task.row["version"],
                "taskDigest": task.task_digest,
                "family": task.row["family"],
                "tier": task.row["tier"],
                "shape": task.row["shape"],
            },
            route={"adapterClass": "wrapper", "routeClass": "standard", "routeDigest": canonical_digest({"route": "b"}), "command": "run"},
            environment={"environmentClass": "local", "environmentDigest": canonical_digest({"environment": "b"})},
            scorer={"scorerClass": "oracle", "scorerDigest": canonical_digest({"scorer": "b"})},
            source={"sourceClass": "external-receipt", "sourceDigest": canonical_digest({"source": "b"})},
            completed=True,
            quality={"criteriaTotal": 1, "criteriaPassed": 1, "falseAcceptance": False, "measurementGap": []},
            measurements={"usageConfidence": "ESTIMATED", "tokens": 1, "elapsedMilliseconds": 1, "retries": 0, "remediations": 0},
        )

        result = validate_benchmark_run_receipt(receipt, suite=suite)

        self.assertEqual(result["status"], "FAIL")
        self.assertIn("benchmark-receipt-forbidden-field", {item["code"] for item in result["blockers"]})


if __name__ == "__main__":
    unittest.main()
