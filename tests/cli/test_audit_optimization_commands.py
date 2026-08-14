from __future__ import annotations

import contextlib
import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.cli import main  # noqa: E402


class AuditOptimizationCommandTests(unittest.TestCase):
    def test_sample_report_proposal_and_apply_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_paths = []
            for index in range(3):
                path = root / f"receipt-{index}.json"
                path.write_text(json.dumps(_receipt(index)), encoding="utf-8")
                receipt_paths.append(path)
            sample_path = root / "samples.json"
            candidate_path = root / "candidate.json"
            report_path = root / "report.json"
            proposal_path = root / "proposal.json"
            applied_path = root / "profile.json"
            candidate_path.write_text(json.dumps(_candidate()), encoding="utf-8")

            code, sample = _run(["metrics", "audit-sample", *sum((["--receipt", str(path)] for path in receipt_paths), []), "--out", str(sample_path)])
            self.assertEqual(code, 0)
            self.assertEqual(sample["status"], "PASS")
            code, report = _run(["metrics", "audit-report", "--sample", str(sample_path), "--candidate-profile", str(candidate_path), "--out", str(report_path)])
            self.assertEqual(code, 0)
            self.assertEqual(report["status"], "PASS")
            code, proposal = _run(["metrics", "audit-proposal", "--report", str(report_path), "--out", str(proposal_path)])
            self.assertEqual(code, 0)
            self.assertFalse(proposal["applyAllowed"])
            code, approved = _run(["metrics", "audit-proposal", "--report", str(report_path), "--approved", "--out", str(root / "approved-proposal.json")])
            self.assertEqual(code, 0)
            self.assertTrue(approved["applyAllowed"])
            code, applied = _run(["metrics", "audit-apply", "--proposal", str(root / "approved-proposal.json"), "--out", str(applied_path)])
            self.assertEqual(code, 0)
            self.assertEqual(applied["status"], "PASS")
            self.assertTrue(applied_path.is_file())

    def test_terminal_report_is_human_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "samples.json"
            sample.write_text(json.dumps({"schemaVersion": "agent-audit-optimization-sample-batch.v1", "samples": []}), encoding="utf-8")
            out = root / "report.json"
            stdout = StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["metrics", "audit-report", "--sample", str(sample), "--out", str(out), "--terminal"])

        self.assertEqual(code, 0)
        self.assertIn("Audit optimization:", stdout.getvalue())


def _run(arguments: list[str]) -> tuple[int, dict[str, object]]:
    stdout = StringIO()
    with contextlib.redirect_stdout(stdout):
        code = main(arguments)
    return code, json.loads(stdout.getvalue())


def _candidate() -> dict[str, object]:
    return {
        "profileId": "safe",
        "taskShape": "feature",
        "qualityFloor": "standard",
        "routeClass": "standard",
        "packetTokenLimit": 12000,
        "reviewerCountHint": 2,
        "timeoutSeconds": 900,
        "retryLimit": 1,
        "holdoutTasks": [{"taskId": f"task-{index}", "qualityPass": True, "billableTokens": 500, "wallSeconds": 12} for index in range(3)],
    }


def _receipt(index: int) -> dict[str, object]:
    return {
        "operationId": f"operation-{index}",
        "runId": f"run-{index}",
        "packageId": "release-1-70",
        "taskId": f"task-{index}",
        "taskShape": "feature",
        "reviewReceipt": {"schemaVersion": "agent-review-mesh-result.v1", "status": "PASS", "findings": [], "independence": {"status": "INDEPENDENT"}, "reviewer": {"role": "reviewer", "modelClass": "standard"}},
        "usageReceipt": {"usage": {"inputTokens": 1000, "outputTokens": 500, "billableTokens": 1500, "wallSeconds": 12}, "attestation": {"status": "ATTESTED"}},
        "processReceipt": {"resources": {"cpuMs": {"value": 120, "availability": "ATTESTED"}, "peakMemoryMb": {"value": 64, "availability": "ATTESTED"}, "processCount": {"value": 1, "availability": "ATTESTED"}}, "timing": {"elapsedMs": 12000}, "retry": {"count": 0}, "timedOut": False},
        "outcomeReceipt": {"status": "ACCEPTED"},
    }


if __name__ == "__main__":
    unittest.main()
