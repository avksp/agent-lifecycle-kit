from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.benchmarks import evaluate_reference_task

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"
FIXTURES = ROOT / "tests/benchmarks/fixtures"


class ReferenceTaskEvaluatorTests(unittest.TestCase):
    def test_accepted_result_with_passing_oracle_passes(self) -> None:
        receipt = evaluate_reference_task(suite_path=SUITE, artifact_path=FIXTURES / "accepted-pass.json")

        self.assertEqual(receipt["schemaVersion"], "agent-reference-task-evaluation.v1")
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["summary"]["falseAcceptanceCount"], 0)
        self.assertEqual(receipt["measurements"]["tokens"]["headline"], {"confidence": "ATTESTED", "total": 200})
        self.assertFalse(receipt["modelCallsStarted"])
        self.assertFalse(receipt["hostLaunchStarted"])

    def test_accepted_result_with_failing_oracle_is_false_acceptance(self) -> None:
        receipt = evaluate_reference_task(suite_path=SUITE, artifact_path=FIXTURES / "accepted-false.json")

        self.assertEqual(receipt["status"], "FAIL")
        self.assertEqual(receipt["summary"]["falseAcceptanceCount"], 1)
        self.assertFalse(receipt["oracle"]["status"] == "PASS")

    def test_missing_usage_is_reported_without_hiding_quality(self) -> None:
        receipt = evaluate_reference_task(suite_path=SUITE, artifact_path=FIXTURES / "missing-usage.json")

        self.assertEqual(receipt["status"], "PASS")
        self.assertIn("usage-export-missing", receipt["measurements"]["measurementGaps"])
        self.assertEqual(receipt["measurements"]["tokens"]["headline"], {"confidence": "MISSING", "total": None})

    def test_untrusted_extra_evidence_is_not_copied_to_receipt(self) -> None:
        submission = json.loads((FIXTURES / "accepted-pass.json").read_text(encoding="utf-8"))
        submission["evidence"]["operatorNote"] = "Bearer example-secret-value at C:\\Users\\example\\private"
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "submission.json"
            artifact.write_text(json.dumps(submission), encoding="utf-8")
            receipt = evaluate_reference_task(suite_path=SUITE, artifact_path=artifact)

        rendered = json.dumps(receipt)
        self.assertNotIn("example-secret-value", rendered)
        self.assertNotIn("C:\\\\Users\\\\", rendered)
        self.assertFalse(receipt["redaction"]["rawContentStored"])


if __name__ == "__main__":
    unittest.main()
