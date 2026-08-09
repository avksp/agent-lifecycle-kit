from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent_lifecycle.benchmarks.reporting import build_measurements, redact_evaluation_payload

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/benchmarks/fixtures"


class BenchmarkReportingTests(unittest.TestCase):
    def test_mixed_confidence_has_no_unqualified_total(self) -> None:
        submission = json.loads((FIXTURES / "mixed-confidence-usage.json").read_text(encoding="utf-8"))
        measurements, blockers = build_measurements(submission, {"status": "PASS", "checks": []})

        self.assertEqual(blockers, [])
        self.assertEqual(measurements["tokens"]["byConfidence"]["ATTESTED"]["total"], 15)
        self.assertEqual(measurements["tokens"]["byConfidence"]["ESTIMATED"]["total"], 10)
        self.assertEqual(measurements["tokens"]["headline"], {"confidence": "MIXED", "total": None})
        self.assertIn("token-usage-missing", measurements["measurementGaps"])

    def test_estimated_only_total_keeps_its_confidence_label(self) -> None:
        submission = json.loads((FIXTURES / "estimated-usage.json").read_text(encoding="utf-8"))
        measurements, blockers = build_measurements(submission, {"status": "PASS", "checks": []})

        self.assertEqual(blockers, [])
        self.assertEqual(measurements["tokens"]["headline"], {"confidence": "ESTIMATED", "total": 20})

    def test_shared_redaction_removes_secrets_and_local_paths(self) -> None:
        unsafe = json.loads((FIXTURES / "redaction-leak.json").read_text(encoding="utf-8"))
        safe, receipt = redact_evaluation_payload(unsafe)
        rendered = json.dumps(safe)

        self.assertEqual(receipt["status"], "APPLIED")
        self.assertNotIn("example-secret-value", rendered)
        self.assertNotIn("example-key-must-not-survive", rendered)
        self.assertNotIn("C:\\\\Users\\\\", rendered)
        self.assertNotIn("file:///home/", rendered)


if __name__ == "__main__":
    unittest.main()
