from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import build_implementation_audit_report
from agent_lifecycle.contracts import LifecycleError, canonical_digest, write_json_create
from agent_lifecycle.workflow import accept_task, commit_task_result, rework_task, start_task
from agent_lifecycle.workflow.reviews import validate_task_review
from agent_lifecycle.workflow.run import run_workflow_step


class TaskAcceptanceImplementationAuditGateTests(unittest.TestCase):
    def test_task_review_rejects_every_open_medium_plus_severity(self) -> None:
        state = {"runId": "run", "planDigest": "a" * 64}
        task = {
            "id": "WS-01",
            "attempt": 1,
            "result": {"sha256": "b" * 64},
            "packet": {"sha256": "c" * 64},
        }
        for severity in ("BLOCKER", "CRITICAL", "HIGH", "MEDIUM"):
            review = {
                "schemaVersion": "agent-task-review.v2",
                "runId": "run",
                "taskId": "WS-01",
                "attempt": 1,
                "planDigest": "a" * 64,
                "resultHash": "b" * 64,
                "taskPacketHash": "c" * 64,
                "reviewer": {"independent": True},
                "verdict": "ACCEPTED",
                "findings": [{"id": severity, "status": "open", "severity": severity}],
            }
            with self.subTest(severity=severity), self.assertRaises(LifecycleError) as raised:
                validate_task_review(state, task, review)
            self.assertEqual(raised.exception.code, "task-review-open-findings")

    def test_task_acceptance_requires_accepted_implementation_audit_when_declared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=True)
            start_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path, review_path = _write_result_review(root, bundle)
            commit_task_result(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )

            with self.assertRaises(LifecycleError) as raised:
                accept_task(
                    bundle["statePath"],
                    task_id="WS-01",
                    operation_id="accept-op",
                    expected_revision=3,
                    review_path=review_path,
                    reason="accepted",
                )

            self.assertEqual(raised.exception.code, "implementation-audit-required")
            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )
            write_json_create(root / "work/WS-01/attempt-1/implementation-audit.json", report)

            payload = accept_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="accept-op",
                expected_revision=3,
                review_path=review_path,
                implementation_audit_path="work/WS-01/attempt-1/implementation-audit.json",
                reason="accepted",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "ACCEPTED")
            stored = json.loads(Path(bundle["statePath"]).read_text(encoding="utf-8"))
            stored_task = next(item for item in stored["tasks"] if item["id"] == "WS-01")
            self.assertEqual(stored_task["implementationAuditReport"]["verdict"], "ACCEPTED")

    def test_managed_runner_blocks_when_verifying_task_lacks_required_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="STEP_REVIEW", task_status="VERIFYING", audit_required=True)

            receipt = run_workflow_step(
                state_path=bundle["statePath"],
                manifest_path=bundle["manifestPath"],
                operation_id="managed-op",
                expected_revision=1,
                source_revision="source",
            )

            self.assertEqual(receipt["status"], "FAIL")
            self.assertEqual(receipt["nextAction"]["type"], "blocked")
            self.assertIn("implementation-audit-required", {item["code"] for item in receipt["blockers"]})

    def test_task_rework_accepts_accepted_review_with_rework_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="RUNNING", task_status="READY", audit_required=True)
            state = json.loads(Path(bundle["statePath"]).read_text(encoding="utf-8"))
            state["budgets"] = {"remediationMode": "ask", "maxTaskAttempts": 2, "maxParallelTasks": 1}
            Path(bundle["statePath"]).write_text(json.dumps(state), encoding="utf-8")
            start_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="start-op",
                expected_revision=1,
                source_revision="source",
                reason="launch",
            )
            result_path, review_path = _write_result_review(root, bundle)
            commit_task_result(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="result-op",
                expected_revision=2,
                source_revision="source",
                result_path=result_path,
                reason="done",
            )
            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
                changed_paths=[],
            )
            self.assertEqual(report["verdict"], "REWORK")
            finding_id = next(
                item["id"] for item in report["findings"] if item["code"] == "implementation-changed-paths-stale"
            )
            audit_path = "work/WS-01/attempt-1/implementation-audit.json"
            write_json_create(root / audit_path, report)

            payload = rework_task(
                bundle["statePath"],
                task_id="WS-01",
                operation_id="rework-op",
                expected_revision=3,
                source_revision="source",
                review_path=review_path,
                implementation_audit_path=audit_path,
                finding_ids=[finding_id],
                reason="audit requested rework",
            )

            task = next(item for item in payload["tasks"] if item["id"] == "WS-01")
            self.assertEqual(task["status"], "REWORK")


def _write_bundle(
    root: Path,
    *,
    phase: str,
    task_status: str,
    audit_required: bool,
) -> dict[str, Path | str]:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [
            {
                "id": "WS-01",
                "dependsOn": [],
                "writes": ["src/example.py"],
                "implementationAuditRequired": audit_required,
            }
        ],
        "acceptanceCriteria": [{"id": "AC-01", "evidenceIds": []}],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (manifest_path.parent / "plan.lock.json").write_text(
        json.dumps({"schemaVersion": "agent-plan-lock.v1", "planRevision": 1, "manifestHash": digest}),
        encoding="utf-8",
    )
    state = {
        "schemaVersion": "agent-workflow-state.v3",
        "runId": "run",
        "packageId": "package",
        "planRevision": 1,
        "planDigest": digest,
        "sourceRevision": "source",
        "stateRevision": 1,
        "phase": phase,
        "manifestPath": "plans/package/plan.manifest.json",
        "authorization": {"required": False, "granted": True},
        "tasks": [
            {
                "id": "WS-01",
                "status": task_status,
                "attempt": 0 if task_status == "READY" else 1,
                "dependsOn": [],
                "required": True,
                "writes": ["src/example.py"],
                "acceptanceIds": [],
                "evidenceIds": [],
                "implementationAuditRequired": audit_required,
                "artifactPaths": {
                    "result": "work/WS-01/attempt-{attempt}/task-result.json",
                    "review": "work/WS-01/attempt-{attempt}/task-review.json",
                },
                "packet": {"sha256": "1" * 64},
            }
        ],
        "eventLog": "events.jsonl",
    }
    if task_status == "VERIFYING":
        state["tasks"][0]["result"] = {"path": "work/WS-01/attempt-1/task-result.json", "sha256": "2" * 64, "bytes": 10}
    state_path = root / "run.state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return {"manifestPath": manifest_path, "statePath": state_path, "planDigest": digest}


def _write_result_review(
    root: Path,
    bundle: dict[str, Path | str],
    *,
    reviewer_id: str = "reviewer",
) -> tuple[str, str]:
    result = {
        "schemaVersion": "agent-task-result.v2",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": bundle["planDigest"],
        "sourceRevision": "source",
        "actor": "worker",
        "actorRunId": "worker-run",
        "surface": "test",
        "taskPacketHash": "1" * 64,
        "traceDigest": "4" * 64,
        "changedFiles": ["src/example.py"],
        "changeSet": {
            "provider": "git-worktree-v1",
            "baselineRef": "main",
            "baselineSha": "source",
            "fileSetHash": "5" * 64,
            "diffHash": "6" * 64,
            "snapshotHash": "7" * 64,
        },
        "commands": [{"id": "unit", "status": "PASS", "exitCode": 0}],
        "itemOutcomes": [
            {
                "plannedItemId": "REQ-01",
                "status": "COMPLETE",
                "changedFiles": ["src/example.py"],
                "commandIds": ["unit"],
            }
        ],
        "summary": "done",
        "assumptions": [],
        "blocker": None,
        "contractChangeRequest": None,
    }
    result_path = "work/WS-01/attempt-1/task-result.json"
    write_json_create(root / result_path, result)
    result_digest = canonical_digest(result)
    review = {
        "schemaVersion": "agent-task-review.v2",
        "reviewId": "review-1",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": bundle["planDigest"],
        "resultHash": result_digest,
        "taskPacketHash": "1" * 64,
        "traceDigest": "4" * 64,
        "reviewer": {"id": reviewer_id, "independent": True, "surface": "test", "runId": "review-run"},
        "reviewedAt": "2026-08-03T00:00:00Z",
        "verdict": "ACCEPTED",
        "itemReviews": [{"plannedItemId": "REQ-01", "verdict": "ACCEPTED", "findingIds": []}],
        "acceptanceChecks": [],
        "findings": [],
        "summary": "accepted",
    }
    review_path = "work/WS-01/attempt-1/task-review.json"
    write_json_create(root / review_path, review)
    return result_path, review_path


if __name__ == "__main__":
    unittest.main()
