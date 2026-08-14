from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.benchmarks import build_benchmark_run_receipt
from agent_lifecycle.benchmarks.contracts import load_suite, load_task
from agent_lifecycle.contracts import canonical_digest

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"


class BenchmarkQualificationCliTests(unittest.TestCase):
    def test_sample_command_is_deterministic_and_writes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sample.json"
            code, payload = _run_cli(
                ["benchmark", "sample", "--suite", str(SUITE), "--seed", "cli", "--out", str(out)]
            )
            written = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(payload["schemaVersion"], "agent-benchmark-stratified-sample.v1")
        self.assertEqual(written, payload)

    def test_receipt_check_and_qualification_commands_are_read_only(self) -> None:
        suite = load_suite(SUITE)
        task = load_task(suite, "rt01-planning")
        receipt = build_benchmark_run_receipt(
            receipt_id="cli-run",
            task={
                "taskId": task.row["id"],
                "taskVersion": task.row["version"],
                "taskDigest": task.task_digest,
                "family": task.row["family"],
                "tier": task.row["tier"],
                "shape": task.row["shape"],
            },
            route={"adapterClass": "wrapper", "routeClass": "standard", "routeDigest": canonical_digest({"route": "cli"})},
            environment={"environmentClass": "local", "environmentDigest": canonical_digest({"environment": "cli"})},
            scorer={"scorerClass": "oracle", "scorerDigest": canonical_digest({"scorer": "cli"})},
            source={"sourceClass": "external-receipt", "sourceDigest": canonical_digest({"source": "cli"})},
            completed=True,
            quality={"criteriaTotal": 1, "criteriaPassed": 1, "falseAcceptance": False, "measurementGap": []},
            measurements={"usageConfidence": "ATTESTED", "tokens": 1, "elapsedMilliseconds": 1, "retries": 0, "remediations": 0},
        )
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            code, checked = _run_cli(
                ["benchmark", "receipt-check", "--suite", str(SUITE), "--receipt", str(receipt_path)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(checked["status"], "PASS")
            code, report = _run_cli(
                ["benchmark", "qualify", "--suite", str(SUITE), "--receipt", str(receipt_path)]
            )

        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "NO_RECOMMENDATION")


if __name__ == "__main__":
    unittest.main()
