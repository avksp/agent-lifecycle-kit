from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.benchmarks import evaluate_reference_task
from agent_lifecycle.contracts import canonical_digest

try:
    from .helpers import _run_cli
except ImportError:
    from helpers import _run_cli

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "benchmarks/reference-tasks/manifest.json"
FIXTURES = ROOT / "tests/benchmarks/fixtures"


class BenchmarkCliTests(unittest.TestCase):
    def test_evaluate_emits_and_writes_pass_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evaluation.json"
            code, payload = _run_cli(
                ["benchmark", "evaluate", "--suite", str(SUITE), "--artifact", str(FIXTURES / "accepted-pass.json"), "--out", str(out)]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)

    def test_false_acceptance_is_negative_receipt_not_cli_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evaluation.json"
            code, payload = _run_cli(
                ["benchmark", "evaluate", "--suite", str(SUITE), "--artifact", str(FIXTURES / "accepted-false.json"), "--out", str(out)]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "FAIL")
            self.assertEqual(payload["summary"]["falseAcceptanceCount"], 1)

    def test_evaluate_does_not_overwrite_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evaluation.json"
            out.write_text("occupied", encoding="utf-8")

            code, payload = _run_cli(
                ["benchmark", "evaluate", "--suite", str(SUITE), "--artifact", str(FIXTURES / "accepted-pass.json"), "--out", str(out)]
            )

            self.assertEqual(code, 2)
            self.assertEqual(payload["code"], "output-already-exists")

    def test_evaluate_rejects_excessive_evidence_nesting_with_typed_error(self) -> None:
        evidence: dict = {"schemaVersion": "agent-plan-validation.v1", "status": "FROZEN"}
        for _ in range(65):
            evidence = {"nested": evidence}
        submission = {
            "schemaVersion": "agent-reference-task-submission.v1",
            "taskId": "rt01-planning",
            "taskVersion": "1.0.0",
            "accepted": True,
            "evidence": evidence,
            "productionPromotionClaimed": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "deep-submission.json"
            artifact.write_text(json.dumps(submission), encoding="utf-8")
            code, payload = _run_cli(
                ["benchmark", "evaluate", "--suite", str(SUITE), "--artifact", str(artifact)]
            )

        self.assertEqual(code, 2)
        self.assertEqual(payload["code"], "reference-submission-evidence-depth")

    def test_evaluate_accepts_evidence_at_depth_limit(self) -> None:
        evidence: dict = {"schemaVersion": "agent-plan-validation.v1", "status": "FROZEN"}
        for _ in range(64):
            evidence = {"nested": evidence}
        submission = {
            "schemaVersion": "agent-reference-task-submission.v1",
            "taskId": "rt01-planning",
            "taskVersion": "1.0.0",
            "accepted": True,
            "evidence": evidence,
            "productionPromotionClaimed": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "boundary-submission.json"
            artifact.write_text(json.dumps(submission), encoding="utf-8")
            code, payload = _run_cli(
                ["benchmark", "evaluate", "--suite", str(SUITE), "--artifact", str(artifact)]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "FAIL")

    def test_compare_writes_quality_first_receipt(self) -> None:
        baseline = evaluate_reference_task(suite_path=SUITE, artifact_path=FIXTURES / "accepted-pass.json")
        candidate = json.loads(json.dumps(baseline))
        candidate["measurements"]["tokens"]["headline"]["total"] = 150
        candidate["evaluationDigest"] = canonical_digest(
            {key: value for key, value in candidate.items() if key != "evaluationDigest"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_path = root / "baseline.json"
            candidate_path = root / "candidate.json"
            out = root / "comparison.json"
            baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
            candidate_path.write_text(json.dumps(candidate), encoding="utf-8")

            code, payload = _run_cli(
                [
                    "benchmark",
                    "compare",
                    "--baseline",
                    str(baseline_path),
                    "--candidate",
                    str(candidate_path),
                    "--out",
                    str(out),
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload["schemaVersion"], "agent-reference-task-comparison.v1")
            self.assertTrue(payload["decision"]["qualityFirst"])
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
