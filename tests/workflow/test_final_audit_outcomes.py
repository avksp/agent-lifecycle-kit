from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from agent_lifecycle.contracts import LifecycleError, write_json_create  # noqa: E402
from agent_lifecycle.workflow import apply_final_audit_outcome, finalize_run, start_task, status  # noqa: E402
from agent_lifecycle.workflow.artifacts import artifact_identity  # noqa: E402


class FinalAuditOutcomeTests(unittest.TestCase):
    def test_rework_archives_accepted_attempt_and_opens_attempt_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_v4_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(status(state_path)["nextAction"]["type"], "final-audit-outcome")
            result = {"schemaVersion": "agent-task-result.v2", "status": "PASS", "changedFiles": []}
            review = {
                "schemaVersion": "agent-task-review.v2",
                "status": "PASS",
                "verdict": "ACCEPTED",
                "reviewId": "review-1",
            }
            result_path = root / "work/WS-01/attempt-1/task-result.json"
            review_path = root / "work/WS-01/attempt-1/task-review.json"
            write_json_create(result_path, result)
            write_json_create(review_path, review)
            task = state["tasks"][0]
            task["result"] = artifact_identity(root, "work/WS-01/attempt-1/task-result.json", result)
            task["review"] = artifact_identity(root, "work/WS-01/attempt-1/task-review.json", review)
            state_path.write_text(json.dumps(state), encoding="utf-8")
            audit = _final_audit(
                state,
                status="FAIL",
                semantic_status="CHANGES_REQUIRED",
                findings=[{"id": "F-1", "status": "open", "severity": "HIGH", "taskId": "WS-01"}],
            )
            write_json_create(root / "final/final-audit.json", audit)

            payload = apply_final_audit_outcome(
                state_path,
                operation_id="final-rework",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                verdict="REWORK",
                task_ids=["WS-01"],
                finding_ids=["F-1"],
                reason="address final finding",
            )

            self.assertEqual(payload["phase"], "RUNNING")
            self.assertEqual(payload["tasks"][0]["status"], "REWORK")
            state = json.loads(state_path.read_text(encoding="utf-8"))
            task = state["tasks"][0]
            self.assertEqual(task["attemptHistory"][0]["attempt"], 1)
            self.assertEqual(task["remediationFindingIds"], ["F-1"])
            self.assertNotIn("result", task)
            self.assertEqual(state["finalAuditOutcome"]["verdict"], "REWORK")

            payload = start_task(
                state_path,
                task_id="WS-01",
                operation_id="start-attempt-two",
                expected_revision=2,
                source_revision="source",
                reason="remediation",
            )
            self.assertEqual(payload["tasks"][0]["attempt"], 2)
            self.assertEqual(payload["tasks"][0]["status"], "RUNNING")

            state_path = _write_v4_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["finalAuditOutcome"] = {"verdict": "REWORK"}
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(status(state_path)["nextAction"]["type"], "final-audit-outcome")

    def test_v4_finalize_requires_accepted_final_audit_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = _write_v4_state(Path(tmp))
            with self.assertRaises(LifecycleError) as raised:
                finalize_run(
                    state_path,
                    operation_id="missing-outcome",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    proof_path="final/proof.json",
                    reason="finalize without verdict",
                )
            self.assertEqual(raised.exception.code, "final-audit-outcome-required")

    def test_rework_rejects_finding_without_named_task_and_leaves_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_v4_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            audit = _final_audit(
                state,
                status="FAIL",
                semantic_status="CHANGES_REQUIRED",
                findings=[{"id": "F-1", "status": "open", "severity": "HIGH"}],
            )
            write_json_create(root / "final/final-audit.json", audit)

            with self.assertRaises(LifecycleError) as raised:
                apply_final_audit_outcome(
                    state_path,
                    operation_id="invalid-rework",
                    expected_revision=1,
                    source_revision="source",
                    final_audit_path="final/final-audit.json",
                    verdict="REWORK",
                    task_ids=["WS-01"],
                    finding_ids=["F-1"],
                    reason="invalid mapping",
                )

            self.assertEqual(raised.exception.code, "final-audit-outcome-task-mapping")
            unchanged = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(unchanged["stateRevision"], 1)
            self.assertNotIn("finalAuditOutcome", unchanged)

    def test_blocked_outcome_requires_external_receipt_and_clears_typed_blocker_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = _write_v4_state(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            audit = _final_audit(
                state,
                status="FAIL",
                semantic_status="BLOCKED",
                findings=[],
            )
            audit["blocker"] = {
                "externalAction": {
                    "actionId": "release-approval",
                    "expectedReceiptPath": "external/release-approval.json",
                }
            }
            write_json_create(root / "final/final-audit.json", audit)

            payload = apply_final_audit_outcome(
                state_path,
                operation_id="final-blocked",
                expected_revision=1,
                source_revision="source",
                final_audit_path="final/final-audit.json",
                verdict="BLOCKED",
                reason="awaiting operator approval",
            )
            self.assertEqual(payload["phase"], "WAITING_FOR_EXTERNAL_ACTION")
            self.assertEqual(payload["nextAction"]["type"], "record-external-action-receipt")
            self.assertEqual(payload["blocker"]["recoveryRoute"], "external-action")


def _write_v4_state(root: Path) -> Path:
    state_path = root / "run.state.json"
    state = {
        "schemaVersion": "agent-workflow-state.v4",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": "0" * 64,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": "FINAL_AUDIT",
        "runStartedAt": "2026-07-22T00:00:00Z",
        "packageRoot": ".",
        "eventLog": "events.jsonl",
        "operationLedger": {},
        "authorization": {"required": False, "granted": True},
        "startMode": "approval-required",
        "budgets": {"maxTaskAttempts": 2, "remediationMode": "ask", "maxParallelTasks": 1},
        "tasks": [
            {
                "id": "WS-01",
                "title": "Task",
                "owner": "worker",
                "status": "ACCEPTED",
                "attempt": 1,
                "attemptHistory": [],
                "dependsOn": [],
                "writes": ["src"],
                "required": True,
                "artifactPaths": {
                    "result": "work/WS-01/attempt-{attempt}/task-result.json",
                    "review": "work/WS-01/attempt-{attempt}/task-review.json",
                },
            }
        ],
        "blocker": None,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path


def _final_audit(
    state: dict,
    *,
    status: str,
    semantic_status: str,
    findings: list[dict],
) -> dict:
    return {
        "schemaVersion": "agent-final-candidate-audit.v1",
        "status": status,
        "semanticStatus": semantic_status,
        "runId": state["runId"],
        "packageId": state["packageId"],
        "planRevision": state["planRevision"],
        "planDigest": state["planDigest"],
        "sourceRevision": state["sourceRevision"],
        "productionPromotionClaimed": False,
        "verifier": {"id": "final-auditor", "independent": True},
        "findings": findings,
    }


if __name__ == "__main__":
    unittest.main()
