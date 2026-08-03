from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_lifecycle.audit import (
    build_final_implementation_audit,
    build_implementation_audit_report,
    validate_final_implementation_audit,
    validate_implementation_audit_report,
)
from agent_lifecycle.contracts import canonical_digest, write_json_create


class ImplementationAuditTests(unittest.TestCase):
    def test_task_implementation_audit_accepts_complete_independent_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            result_path, review_path = _write_result_review(root, bundle)

            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )

            self.assertEqual(report["schemaVersion"], "agent-implementation-audit-report.v1")
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["verdict"], "ACCEPTED")
            self.assertEqual(report["ownership"]["status"], "PASS")
            self.assertEqual(validate_implementation_audit_report(report)["status"], "PASS")

    def test_task_implementation_audit_rejects_worker_self_certification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            result_path, review_path = _write_result_review(root, bundle, reviewer_id="worker", reviewer_run_id="worker-run")

            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["verdict"], "REWORK")
            self.assertIn("worker-self-certification", {item["code"] for item in report["blockers"]})

    def test_task_implementation_audit_rejects_unowned_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            result_path, review_path = _write_result_review(root, bundle, changed_files=["other/file.py"])

            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["verdict"], "CONTRACT_CHANGE")
            self.assertIn("implementation-write-scope-violation", {item["code"] for item in report["blockers"]})

    def test_task_implementation_audit_rejects_stale_state_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            result_path, review_path = _write_result_review(root, bundle)

            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
                expected_revision=99,
            )

            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["verdict"], "BLOCKED")
            self.assertIn("state-revision-mismatch", {item["code"] for item in report["blockers"]})

    def test_task_implementation_audit_validation_rejects_forged_pass_with_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root)
            result_path, review_path = _write_result_review(root, bundle)
            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )
            report["blockers"] = [{"code": "still-open"}]
            body = {key: value for key, value in report.items() if key != "reportDigest"}
            report["reportDigest"] = canonical_digest(body)

            validation = validate_implementation_audit_report(report)

            self.assertEqual(validation["status"], "FAIL")
            self.assertIn("implementation-audit-open-blockers", {item["code"] for item in validation["blockers"]})

    def test_final_implementation_audit_aggregates_task_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = _write_bundle(root, phase="FINAL_AUDIT", task_status="ACCEPTED")
            result_path, review_path = _write_result_review(root, bundle)
            report = build_implementation_audit_report(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                task_id="WS-01",
                result_path=result_path,
                review_path=review_path,
            )
            write_json_create(root / "work/WS-01/attempt-1/implementation-audit.json", report)

            final_audit = build_final_implementation_audit(
                manifest_path=bundle["manifestPath"],
                state_path=bundle["statePath"],
                report_paths=["work/WS-01/attempt-1/implementation-audit.json"],
            )

            self.assertEqual(final_audit["schemaVersion"], "agent-final-implementation-audit.v1")
            self.assertEqual(final_audit["status"], "PASS")
            self.assertEqual(validate_final_implementation_audit(final_audit)["status"], "PASS")

    def test_final_implementation_audit_validation_rejects_forged_pass_with_blockers(self) -> None:
        audit = {
            "schemaVersion": "agent-final-implementation-audit.v1",
            "status": "PASS",
            "runId": "run",
            "packageId": "package",
            "planRevision": 1,
            "planDigest": "0" * 64,
            "sourceRevision": "source",
            "auditor": {"id": "auditor", "surface": "test", "independent": True},
            "reports": [],
            "missingTaskIds": [],
            "findings": [],
            "blockers": [{"code": "still-open"}],
            "productionPromotionClaimed": False,
        }
        audit["auditDigest"] = canonical_digest(audit)

        validation = validate_final_implementation_audit(audit)

        self.assertEqual(validation["status"], "FAIL")
        self.assertIn("final-implementation-audit-open-blockers", {item["code"] for item in validation["blockers"]})


def _write_bundle(root: Path, *, phase: str = "STEP_REVIEW", task_status: str = "VERIFYING") -> dict[str, Path | str]:
    manifest = {
        "status": "FROZEN",
        "planRevision": 1,
        "package": {"id": "package", "planArtifactRoot": "plans/package"},
        "readOnly": [],
        "forbiddenWrites": [],
        "leadOwned": [],
        "workstreams": [{"id": "WS-01", "dependsOn": [], "writes": ["src/example.py"]}],
        "acceptanceCriteria": [{"id": "AC-01", "evidenceIds": []}],
    }
    digest = canonical_digest(manifest)
    manifest_path = root / "plans/package/plan.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    state = _state(digest, phase=phase, task_status=task_status)
    state_path = root / "run.state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return {"manifestPath": manifest_path, "statePath": state_path, "planDigest": digest}


def _state(digest: str, *, phase: str, task_status: str) -> dict:
    return {
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
                "attempt": 1,
                "dependsOn": [],
                "required": True,
                "writes": ["src/example.py"],
                "acceptanceIds": [],
                "evidenceIds": [],
                "artifactPaths": {
                    "result": "work/WS-01/attempt-{attempt}/task-result.json",
                    "review": "work/WS-01/attempt-{attempt}/task-review.json",
                },
                "packet": {"sha256": "1" * 64},
                "result": {
                    "path": "work/WS-01/attempt-1/task-result.json",
                    "sha256": "2" * 64,
                    "bytes": 10,
                },
                "review": {
                    "path": "work/WS-01/attempt-1/task-review.json",
                    "sha256": "3" * 64,
                    "bytes": 10,
                    "verdict": "ACCEPTED",
                },
            }
        ],
        "eventLog": "events.jsonl",
    }


def _write_result_review(
    root: Path,
    bundle: dict[str, Path | str],
    *,
    changed_files: list[str] | None = None,
    reviewer_id: str = "reviewer",
    reviewer_run_id: str = "review-run",
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
        "changedFiles": changed_files or ["src/example.py"],
        "changeSet": {
            "provider": "git-worktree-v1",
            "baselineRef": "main",
            "baselineSha": "source",
            "fileSetHash": "5" * 64,
            "diffHash": "6" * 64,
            "snapshotHash": "7" * 64,
        },
        "commands": [{"id": "unit", "status": "PASS", "exitCode": 0}],
        "itemOutcomes": [{"plannedItemId": "REQ-01", "status": "COMPLETE", "changedFiles": ["src/example.py"], "commandIds": ["unit"]}],
        "summary": "done",
        "assumptions": [],
        "blocker": None,
        "contractChangeRequest": None,
    }
    result_path = "work/WS-01/attempt-1/task-result.json"
    write_json_create(root / result_path, result)
    digest = canonical_digest(result)
    review = {
        "schemaVersion": "agent-task-review.v2",
        "reviewId": "review-1",
        "runId": "run",
        "taskId": "WS-01",
        "attempt": 1,
        "planDigest": bundle["planDigest"],
        "resultHash": digest,
        "taskPacketHash": "1" * 64,
        "traceDigest": "4" * 64,
        "reviewer": {"id": reviewer_id, "independent": True, "surface": "test", "runId": reviewer_run_id},
        "reviewedAt": "2026-08-03T00:00:00Z",
        "verdict": "ACCEPTED",
        "itemReviews": [{"plannedItemId": "REQ-01", "verdict": "ACCEPTED", "findingIds": []}],
        "acceptanceChecks": [],
        "findings": [],
        "summary": "accepted",
    }
    review_path = "work/WS-01/attempt-1/task-review.json"
    write_json_create(root / review_path, review)
    state_path = bundle["statePath"]
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    state["tasks"][0]["result"]["sha256"] = digest
    state["tasks"][0]["result"]["bytes"] = len(json.dumps(result).encode("utf-8"))
    state["tasks"][0]["review"]["sha256"] = canonical_digest(review)
    Path(state_path).write_text(json.dumps(state), encoding="utf-8")
    return result_path, review_path


if __name__ == "__main__":
    unittest.main()
