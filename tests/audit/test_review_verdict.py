from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.audit import compact_review_routing, validate_review_verdict  # noqa: E402
from agent_lifecycle.audit.review_verdict import validate_review_verdict as facade_validate_review_verdict  # noqa: E402
from agent_lifecycle.cli import main  # noqa: E402
from agent_lifecycle.contracts import LifecycleError  # noqa: E402
from agent_lifecycle.contracts.review_verdict import validate_review_verdict as contract_validate_review_verdict  # noqa: E402
from agent_lifecycle.workflow.reviews import validate_task_review  # noqa: E402


class ReviewVerdictTests(unittest.TestCase):
    def test_audit_module_remains_a_contract_facade(self) -> None:
        self.assertIs(facade_validate_review_verdict, contract_validate_review_verdict)

    def test_review_verdict_accepts_split_quality_dimensions(self) -> None:
        verdict = _accepted_verdict()

        validation = validate_review_verdict(verdict)
        summary = compact_review_routing(verdict)

        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(summary["nextAction"], "accept")
        self.assertEqual(summary["dimensionStatus"]["requirementFit"], "PASS")

    def test_review_verdict_rejects_accept_with_failed_dimension(self) -> None:
        verdict = _accepted_verdict()
        verdict["dimensions"]["evidenceQuality"]["status"] = "FAIL"
        verdict["dimensions"]["evidenceQuality"]["reasonCode"] = "missing-receipt"

        validation = validate_review_verdict(verdict)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("review-verdict-accepted-with-blockers", {item["code"] for item in validation["blockers"]})

    def test_task_review_validates_structured_verdict_when_present(self) -> None:
        state = {"runId": "run-1", "planDigest": "a" * 64}
        task = {
            "id": "WS-01",
            "attempt": 1,
            "result": {"sha256": "b" * 64},
            "packet": {"sha256": "c" * 64},
        }
        review = {
            "schemaVersion": "agent-task-review.v2",
            "runId": "run-1",
            "taskId": "WS-01",
            "attempt": 1,
            "planDigest": "a" * 64,
            "resultHash": "b" * 64,
            "taskPacketHash": "c" * 64,
            "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "codex", "independent": True},
            "verdict": "ACCEPTED",
            "findings": [],
            "reviewVerdict": _accepted_verdict(),
        }

        validate_task_review(state, task, review)

    def test_task_review_rejects_invalid_structured_verdict(self) -> None:
        state = {"runId": "run-1", "planDigest": "a" * 64}
        task = {
            "id": "WS-01",
            "attempt": 1,
            "result": {"sha256": "b" * 64},
            "packet": {"sha256": "c" * 64},
        }
        review = {
            "schemaVersion": "agent-task-review.v2",
            "runId": "run-1",
            "taskId": "WS-01",
            "attempt": 1,
            "planDigest": "a" * 64,
            "resultHash": "b" * 64,
            "taskPacketHash": "c" * 64,
            "reviewer": {"id": "reviewer", "runId": "review-run", "surface": "codex", "independent": True},
            "verdict": "ACCEPTED",
            "findings": [],
            "reviewVerdict": {**_accepted_verdict(), "routing": {"nextAction": "fix-implementation"}},
        }

        with self.assertRaises(LifecycleError) as raised:
            validate_task_review(state, task, review)
        self.assertEqual(raised.exception.code, "task-review-verdict-invalid")

    def test_audit_review_check_cli_accepts_review_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            review = Path(tmp) / "review.json"
            review.write_text(json.dumps({"reviewVerdict": _accepted_verdict(), "findings": []}), encoding="utf-8")
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = main(["audit", "review-check", "--review", str(review)])

            payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "PASS")


def _accepted_verdict() -> dict[str, object]:
    return {
        "schemaVersion": "agent-review-verdict.v1",
        "overall": "ACCEPTED",
        "dimensions": {
            "requirementFit": {"status": "PASS", "reasonCode": "requirements-met", "summary": "All acceptance criteria are covered."},
            "implementationQuality": {"status": "PASS", "reasonCode": "quality-met", "summary": "Implementation is scoped and maintainable."},
            "evidenceQuality": {"status": "PASS", "reasonCode": "evidence-current", "summary": "Validation receipts are current."},
            "residualRisk": {"status": "PASS", "reasonCode": "risk-low", "summary": "No blocking residual risk remains."},
        },
        "routing": {"nextAction": "accept", "target": "task"},
    }


if __name__ == "__main__":
    unittest.main()
