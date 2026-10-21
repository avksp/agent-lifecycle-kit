from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.contracts import canonical_digest

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests/metrics/fixtures/release-2-6-accounting-baseline.json"


class AuditEfficiencyCommandTests(unittest.TestCase):
    def test_cli_compares_deterministic_plan_pairs_without_native_savings(self):
        measurement = json.loads(BASELINE.read_text(encoding="utf-8"))
        observation = {
            "findings": [],
            "readiness": "READY_TO_FREEZE",
            "blockingGates": [],
            "packetBytes": 100,
            "selectedNodes": 5,
            "selectedEdges": 3,
        }
        measurement["planReviewPairs"] = [
            {
                "caseId": "synthetic",
                "full": observation,
                "delta": {**observation, "packetBytes": 80, "selectedNodes": 2},
            }
        ]
        measurement["inputDigest"] = canonical_digest({k: v for k, v in measurement.items() if k != "inputDigest"})
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "measurement.json"
            source.write_text(json.dumps(measurement), encoding="utf-8")
            code, report = _run_cli(
                [
                    "metrics",
                    "audit-efficiency",
                    "--input",
                    str(source),
                    "--out",
                    str(Path(tmp) / "report.json"),
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "NO_COMPARISON")
        self.assertEqual(report["planReviewComparison"]["status"], "PASS")
        self.assertIsNone(report["planReviewComparison"]["candidateModelTokens"]["value"])

    def test_cli_writes_single_sample_report_without_reduction_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            args = [
                "metrics",
                "audit-efficiency",
                "--input",
                str(BASELINE),
                "--out",
                str(output),
            ]

            code, report = _run_cli(args)
            written = json.loads(output.read_text(encoding="utf-8"))
            second_code, second = _run_cli(args)

        self.assertEqual(code, 0)
        self.assertEqual(report, written)
        self.assertEqual(report["status"], "NO_COMPARISON")
        self.assertTrue(report["qualityFloorPreserved"])
        self.assertTrue(report["advisoryOnly"])
        self.assertFalse(report["autoApply"])
        self.assertEqual(report["comparison"]["sampleCount"], 1)
        self.assertEqual(
            report["comparison"]["tokenReductionPercent"],
            {"status": "UNAVAILABLE", "value": None, "reason": "comparison-sample-required"},
        )
        self.assertEqual(second_code, 2)
        self.assertEqual(second["code"], "cli-io-error")

    def test_cli_rejects_unavailable_metric_with_invented_zero(self) -> None:
        measurement = json.loads(BASELINE.read_text(encoding="utf-8"))
        measurement["views"]["implementation"]["tokens"]["value"] = 0
        measurement["inputDigest"] = canonical_digest(
            {key: value for key, value in measurement.items() if key != "inputDigest"}
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "invalid.json"
            output = root / "report.json"
            source.write_text(json.dumps(measurement), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "metrics",
                    "audit-efficiency",
                    "--input",
                    str(source),
                    "--out",
                    str(output),
                ]
            )
            output_exists = output.exists()

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "audit-efficiency-input-invalid")
        self.assertIn(
            "audit-efficiency-unavailable-has-value",
            {item["code"] for item in payload["details"]["validation"]["blockers"]},
        )
        self.assertFalse(output_exists)

    def test_cli_rejects_invalid_comparison_before_writing(self) -> None:
        comparison = json.loads(BASELINE.read_text(encoding="utf-8"))
        comparison["sourceRevision"] = "stale-without-digest-update"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison_path = root / "comparison.json"
            output = root / "report.json"
            comparison_path.write_text(json.dumps(comparison), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "metrics",
                    "audit-efficiency",
                    "--input",
                    str(BASELINE),
                    "--comparison",
                    str(comparison_path),
                    "--out",
                    str(output),
                ]
            )
            output_exists = output.exists()

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "audit-efficiency-comparison-invalid")
        self.assertEqual(payload["details"]["index"], 0)
        self.assertFalse(output_exists)


if __name__ == "__main__":
    unittest.main()
